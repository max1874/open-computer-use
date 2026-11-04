"""The complete loop: observe the window, choose one operation, execute it, observe again."""

import time

from .desktop import (
    BridgeError,
    Desktop,
    Executed,
    StaleWindow,
    UnknownOutcome,
    disposition,
)
from .model import action_space, choose, field_context, field_text
from .questions import MAX_DECISIONS, MAX_STALE_RETRIES, MAX_STEPS, RISK_THRESHOLD


def window_changes(before, after, limit=3):
    """Name what moved between two observations, for a run that keeps going stale.

    The freshness guard answers yes or no, which is all it needs to refuse an
    operation and nothing like enough to explain a run that was refused eighty
    times. A window with a clock in it is never fresh, and "the window changed"
    does not say that a clock is what changed.
    """
    def by_path(page):
        return {e["path"]: e for e in page.get("elements", [])}

    old, new = by_path(before), by_path(after)
    moved = []
    for path, element in new.items():
        was = old.get(path)
        if was is None:
            moved.append(f"{element['role'].removeprefix('AX')} \"{element.get('label') or '?'}\" appeared")
        elif was.get("value") != element.get("value"):
            moved.append(
                f"{element.get('label') or element['role'].removeprefix('AX')}: "
                f"{was.get('value')!r} → {element.get('value')!r}"
            )
        elif was.get("label") != element.get("label"):
            moved.append(f"{was.get('label')!r} → {element.get('label')!r}")
        if len(moved) >= limit:
            break
    gone = len(set(old) - set(new))
    if gone and len(moved) < limit:
        moved.append(f"{gone} elements went away")
    return "; ".join(moved)


def public_decision(decision):
    """Keep secure-field input out of the inspector and decision history."""
    if decision and (decision.get("action") or {}).get("secure"):
        text = decision.get("text")
        reason = decision["risk_reason"]
        return {**decision, "text": None, "risk_reason": reason.replace(text, "[redacted]") if text else reason}
    return decision


class Agent:
    """Drive one macOS app towards one natural-language goal.

    `approve` is called with the pending decision whenever the model rates an
    operation at or above `risk_threshold`. Without it the run stops at
    `needs_approval` and hands the decision back, rather than acting.

    The native bridge works without activating the app or moving the pointer.
    """

    def __init__(
        self,
        app,
        goal,
        *,
        approve=None,
        risk_threshold=RISK_THRESHOLD,
        menus=True,
        verify=None,
    ):
        goal = goal.strip() if isinstance(goal, str) else "\n".join(goal).strip()
        if not goal:
            raise ValueError("Supply a goal")
        self.approve = approve
        self.risk_threshold = risk_threshold
        # Called with the final observation when the model says DONE. Return
        # True to confirm, False to reject it, None if it cannot be judged.
        # Without one, DONE is only ever the model's own claim.
        self.verify = verify
        self.pending_text = None
        # (operation, path) pairs this app has refused on the window as it
        # now stands. Cleared the moment the window changes, because a
        # refusal is a fact about a state, not about a control.
        self.refused = set()
        # Consecutive decisions refused because the window moved under them.
        self.stale = 0
        self.desktop = Desktop(app, menus=menus)
        try:
            page = self.desktop.observe()
        except Exception:
            self.desktop.close()
            raise
        self.state = dict(
            app=app,
            goal=goal,
            page=page,
            decision=None,
            history=[],
            decisions=[],
            status="ready",
            verified=None,
            took_focus=False,
            elapsed_ms=0,
            started_at=None,
        )

    def snapshot(self):
        elements, targets, _ = action_space(self.state["page"])
        return {
            **{k: v for k, v in self.state.items() if k != "page"},
            "decision": public_decision(self.state["decision"]),
            "window": {
                k: self.state["page"][k] for k in ("app", "window", "fingerprint", "text", "truncated")
            },
            "elements": elements,
            "menus": self.state["page"].get("menus", []),
            "targets": {k: sorted(v) for k, v in targets.items()},
        }

    def _elapsed(self):
        return round((time.perf_counter() - self.state["started_at"]) * 1000)

    def command(self, name, body=None):
        if name == "tick":
            self._tick()
        elif name == "predict":
            self._predict()
        elif name == "act":
            self._act(body or {})
        else:
            raise ValueError(f"Unknown command {name!r}")
        return self.snapshot()

    def _record(self, decision, text=None, **details):
        state = self.state
        action = decision["action"] or {}
        state["elapsed_ms"] = self._elapsed()
        state["history"].append({
            "step": len(state["history"]) + 1,
            "operation": decision["operation"],
            "target": decision["target"],
            "label": action.get("label", decision["operation"]),
            "text": None if action.get("secure") else text,
            "risk": decision["risk"],
            **details,
            "elapsed_ms": state["elapsed_ms"],
        })

    def _stalled(self, ignored=()):
        recent = self.state["history"][-3:]
        return len(recent) == 3 and all(
            h.get("window_changed") is False and h["operation"] not in ignored for h in recent
        )

    def _observe(self):
        before = self.state["page"]["fingerprint"]
        page = self.desktop.observe()
        self.state["page"] = page
        changed = page["fingerprint"] != before
        if changed:
            self.refused.clear()
        return changed

    def _tick(self):
        state = self.state
        try:
            self._predict()
            # Only a pending decision can execute; a terminal or held prediction ends the tick.
            if state["status"] in {"needs_approval", "blocked", "done"}:
                return
            return self._act({"fingerprint": state["page"]["fingerprint"]})
        except StaleWindow as error:
            # A stale decision sent no input. Bound re-observation so a live clock cannot consume the whole run.
            previous = state["page"]
            state["decision"] = None
            self._observe()
            self.stale += 1
            state["elapsed_ms"] = self._elapsed()
            if self.stale >= MAX_STALE_RETRIES:
                state["status"] = "blocked"
                moved = window_changes(previous, state["page"])
                state["note"] = (
                    f"{self.stale} decisions in a row were refused as stale: {error} "
                    + (f"What keeps changing: {moved}." if moved else "Nothing visible changed between them.")
                )
            else:
                state["status"] = "ready"
            return
        except RuntimeError as error:
            # Preserve completed history when the provider cannot answer.
            state["decision"] = None
            state["status"] = "blocked"
            state["note"] = str(error)
            state["elapsed_ms"] = self._elapsed()
            return

    def _predict(self):
        state = self.state
        if state["status"] in {"done", "blocked"}:
            raise ValueError("This run has stopped. Start a fresh agent.")
        if state["started_at"] is None:
            state["started_at"] = time.perf_counter()
        # Budget exhaustion is a normal terminal result.
        if len(state["decisions"]) >= MAX_DECISIONS:
            state["status"] = "blocked"
            state["note"] = f"Reached the {MAX_DECISIONS}-decision budget without finishing."
            state["elapsed_ms"] = self._elapsed()
            return
        if not self.desktop.fresh(state["page"]):
            self._observe()
        state["decision"] = None
        _, targets, _ = action_space(state["page"], refused=self.refused)
        if not targets:
            state["status"] = "blocked"
            state["note"] = "The app exposes no supported background controls. No input was sent."
            state["elapsed_ms"] = self._elapsed()
            return
        decision = choose(state["page"], state["goal"], state["history"], refused=self.refused)
        state["decisions"].append(
            {
                **{k: v for k, v in public_decision(decision).items() if k != "offered"},
                "fingerprint": state["page"]["fingerprint"],
                "elapsed_ms": self._elapsed(),
            }
        )
        state["decision"] = decision
        # The guard runs on the operation that is about to execute, in the
        # same request that chose it: safety costs no extra round trip.
        risky = decision["risk"] >= self.risk_threshold and decision["operation"] not in {"DONE", "BLOCKED"}
        if risky and not (self.approve and self.approve(decision)):
            state["status"] = "needs_approval"
        else:
            state["status"] = "predicted"
        return

    def _act(self, body):
        state = self.state
        decision, page = state["decision"], state["page"]
        if not decision or body.get("fingerprint") != page["fingerprint"]:
            raise ValueError("Observe and choose before acting")
        if state["status"] == "needs_approval" and not body.get("approved"):
            raise ValueError(f"Held for approval: {decision['risk_reason']}")
        # Consume once, before any mutation. A retry cannot press twice.
        state["decision"] = None
        operation = decision["operation"]

        if operation in {"DONE", "BLOCKED"}:
            if not self.desktop.fresh(page):
                state["status"] = "ready"
                raise StaleWindow("The window changed since the decision. Choose again.")
            state["elapsed_ms"] = self._elapsed()
            if operation == "BLOCKED":
                state["status"] = "blocked"
                return
            # DONE is the model's opinion about its own work. When the
            # caller supplied a way to check, the check decides.
            verdict = None
            if self.verify:
                try:
                    verdict = self.verify(state["page"])
                except Exception as error:
                    verdict = None
                    state["note"] = f"the outcome check itself failed: {error}"
            state["verified"] = verdict
            if verdict is False:
                state["status"] = "blocked"
                state["note"] = "The model reported DONE and the outcome check disagreed."
            else:
                state["status"] = "done"
            return

        if len(state["history"]) >= MAX_STEPS:
            state["status"] = "blocked"
            state["note"] = f"Stopped at the {MAX_STEPS}-operation budget without finishing."
            state["elapsed_ms"] = self._elapsed()
            return

        action = decision["action"]
        secure = bool(action and action.get("secure"))
        text, helper = None, None
        # Preparation failure sent no input; retain it as a refused step.
        try:
            if operation in {"TYPE_TEXT", "PASTE_TEXT"}:
                if not self.desktop.fresh(page):
                    raise StaleWindow("The window changed before the value was settled. Choose again.")
                text = decision.get("text")
                if not text:
                    # A choice-only decision backend cannot write; ask a text model.
                    context = field_context(state["goal"], action, page, state["history"])
                    if self.pending_text and self.pending_text[0] == context:
                        _, text, helper = self.pending_text
                    else:
                        text, helper = field_text(context)
                        self.pending_text = (context, text, helper)
        except ValueError as error:
            detail = "The secure field value could not be prepared; nothing was typed." if secure else str(error)
            self._record(
                decision,
                outcome="not attempted",
                disposition=disposition("not_delivered"),
                detail=detail,
                path=action.get("path") if action else None,
                window_changed=False,
            )
            if action and action.get("path"):
                self.refused.add((operation, action["path"]))
            stuck = self._stalled()
            state["status"] = "blocked" if stuck else "ready"
            if stuck:
                state["note"] = detail
            return

        if operation == "WAIT":
            time.sleep(0.15)
            result = {"detail": "waited", "mechanism": "sleep", "disposition": disposition("not_delivered")}
        else:
            try:
                result = self.desktop.act(action, page, text=text)
            except UnknownOutcome as error:
                # Input may have landed. Record before observing, then stop without replay.
                certain = isinstance(error, Executed)
                self._record(
                    decision,
                    text=text,
                    secure=secure,
                    outcome="executed, unconfirmed" if certain else "unknown",
                    disposition=error.disposition,
                    detail=str(error),
                )
                try:
                    self._observe()
                except BridgeError:
                    pass
                state["status"] = "blocked"
                state["note"] = (
                    f"{operation} was delivered but its result could not be confirmed. "
                    f"Check the window before running anything else."
                    if certain
                    else f"{operation} may or may not have run. Check the window before running anything else."
                )
                return
            except BridgeError as error:
                # A proven pre-dispatch refusal can continue with a different target.
                self._record(
                    decision,
                    text=text,
                    secure=secure,
                    outcome="failed",
                    disposition=error.disposition,
                    detail=str(error),
                    path=action.get("path") if action else None,
                    window_changed=False,
                )
                if action and action.get("path"):
                    self.refused.add((operation, action["path"]))
                try:
                    self._observe()
                except BridgeError as gone:
                    state["history"][-1]["unobserved"] = str(gone)
                    state["status"] = "blocked"
                    return
                state["elapsed_ms"] = self._elapsed()
                stuck = self._stalled()
                state["status"] = "blocked" if stuck else "ready"
                if stuck:
                    state["note"] = f"{operation} was refused: {error}"
                return
        self.pending_text = None
        # Something executed, so the run is converging again.
        self.stale = 0

        # Record execution before observing its result: a stale observation
        # must never erase an operation that actually ran.
        self._record(
            decision,
            text=text,
            secure=secure,
            disposition=result["disposition"],
            mechanism=result.get("mechanism"),
            detail=result.get("detail"),
            took_focus=result.get("took_focus", False),
            verified_by_app=result.get("verified"),
            confidence=decision["confidence"],
            risk_reason=public_decision(decision)["risk_reason"],
            latency_ms=decision["latency_ms"],
            text_helper=helper["model"] if helper else None,
            usage=decision["usage"],
            window_changed=None,
            executed_ms=self._elapsed(),
        )
        if result.get("took_focus"):
            state["took_focus"] = True
        try:
            changed = self._observe()
        except BridgeError as error:
            # Retain delivered input even when the following observation fails.
            state["elapsed_ms"] = self._elapsed()
            state["history"][-1].update(window_changed=None, unobserved=str(error))
            state["status"] = "blocked"
            return
        state["elapsed_ms"] = self._elapsed()
        state["history"][-1].update(
            window_changed=changed,
            elapsed_ms=state["elapsed_ms"],
        )
        # Three operations that changed nothing visible is a stuck policy.
        stuck = self._stalled({"WAIT", "SCROLL_UP", "SCROLL_DOWN"})
        state["status"] = "blocked" if stuck else "ready"
        return

    def run(self):
        """Yield one state per step. Stops at done, blocked, or a held operation."""
        while self.state["status"] not in {"done", "blocked", "needs_approval"}:
            yield self.command("tick")

    def approve_pending(self):
        """Release an operation that was held by the guard."""
        if self.state["status"] != "needs_approval":
            raise ValueError("Nothing is waiting for approval")
        self.state["status"] = "predicted"
        return self.command("act", {"fingerprint": self.state["page"]["fingerprint"], "approved": True})

    def close(self):
        self.desktop.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
