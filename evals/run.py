"""Real model tasks, independent result readings, and lifetime-wide focus events."""
import argparse
from dataclasses import replace
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from open_computer_use import Agent, model
from open_computer_use.desktop import BridgeError, Desktop
from .tasks import TASKS


class Budget:
    def __init__(self, client, path, limit):
        self.client, self.path, self.limit = client, path, limit
        self.data = json.loads(path.read_text()) if path.exists() else {"approved_calls": limit, "calls": 0, "usage": []}
        if self.data["approved_calls"] != limit:
            raise ValueError("The limit must match the existing batch's approved_calls")

    def post(self, *args, **kwargs):
        if self.data["calls"] >= self.limit:
            raise RuntimeError("Approved model-call batch exhausted")
        # Count before sending, including retries and calls whose reply is lost.
        self.data["calls"] += 1
        self.path.write_text(json.dumps(self.data, indent=2))
        response = self.client.post(*args, **kwargs)
        if response.is_success:
            self.data["usage"].append(response.json().get("usage", {}))
            self.path.write_text(json.dumps(self.data, indent=2))
        return response


class Lease:
    def __init__(self, binary, config, directory):
        self.events, self.messages = [], queue.Queue()
        self.log = (directory / "events.jsonl").open("w")
        self.errors = (directory / "native.log").open("w")
        config_path = directory / "launch.json"
        config_path.write_text(json.dumps(config))
        self.process = subprocess.Popen([str(binary), str(config_path)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.errors, text=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.log.write(line); self.log.flush()
                event = json.loads(line)
                self.events.append(event)
                self.messages.put(event)
        except Exception as error:
            event = {"event": "error", "detail": str(error)}
            self.events.append(event); self.messages.put(event)
        finally:
            self.messages.put({"event": "eof"})

    def acquire(self):
        deadline = time.monotonic() + 15
        while True:
            event = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            if event["event"] == "leased":
                self.acquired = event
                return event["pid"]
            if event["event"] in {"unavailable", "error", "eof"}:
                raise RuntimeError(event.get("detail", "Ownership monitor ended before acquiring an instance"))

    def focus_clear(self):
        if (not self.events or self.events[0]["event"] != "ready" or self.process.poll() is not None
                or any(e["event"] == "error" for e in self.events)):
            return None
        return not any(e["event"] == "activated" for e in self.events)

    def close(self):
        self.process.stdin.close()
        # The native owner closes only what it created, before its stopped event.
        code = self.process.wait(timeout=15)
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.log.close(); self.errors.close()
        if code != 0 or self.reader.is_alive():
            raise RuntimeError("The native owner did not finish cleanly")


def accepted(record):
    return (record.get("before") is False and record.get("after") is True
            and record.get("status") == "done" and record.get("monitor_complete") is True
            and record.get("cleaned") is True and record.get("focus") == [] and not record.get("error"))


def run_once(task, binary, directory, max_decisions):
    directory.mkdir()
    scratch = directory / "Documents"; scratch.mkdir()
    record = {"task": task.id, "app": task.app, "goal": task.goal, "passed": False,
              "status": "not_run", "before": None, "after": None, "error": None, "phases": [],
              "focus": [], "cleaned": False, "monitor_complete": False}
    lease = None
    def phase(name):
        record["phases"].append({"phase": name, "time": time.time()})
    try:
        phase("setup")
        lease = Lease(binary, task.launch(scratch), directory)
        pid = lease.acquire(); record["pid"] = pid
        deadline = time.monotonic() + 5
        while True:
            desktop = None
            try:
                desktop = Desktop(str(pid), menus=False)
                if desktop.observe()["elements"]:
                    break
            except BridgeError:
                if time.monotonic() >= deadline:
                    raise
            finally:
                if desktop:
                    desktop.close()
            if time.monotonic() >= deadline:
                raise RuntimeError("The owned app exposed no controls")
            time.sleep(.1)
        if any(e["event"] == "activated" for e in lease.events):
            raise RuntimeError("Activation occurred during setup; task not attempted")
        task.prepare(pid)
        phase("check_before")
        record["before"], record["initial_reading"] = task.read(pid)
        if task.app == "Finder":
            record["initial_reading"] = lease.acquired["target"]
            record["before"] = Path(record["initial_reading"]) == scratch / task.expected
        if task.app == "TextEdit" and record["initial_reading"] != task.initial.strip():
            raise RuntimeError("The owned document does not contain the requested initial text")
        if task.app == "Calculator" and record["initial_reading"] != "0":
            raise RuntimeError("The owned calculator was not cleared")
        if record["before"] is not False:
            raise RuntimeError("The initial result check was not false after setup")
        phase("agent")
        with Agent(str(pid), task.goal, menus=False, risk_threshold=0, focus_check=lease.focus_clear,
                   approve=lambda d: task.app != "System Settings" or d["operation"] in {
                       "CLICK", "SCROLL_UP", "SCROLL_DOWN", "WAIT", "PRESS_ESCAPE"}) as agent:
            try:
                for turn, state in enumerate(agent.run(), 1):
                    if any(e["event"] == "activated" for e in lease.events):
                        record["status"] = "focus_interrupted"; break
                    if turn >= max_decisions and state["status"] not in {"done", "blocked"}:
                        record["status"] = "decision_limit"; break
                else:
                    record["status"] = agent.state["status"]
            finally:
                # These public fields have already passed through Agent redaction.
                record["trace"] = agent.snapshot()["history"]
                record["note"] = agent.state.get("note")
        phase("check_after")
        record["after"], record["final_reading"] = task.read(pid)
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        phase("cleanup")
        if lease:
            try:
                lease.close()
            except Exception as error:
                record["error"] = f"{record['error'] or ''} Cleanup failed: {error}".strip()
            events = lease.events
            if task.app == "Finder":
                targets = [e["target"] for e in events if e["event"] == "finder_result"]
                record["final_reading"] = targets[-1] if targets else None
                record["after"] = Path(targets[-1]) == scratch / task.expected if targets else None
            record["monitor_complete"] = (bool(events) and events[0]["event"] == "ready"
                                          and events[-1]["event"] == "stopped")
            record["cleaned"] = bool(events and events[-1].get("cleaned") is True)
            record["focus"] = [e for e in events if e["event"] == "activated"]
            for event in record["focus"]:
                event["phase"] = next(p["phase"] for p in reversed(record["phases"]) if p["time"] <= event["time"])
            if any(e["event"] == "error" for e in events):
                record["error"] = record["error"] or "Native ownership monitor reported an error"
        record["passed"] = accepted(record)
        record["false_done"] = record["status"] == "done" and record["after"] is False
        (directory / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", choices=[t.id for t in TASKS], required=True)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--goal", help="Override the goal for a single selected task")
    parser.add_argument("--expect", help="Override its independent expected result")
    parser.add_argument("--max-decisions", type=int, default=16)
    parser.add_argument("--max-calls", type=int, required=True, help="Approved total batch cap, including prior stages")
    parser.add_argument("--usage-file", type=Path, required=True, help="Shared cumulative batch counter; run one writer at a time")
    parser.add_argument("--output", type=Path, required=True, help="New artifact directory outside the checkout")
    options = parser.parse_args()
    if (options.goal is not None or options.expect is not None) and len(options.tasks) != 1:
        parser.error("Goal/result overrides require exactly one task")
    if min(options.reps, options.max_calls, options.max_decisions) < 1:
        parser.error("Budgets and repetitions must be positive")
    root = Path(__file__).resolve().parents[1]
    output = options.output.resolve()
    if output.is_relative_to(root):
        parser.error("Keep acceptance artifacts outside the checkout")
    options.usage_file.parent.mkdir(parents=True, exist_ok=True)
    budget = Budget(model.CLIENT, options.usage_file, options.max_calls)
    output.mkdir(parents=True, exist_ok=False)
    binary = output / "native"
    subprocess.run(["swiftc", "-O", str(Path(__file__).with_name("native.swift")), "-o", str(binary)], check=True)
    original = model.CLIENT; model.CLIENT = budget
    try:
        with (output / "results.jsonl").open("w") as stream:
            for rep in range(options.reps):
                for task in TASKS:
                    if task.id not in options.tasks:
                        continue
                    if budget.data["calls"] >= options.max_calls:
                        return
                    task = replace(task, goal=options.goal if options.goal is not None else task.goal,
                                   expected=options.expect if options.expect is not None else task.expected)
                    record = run_once(task, binary, output / f"{rep + 1:02d}-{task.id}", options.max_decisions)
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n"); stream.flush()
                    print(json.dumps({k: record[k] for k in ("task", "passed", "status", "before", "after", "monitor_complete", "cleaned", "focus", "error")}), flush=True)
    finally:
        model.CLIENT = original
        print(json.dumps({"batch_calls": budget.data["calls"], "batch_cap": options.max_calls}), flush=True)


if __name__ == "__main__":
    main()
