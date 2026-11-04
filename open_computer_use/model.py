"""The action space, and the single request that chooses an operation and a target.

One observation produces one indexed element table. One request asks, on the
same state, which operation to run and which target each operation would use.
The executor consumes only the head matching the chosen operation; the rest is
speculation that cost no extra round trip.
"""

import json
import math
import os
import time

import httpx

from .actions import (
    PIXEL_CONTROLS, action_space, head_properties, object_format_instructions,
    parameter_properties, questions_for, schema_format,
)
from .questions import GUARD_CHOICE, GUARD_LEVELS, NEXT_ACTION, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=60)


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as error:
            # A decision request changes nothing, so a connection that dropped
            # on the way out is safe to send again — and this one only retried
            # HTTP status codes, so a single TLS EOF from the provider ended
            # the run outright. Retried on the same schedule as a 503.
            if attempt < 2:
                time.sleep(0.4 * 2**attempt)
                continue
            # Name the failure. "Model connection failed" reads the same for a
            # timeout, a refused connection and DNS, which are three different
            # things to do next, and it hid all three behind `from None`. The
            # URL's host is safe to say; the key is in a header and never in
            # this message.
            host = httpx.URL(url).host
            raise RuntimeError(
                f"Could not reach {host}: {type(error).__name__}: {error}. No operation executed."
            ) from error
        if response.status_code in {408, 429, 500, 502, 503, 529} and attempt < 2:
            time.sleep(0.4 * 2**attempt)
            continue
        if response.is_error:
            detail = response.text[:300]
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}: {detail}")
        return response.json()
    raise RuntimeError("Model unavailable")


def names(needle, base_url, model):
    """Whether the provider or the model is the one named.

    Both of the checks below used to read the base URL alone, which is right
    until the same model arrives through a gateway. `deepseek-v4.1-flash`
    served from openrouter.ai is still DeepSeek and the URL no longer says so,
    so both checks silently took the wrong branch and every run through that
    gateway failed the same way: reasoning left on, the output budget spent on
    it, the JSON truncated, "no parseable answer". That is the exact failure
    the note in `reasoning_body` describes, arriving by the one route its own
    check could not see.
    """
    return needle in (base_url or "").lower() or needle in (model or "").lower()


def reasoning_body(base_url, model):
    """Turn extended thinking off where it is on by default.

    Picking an operation from an enumerated table is not a reasoning task, and
    a model that thinks first spends its whole output budget doing it: a
    `deepseek-flash` answer measured here was 417 reasoning tokens to 13 tokens
    of JSON, and on a real action space the JSON is what gets truncated.

    `DECISION_REASONING=default` leaves the provider's own behaviour alone.
    """
    if os.environ.get("DECISION_REASONING") == "default":
        return {}
    if names("deepseek", base_url, model):
        # Two spellings, because the gateway and the vendor disagree and
        # sending the one the endpoint does not know is ignored, not refused.
        return {"thinking": {"type": "disabled"}, "reasoning": {"enabled": False}}
    return {}


def uses_json_schema(base_url, model=""):
    """Whether this endpoint can constrain the answer server-side.

    `DECISION_RESPONSE_FORMAT` overrides the guess. DeepSeek, for one,
    guarantees valid JSON but not a given schema.
    """
    override = os.environ.get("DECISION_RESPONSE_FORMAT")
    if override:
        return override == "json_schema"
    return not names("deepseek", base_url, model)


def operation_distribution(payload, chosen, operations):
    """Best-effort probabilities over the operation head, from token logprobs.

    Providers that do not return logprobs simply get no distribution; the
    inspector then shows the model's own confidence instead.
    """
    try:
        tokens = payload["choices"][0]["logprobs"]["content"]
    except (KeyError, IndexError, TypeError):
        return {}
    seen = ""
    for position, token in enumerate(tokens):
        seen += token.get("token", "")
        if not seen.rstrip().endswith('"operation":') and not seen.rstrip().endswith('"operation": "'):
            continue
        # The value's first token discriminates between the candidates.
        for candidate in tokens[position:][:3]:
            alternatives = candidate.get("top_logprobs") or []
            if not alternatives:
                continue
            weights = {}
            for alternative in alternatives:
                piece = alternative["token"].strip().strip('"')
                if not piece:
                    continue
                matches = [name for name in operations if name.startswith(piece)]
                if not matches:
                    continue
                share = math.exp(alternative["logprob"]) / len(matches)
                for name in matches:
                    weights[name] = weights.get(name, 0.0) + share
            total = sum(weights.values())
            # Every alternative can underflow to zero, which is not a distribution.
            if chosen in weights and len(weights) > 1 and total > 0:
                return {name: round(value / total, 4) for name, value in sorted(weights.items())}
        return {}
    return {}


def user_content(state, capture):
    """The observed state, with the picture attached when there is one."""
    text = json.dumps(state, ensure_ascii=False)
    if not capture:
        return text
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{capture['media_type']};base64,{capture['image']}"},
        },
    ]


def number(value):
    """A finite number, whether it arrived as one or as a string of one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def jev_questions(operations, targets):
    """The same heads, as named questions instead of fields of one JSON object.

    The shape barely has to be translated, which is the point: this project's
    decision was always an operation chosen from a set and one index chosen per
    operation. Writing that as a schema and asking a chat model to fill it in
    is a way of getting a choice out of something built to write prose. Here
    the choice is what the endpoint returns.
    """
    questions = {
        "operation": {"type": "choice", "instructions": NEXT_ACTION, "criteria": dict(operations)},
        "risk": {"type": "score", "instructions": GUARD_CHOICE, "criteria": list(GUARD_LEVELS)},
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "instructions": f"{TARGET}\n\nThe operation assumed by this answer is {operation}.",
            # Criteria keys are JSON object keys and so are strings; the action
            # space keys them by index, which is what they are turned back into.
            "criteria": {str(key): candidate.get("label") for key, candidate in candidates.items()},
        }
    for name, spec in parameter_properties(operations, targets).items():
        questions[name] = {"type": "choice", "instructions": spec.get("description", name),
                           "criteria": {str(value): str(value) for value in spec["enum"]}}
    return questions


def jev_reason(rating):
    """The level a score mostly landed on, in the level's own words.

    A backend that cannot write a sentence can still say which of the three
    tiers it read the operation as, and that is all `risk_reason` ever was.
    """
    probabilities = rating.get("probabilities") or {}
    if not probabilities:
        return ""
    top = max(probabilities, key=lambda level: probabilities[level])
    return (rating.get("legend") or {}).get(top, "")


def ask_jev(state, operations, targets):
    """The System One backend: every head answered with a choice and a distribution.

    Nothing here asks for JSON, because nothing here asks for writing. The
    probabilities come back measured rather than reconstructed from token
    logprobs, and the risk rating lands between its levels on its own instead
    of a model picking a round number.

    It takes text only, so the pixel path is not routed here — see `choose`.
    """
    base = os.environ.get("JEV_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/")
    key = os.environ.get("JEV_API_KEY")
    body = {
        "state": state,
        "model": os.environ.get("JEV_MODEL", "jev-latest"),
        "questions": jev_questions(operations, targets),
    }
    started = time.perf_counter()
    payload = post_json(base + "/systemone", key, body)
    latency = round((time.perf_counter() - started) * 1000)
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict) or "operation" not in answers:
        raise ValueError("The decision model returned no operation; no operation executed.")

    picked = answers["operation"]
    answer = {"operation": picked.get("choice"), "confidence": picked.get("confidence")}
    for name, reply in answers.items():
        if not name.endswith("_target"):
            continue
        candidates = targets.get(name[: -len("_target")].upper(), {})
        by_text = {str(index): index for index in candidates}
        answer[name] = by_text.get(reply.get("choice"), reply.get("choice"))

    for name, spec in parameter_properties(operations, targets).items():
        picked_value = (answers.get(name) or {}).get("choice")
        choices = {str(value): value for value in spec["enum"]}
        answer[name] = choices.get(str(picked_value))
    rating = answers.get("risk") or {}
    if isinstance(rating.get("score"), (int, float)):
        answer["risk"] = rating["score"] / max(1, len(GUARD_LEVELS) - 1)
    answer["risk_reason"] = jev_reason(rating)
    return {
        "answer": answer,
        "probabilities": picked.get("probabilities") or {},
        "model": payload.get("model", body["model"]),
        "usage": payload.get("usage", {}),
        "latency_ms": latency,
    }


def ask_chat(state, operations, targets, capture):
    """The OpenAI-compatible backend: one JSON object carrying every head."""
    base = os.environ.get("DECISION_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("DECISION_API_KEY")
    if not key:
        raise RuntimeError("Set DECISION_API_KEY (and DECISION_BASE_URL / DECISION_MODEL) before running.")
    model = os.environ.get("DECISION_MODEL", "gpt-5.6")
    properties = head_properties(operations, targets)
    strict = uses_json_schema(base, model)
    instructions = NEXT_ACTION if strict else NEXT_ACTION + "\n\n" + object_format_instructions(properties)
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "logprobs": True,
        "top_logprobs": 8,
        "response_format": schema_format(properties) if strict else {"type": "json_object"},
        **reasoning_body(base, model),
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content(state, capture)},
        ],
    }
    started = time.perf_counter()
    payload = post_json(base + "/chat/completions", key, body)
    latency = round((time.perf_counter() - started) * 1000)
    try:
        answer = json.loads(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, ValueError):
        raise ValueError("The decision model returned no parseable answer; no operation executed.") from None
    return {
        "answer": answer,
        "probabilities": operation_distribution(payload, answer.get("operation"), operations),
        "model": payload.get("model", body["model"]),
        "usage": payload.get("usage", {}),
        "latency_ms": latency,
    }


def past_action(step):
    """One history row as the model sees it.

    `outcome` is carried only when the step has one, which is only when it did
    not run cleanly. Without it a refused operation and one that ran and moved
    nothing are the same row — `window_changed: false` — and the obvious read of
    that row is to try the same control again.
    """
    row = {k: step.get(k) for k in ("operation", "label", "text", "window_changed")}
    for key in ("outcome", "disposition", "secure"):
        if step.get(key):
            row[key] = step[key]
    return row


def choose(page, goal, history, capture=None, pointer=False, refused=()):
    """One request: the operation, a target for every operation, and a risk rating.

    `capture` is a screenshot of the window, passed when the tree is too sparse
    to work from. `pointer` says whether the operations aimed at that picture
    may be offered, and the two are separate on purpose. Photographing a window
    needs nothing from the user — `screencapture` reads a window that is behind
    everything else — while clicking a point in it, as delivered here, needs the
    app in front. Tying them together meant a window could not be looked at
    without being raised, and the looking is the half that costs nothing.

    `refused` is (operation, path) pairs the app has turned down on this window
    since it last changed. They are dropped from the table rather than argued
    about in the prompt.
    """
    elements, targets, controls = action_space(
        page, pixels=bool(capture) and pointer, refused=refused, pointer=pointer
    )
    operations = questions_for(targets, controls)
    state = {
        "goal": goal,
        "window": {"app": page["app"], "title": page["window"], "visible_text": page["text"]},
        "elements": elements,
        "menu_commands": [{"index": i["index"], "command": i["label"]} for i in page.get("menus", [])],
        # `outcome` only rides along when there is one, which is when the step
        # did not run cleanly. Without it a refusal and a press that landed on
        # something inert are the same row — `window_changed: false` — and the
        # obvious next move from that row is to press the same thing again.
        "recent_actions": [past_action(h) for h in history[-10:]],
        "offered_operations": operations,
    }
    # Only when it happened. The bridge has always reported this and nothing
    # read it, so a window with more elements than the limit allows reached the
    # model looking complete — the one kind of wrong table that cannot be
    # noticed from the inside. Said conditionally, so a window that fits pays
    # nothing for the warning.
    if page.get("complete") is False:
        state["window"].update(complete=False, truncations=page.get("truncations", []))
    if page.get("truncated"):
        state["table_is_incomplete"] = (
            f"This window has more elements than the {len(elements)} listed; the rest were cut off. "
            "What you are looking for may exist and not be here. Scrolling brings different "
            "elements into view. Choosing something that merely looks close is worse than BLOCKED."
        )
    if capture:
        state["screenshot"] = {
            "why": (
                "This window exposes almost nothing to the accessibility tree, so most of what "
                "you can see in the picture has no element index. Prefer an indexed element when "
                "one fits; fall back to CLICK_POINT only for what the table does not contain."
                if pointer
                else "This window exposes almost nothing to the accessibility tree. The picture is "
                "here to be read, not aimed at: nothing in it can be clicked, because clicking a "
                "point needs the app in front and this run was not given permission to raise it. "
                "Use it to understand what the few offered elements are, and to say BLOCKED with a "
                "reason rather than guessing."
            ),
            "width": capture["image_width"],
            "height": capture["image_height"],
        }
        if pointer:
            state["screenshot"]["coordinates"] = (
                "Top-left origin. click_x is 0 to width, click_y is 0 to height."
            )
    # Which backend answers is decided by whether the window can be described
    # in text at all. A System One model returns a choice, which is the whole
    # shape of this decision and the argument the README makes; it also takes
    # text only. When the tree is too sparse to describe, the choice has to be
    # read off a picture, and that goes to the multimodal backend instead — the
    # one path where writing the answer out is the price of being able to see.
    if capture or not os.environ.get("JEV_API_KEY"):
        reply = ask_chat(state, operations, targets, capture)
    else:
        reply = ask_jev(state, operations, targets)
    answer = reply["answer"]

    operation = answer.get("operation")
    if operation not in operations:
        raise ValueError(f"The decision model chose {operation!r}, which was not offered; no operation executed.")

    action, target = None, None
    if operation in targets:
        target = answer.get(operation.lower() + "_target")
        if target not in targets[operation]:
            raise ValueError(f"{operation} target {target!r} was not offered; no operation executed.")
        action = targets[operation][target]
    elif operation in controls:
        action = dict(controls[operation])
        if operation == "CLICK_POINT":
            # A number sent as "136" is a formatting habit, not a different
            # answer, and the bounds check below is what actually decides
            # whether the point is usable. Refusing the string only meant
            # refusing the provider.
            x, y = (number(answer.get(key)) for key in ("click_x", "click_y"))
            if x is None or y is None:
                raise ValueError("CLICK_POINT came back without a usable point; no operation executed.")
            width, height = capture["image_width"], capture["image_height"]
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f"CLICK_POINT {x},{y} is outside the {width}x{height} capture; nothing executed.")
            # The scale travels with the capture the point was named in, so a
            # stale screenshot cannot be turned into a click somewhere else.
            # The window's identity and size travel with it too, because the
            # scale alone is not enough: a window that was resized between the
            # picture and the click maps the same point somewhere else, and the
            # click would land by coincidence. The bridge has always refused
            # that; until this it was never given what it needed to notice.
            action.update(
                x=float(x),
                y=float(y),
                scale=capture["scale"],
                window_id=capture["window_id"],
                window_size=capture["window_size"],
                label=f"point {int(x)},{int(y)}",
            )
        elif operation == "TYPE_KEYS":
            action["label"] = "focused field"

    if operation in {"KEY_CHORD", "SELECT_TEXT", "DRAG"}:
        for name, spec in parameter_properties({operation}, targets).items():
            if answer.get(name) not in spec["enum"] or isinstance(answer.get(name), bool):
                raise ValueError(f"Invalid {name}; nothing executed.")
        if operation == "KEY_CHORD":
            action["key"] = answer["key_chord_key"]
        elif operation == "SELECT_TEXT":
            action.update(start=int(answer["selection_start"]), length=int(answer["selection_length"]))
        else:
            action["destination_path"] = targets["DRAG"][answer["drag_destination"]]["path"]
    if operation == "DRAG_POINT":
        coordinates = [number(answer.get(name)) for name in ("drag_start_x", "drag_start_y", "drag_end_x", "drag_end_y")]
        for i, coordinate in enumerate(coordinates):
            bound = capture["image_width" if i % 2 == 0 else "image_height"]
            if coordinate is None or not 0 <= coordinate < bound:
                raise ValueError("The drag point leaves the capture; nothing executed.")
        action.update(start=coordinates[:2], end=coordinates[2:], scale=capture["scale"],
                      window_id=capture["window_id"], window_size=capture["window_size"])

    risk = answer.get("risk")
    if not isinstance(risk, (int, float)) or not math.isfinite(risk):
        risk = 1.0  # An unreadable rating is treated as the consequential case.
    return {
        "operation": operation,
        "target": target,
        "action": action,
        "text": answer.get("keys_value") if operation == "TYPE_KEYS" else answer.get(operation.lower() + "_value"),
        "pixels": bool(capture) and operation in PIXEL_CONTROLS,
        "confidence": max(0.0, min(1.0, float(answer.get("confidence") or 0))),
        "risk": max(0.0, min(1.0, float(risk))),
        "risk_reason": str(answer.get("risk_reason") or "")[:300],
        "probabilities": reply["probabilities"],
        "model": reply["model"],
        "usage": reply["usage"],
        "latency_ms": reply["latency_ms"],
        "offered": {"operations": sorted(operations), "targets": {k: sorted(v) for k, v in targets.items()}},
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "window": {"title": page["window"], "text": page["text"][:4000]},
        "recent_actions": [{k: h.get(k) for k in ("label", "text")} for h in history[-6:]],
    }


def field_text(context):
    """Fallback for a decision backend that only chooses and cannot write text."""
    key = os.environ.get("TEXT_MODEL_API_KEY") or os.environ.get("DECISION_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs a text model; no value is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", os.environ.get("DECISION_BASE_URL", "https://api.openai.com/v1"))
    model = os.environ.get("TEXT_MODEL", os.environ.get("DECISION_MODEL", "gpt-5.6"))
    started = time.perf_counter()
    payload = post_json(
        base.rstrip("/") + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            **reasoning_body(base, model),
            "messages": [
                {"role": "system", "content": TEXT_VALUE + ' Reply as {"text": "..."} or {"text": null}.'},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
        },
    )
    # One message per reason. "No valid field value" covered a refusal, a
    # malformed answer and an answer that was simply too long, and the operator
    # reading the traceback could not tell which had happened — nor whether
    # asking again would help.
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, TypeError, IndexError):
        raise ValueError("The text model returned no message; nothing was typed.") from None
    try:
        output = json.loads(content)
    except ValueError:
        raise ValueError(f"The text model did not answer with JSON: {content[:120]!r}; nothing was typed.") from None
    if not isinstance(output, dict) or "text" not in output:
        raise ValueError(f"The text model answered {content[:120]!r}, which has no text; nothing was typed.")
    value = output["text"]
    if value is None:
        raise ValueError("The text model declined to supply a value for this field; nothing was typed.")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"The text model supplied {value!r}, which is not a value; nothing was typed.")
    if len(value) > 2000:
        raise ValueError(f"The text model supplied {len(value)} characters, over the 2000 limit; nothing was typed.")
    if set(output) != {"text"}:
        extra = ", ".join(sorted(set(output) - {"text"}))
        raise ValueError(f"The text model added {extra} alongside the value; nothing was typed.")
    return value, {"model": model, "latency_ms": round((time.perf_counter() - started) * 1000)}
