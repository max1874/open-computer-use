"""One decision per line, for an executor that lives in another process.

    $ python3 -m open_computer_use.decide
    {"goal": "...", "ax": "Window: ...", "history": []}
    {"operation": "PRESS", "index": "17", "label": "1", "risk": 0.08, ...}

Stateless on purpose. The caller owns the loop, the history and the app, which
is what `runtime/loop.mjs` already has to own anyway: Computer Use hands out a
fresh set of indices with every observation, so the tree is re-read after every
action and there is no state here worth keeping between calls.

What crosses the line is a choice among things that were observed — an index
out of the table built from the caller's own text, never a path, a selector or
anything that could be executed. The caller looks the index up in the tree it
just read. If it is not there, nothing runs.
"""

import json
import sys

from .cua import parse
from .model import choose, field_context, field_text
from .questions import RISK_THRESHOLD


def decide(request):
    """Answer one request. Raises nothing the caller cannot print."""
    goal = (request.get("goal") or "").strip()
    if not goal:
        return {"error": "no goal"}
    page = parse(request.get("ax") or "", limit=request.get("limit", 250))
    if not page["elements"]:
        return {"error": "no elements in the accessibility text"}

    history = request.get("history") or []
    # The caller refuses by index, because the index is the only address it
    # has. The table is keyed by path, so translate against the tree that was
    # just parsed rather than asking the caller to know about paths.
    by_index = {e["index"]: e["path"] for e in page["elements"]}
    refused = [
        (operation, by_index[str(index)])
        for operation, index in (request.get("refused") or [])
        if str(index) in by_index
    ]
    # `pointer` is on because the executor on the other side clicks any index it
    # is given. The permission this flag stands for in the bridge — the app has
    # to be in front — is not this executor's constraint to ask for.
    decision = choose(page, goal, history, pointer=True, refused=refused)

    operation = decision["operation"]
    answer = {
        "operation": operation,
        "index": None,
        "label": None,
        "text": decision.get("text"),
        "risk": decision["risk"],
        "risk_reason": decision["risk_reason"],
        "confidence": decision["confidence"],
        "latency_ms": decision["latency_ms"],
        "held": decision["risk"] >= request.get("risk_threshold", RISK_THRESHOLD)
        and operation not in {"DONE", "BLOCKED"},
    }
    action = decision.get("action") or {}
    if action.get("path"):
        # The index is the address on this executor, and the table was built
        # from the caller's own text, so this is the number it printed.
        answer["index"] = next(
            (e["index"] for e in page["elements"] if e["path"] == action["path"]), None
        )
        answer["label"] = action.get("label")

    if operation == "TYPE_TEXT" and not answer["text"]:
        # A choice-only decision backend cannot write. Same fallback the agent
        # uses, and the same failure: a value that cannot be produced is a step
        # that did not happen, reported rather than raised.
        try:
            answer["text"], helper = field_text(
                field_context(goal, action, page, history)
            )
            answer["text_helper"] = helper["model"]
        except (ValueError, RuntimeError) as error:
            return {"operation": operation, "error": str(error), "index": answer["index"]}
    return answer


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            answer = decide(json.loads(line))
        except Exception as error:  # one bad request must not end the session
            answer = {"error": f"{type(error).__name__}: {error}"}
        sys.stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
