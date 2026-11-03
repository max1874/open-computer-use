"""Run the task set and record what each run actually left in the app.

    uv run --env-file .env python -m evals.run --sensitivity          # no model
    uv run --env-file .env python -m evals.run --backend jev --reps 5
    uv run --env-file .env python -m evals.run --backend chat --reps 5

`--backend chat` drops JEV_API_KEY for this process, which is how the loop
picks the OpenAI-compatible model; nothing else differs between the arms.

No `verify` is handed to the agent: the run ends on the model's own DONE or
BLOCKED, and the check is read afterwards. That keeps a false DONE visible as
its own number instead of being turned into a block by the loop.

Each run is one line of `evals/results/<stamp>-<backend>.jsonl`; the summary
at the end is computed from those lines alone.
"""

import argparse
import json
import os
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def frontmost():
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    info = subprocess.run(["lsappinfo", "info", "-only", "name", "-only", "bundleid", asn],
                          capture_output=True, text=True).stdout
    fields = dict(line.split("=", 1) for line in info.split() if "=" in line)
    return fields.get('"LSDisplayName"', "").strip('"'), fields.get('"CFBundleIdentifier"', "").strip('"')


class FocusWatch(threading.Thread):
    """Watch the frontmost app from outside the agent.

    The agent's own `took_focus` only knows about activations it asked for. An
    app that raises itself, or a setup step that does, is invisible to it, and
    both put a window in front of whoever is using the machine. When one of the
    task apps comes to the front this records which phase was running and hands
    the front straight back to the app that had it.
    """

    def __init__(self, apps):
        super().__init__(daemon=True)
        self.apps, self.phase, self.events = set(apps), "start", []
        self.owner = frontmost()
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.wait(0.1):
            name, bundle = frontmost()
            if name in self.apps:
                self.events.append({"phase": self.phase, "app": name})
                if self.owner[1]:
                    subprocess.run(["osascript", "-e", f'tell application id "{self.owner[1]}" to activate'],
                                   capture_output=True)
            elif name:
                self.owner = (name, bundle)

    def take(self):
        events, self.events = self.events, []
        return events

    def stop(self):
        self.stopped.set()


def sensitivity(tasks):
    """setup → check → solve → check, no model: a check must flip from False to True."""
    from evals.tasks import running_apps, tidy

    trusted, was_running = True, running_apps()
    watch = FocusWatch({t.app for t in tasks} - {"Finder"})
    watch.start()
    for position, task in enumerate(tasks):
        watch.phase = "setup"
        task.setup()
        watch.phase = "check"
        before = task.check()
        watch.phase = "solve"
        task.solve()
        watch.phase = "check"
        after = task.check()
        watch.phase = "tidy"
        if position + 1 == len(tasks) or tasks[position + 1].app != task.app:
            tidy(task.app, was_running)
        time.sleep(0.3)
        ok = before is False and after is True
        trusted &= ok
        stolen = watch.take()
        print(f"{'ok  ' if ok else 'FAIL'}  {task.id:<24} before={before}  after={after}"
              + (f"  FOCUS {stolen}" if stolen else ""))
    watch.stop()
    return trusted


def instrument():
    """Total the token usage each backend reports; the loop itself does not keep it."""
    from open_computer_use import model

    spent = []
    for name in ("ask_jev", "ask_chat"):
        original = getattr(model, name)

        def wrapped(*args, _original=original, **kwargs):
            reply = _original(*args, **kwargs)
            spent.append(reply.get("usage") or {})
            return reply

        setattr(model, name, wrapped)
    return spent


def run_once(task, spent, watch):
    from open_computer_use import Agent

    watch.phase = "setup"
    task.setup()
    watch.phase = "check"
    if task.check():
        return {"outcome": "dirty", "detail": "check was already true after setup", "focus": watch.take()}
    asked = []

    def approve(decision):
        asked.append(decision.get("risk_reason"))
        return True

    spent.clear()
    started = time.perf_counter()
    error = None
    watch.phase = "agent"
    try:
        with Agent(task.app, task.goal, approve=approve) as agent:
            for _ in agent.run():
                pass
            final = agent.state
    except Exception as exc:  # a run that raises is a failed run, and says why
        final, error = None, f"{type(exc).__name__}: {exc}"
    wall_ms = round((time.perf_counter() - started) * 1000)
    watch.phase = "check"
    passed = task.check()
    record = {"passed": passed, "wall_ms": wall_ms, "error": error, "approvals_asked": len(asked)}
    if final:
        latencies = [d["latency_ms"] for d in final["decisions"] if "latency_ms" in d]
        record.update(
            status=final["status"],
            said_done=final["status"] == "done",
            note=final.get("note"),
            steps=len(final["history"]),
            decisions=len(final["decisions"]),
            decision_ms=latencies,
            took_focus=final.get("took_focus"),
            operations=[step["operation"] for step in final["history"]],
            # What each step aimed at and how it ended, so a failure can be read
            # back from this file instead of rerun.
            trace=[{k: step.get(k) for k in ("operation", "label", "text", "outcome", "detail", "window_changed")}
                   for step in final["history"]],
        )
    record["prompt_tokens"] = sum(u.get("prompt_tokens", 0) for u in spent)
    record["completion_tokens"] = sum(u.get("completion_tokens", 0) for u in spent)
    record["focus"] = watch.take()
    return record


def summarize(lines):
    by_task = {}
    for line in lines:
        by_task.setdefault(line["task"], []).append(line)
    print(f"\n{'task':<24} pass   false DONE")
    for task, runs in by_task.items():
        passed = sum(bool(r.get("passed")) for r in runs)
        false_done = sum(bool(r.get("said_done")) and not r.get("passed") for r in runs)
        print(f"{task:<24} {passed}/{len(runs)}   {false_done}")
    counted = [l for l in lines if l.get("outcome") != "dirty"]
    passed = [l for l in counted if l.get("passed")]
    decisions = [ms for l in counted for ms in l.get("decision_ms", [])]
    print(f"\npassed {len(passed)}/{len(counted)} runs")
    if passed:
        print(f"wall clock, passed runs, median: {statistics.median(l['wall_ms'] for l in passed) / 1000:.1f} s")
        print(f"steps, passed runs, median: {statistics.median(l['steps'] for l in passed)}")
    if decisions:
        print(f"decision latency median: {statistics.median(decisions)} ms over {len(decisions)} decisions")
    print(f"agent asked for the screen: {sum(bool(l.get('took_focus')) for l in counted)} runs")
    agent_front = sum(any(e["phase"] == "agent" for e in l.get("focus", [])) for l in counted)
    harness_front = sum(any(e["phase"] != "agent" for e in l.get("focus", [])) for l in counted)
    print(f"task app came to the front while the agent ran: {agent_front} runs; "
          f"during setup or checks: {harness_front} runs")
    print(f"tokens: {sum(l.get('prompt_tokens', 0) for l in counted)} in, "
          f"{sum(l.get('completion_tokens', 0) for l in counted)} out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["jev", "chat"])
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--tasks", nargs="*", help="task ids; default all")
    parser.add_argument("--sensitivity", action="store_true", help="check the checks, no model")
    options = parser.parse_args()

    if options.backend == "chat":
        os.environ.pop("JEV_API_KEY", None)

    from evals.tasks import TASKS, running_apps, tidy

    tasks = [t for t in TASKS if not options.tasks or t.id in options.tasks]
    if options.sensitivity:
        raise SystemExit(0 if sensitivity(tasks) else 1)
    if not options.backend:
        parser.error("--backend is required unless --sensitivity")

    spent = instrument()
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}-{options.backend}.jsonl"
    lines = []
    was_running = running_apps()
    watch = FocusWatch({t.app for t in tasks} - {"Finder"})
    watch.start()
    with path.open("w") as out:
        # Interleave tasks within each repetition, so a slow minute on the
        # provider's side spreads across tasks instead of sinking one.
        for rep in range(options.reps):
            for position, task in enumerate(tasks):
                record = {"task": task.id, "backend": options.backend, "rep": rep, **run_once(task, spent, watch)}
                lines.append(record)
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                print(f"{task.id:<24} rep {rep}  passed={record.get('passed')}  "
                      f"{record.get('status', record.get('outcome'))}  {record['wall_ms'] if 'wall_ms' in record else ''} ms")
                # Tasks are grouped by app, so close each app once its group is
                # done instead of leaving six of them open until the end.
                following = tasks[position + 1] if position + 1 < len(tasks) else None
                if not following or following.app != task.app:
                    watch.phase = "tidy"
                    tidy(task.app, was_running)
                    time.sleep(0.3)
                    if stolen := watch.take():
                        print(f"  focus taken while tidying {task.app}: {stolen}")
    print(f"\nwrote {path}")
    summarize(lines)


if __name__ == "__main__":
    main()
