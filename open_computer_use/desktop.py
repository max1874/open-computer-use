"""The accessibility bridge: one snapshot in, one guarded operation out.

The Swift helper stays alive for the whole session, so a step costs one
accessibility traversal rather than a process launch.
"""

import json
import os
import selectors
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT.parent / "scripts" / "build.sh"


def disposition(delivery):
    """Retryability follows delivery, never an API's success flag."""
    return {"delivery": delivery, "retry": "safe" if delivery == "not_delivered" else "unsafe"}


class StaleWindow(Exception):
    """The window changed between the decision and its execution."""

    disposition = disposition("not_delivered")


class BridgeError(RuntimeError):
    """The bridge refused an operation. Nothing was executed."""

    disposition = disposition("not_delivered")


class UnknownOutcome(RuntimeError):
    """The request was sent and the window may already have changed.

    These must not be retried. The operation may have run: a press that reached
    the app and then lost its reply looks exactly like a press that never
    arrived. Observe the window and decide from what is there, rather than
    sending it again.
    """

    disposition = disposition("delivery_uncertain")


class Executed(UnknownOutcome):
    """Input was delivered, but the resulting state could not be confirmed.

    This includes a field cleared before a later write failed. It is never a
    refusal, and callers must not repeat the operation.
    """

    disposition = disposition("delivered_unverified")


def binary():
    """Build the bridge if needed and return its path."""
    override = os.environ.get("AXBRIDGE_BIN")
    if override:
        return override
    result = subprocess.run([str(BUILD)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"could not build the accessibility bridge:\n{result.stderr.strip()}")
    return result.stdout.strip()


class Bridge:
    """A line-delimited JSON-RPC pipe to the Swift helper."""

    def __init__(self):
        self.executable = binary()
        self.lock = threading.Lock()
        self.counter = 0
        self.closed = False
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer = bytearray()

    def _start(self):
        self.process = subprocess.Popen(
            [self.executable, "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def _stop(self):
        if self.process is None:
            return
        self.selector.unregister(self.process.stdout)
        # A timed-out helper must not finish an old request on a new pipe.
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
        self.process = None
        self.buffer.clear()

    def _readline(self, timeout):
        """Read a whole frame within the deadline, including partial replies."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError(f"no complete reply within {timeout}s")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise EOFError("the bridge closed the pipe")
            self.buffer.extend(chunk)
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        return line

    def call(self, method, timeout=20, mutating=False, **body):
        with self.lock:
            if self.closed:
                raise BridgeError("the accessibility bridge is closed")
            if self.process is not None and self.process.poll() is not None:
                self._stop()
            if self.process is None:
                try:
                    self._start()
                except OSError as error:
                    raise BridgeError(f"could not start the accessibility bridge: {error}") from None
            self.counter += 1
            request = {"id": self.counter, "method": method, **body}
            payload = (json.dumps(request) + "\n").encode()
            # Once a write starts, a transport failure cannot prove non-delivery.
            try:
                if self.process.stdin.write(payload) != len(payload):
                    raise OSError("incomplete request write")
                self.process.stdin.flush()
                answer = json.loads(self._readline(timeout))
                if not isinstance(answer, dict) or answer.get("id") != request["id"]:
                    raise ValueError("the reply does not match the request")
                if not isinstance(answer.get("ok"), bool):
                    raise ValueError("the reply has no outcome")
                if answer["ok"] and not isinstance(answer.get("result"), dict):
                    raise ValueError("the reply has no result")
                envelope = answer if not answer["ok"] else answer["result"]
                reported = envelope.get("disposition")
                if "disposition" in envelope and (
                    not isinstance(reported, dict) or reported.get("delivery") not in {
                        "not_delivered", "delivery_uncertain", "delivered_unverified", "delivered_verified"
                    }
                ):
                    raise ValueError("the reply has an invalid delivery outcome")
            except (OSError, EOFError, TimeoutError, ValueError) as error:
                self._stop()
                failure = UnknownOutcome if mutating else BridgeError
                raise failure(
                    f"{method}: {error}. The bridge was reset. "
                    + ("It may have run; observe before doing anything else." if mutating else "Observe again.")
                ) from None
            if not answer["ok"]:
                message = answer.get("error", "unknown bridge error")
                delivery = answer.get("disposition", {}).get("delivery")
                if delivery == "delivery_uncertain":
                    raise UnknownOutcome(message)
                if delivery == "delivered_unverified" or answer.get("acted"):
                    raise Executed(message)
                raise BridgeError(message)
            result = answer["result"]
            if mutating:
                # Older AXBRIDGE_BIN overrides have no structured delivery field.
                result.setdefault("disposition", disposition(
                    "delivered_verified" if result.get("verified") is True else "delivered_unverified"
                ))
            return result

    def close(self):
        with self.lock:
            if not self.closed:
                self._stop()
                self.selector.close()
                self.closed = True


# How long to let the interface settle before the next observation. A menu or a
# sheet animates in; paying for a decision before it exists wastes a round trip.
# TYPE_TEXT needs almost nothing, because setting the accessibility value is
# synchronous and `act` has already read the value back before returning.
SETTLE_MS = {
    "MENU": 220,
    "SELECT": 220,
    "PRESS": 60,
    # Stepping a control is the app changing its own value, done immediately.
    "INCREMENT": 60,
    "DECREMENT": 60,
    "TYPE_TEXT": 25,
    "PASTE_TEXT": 40,
    "KEY_CHORD": 80,
    "SELECT_TEXT": 25,
    "WAIT": 150,
}


class Desktop:
    """One app, observed as an indexed element table and driven by path."""

    def __init__(self, app, *, menus=True, limit=250):
        self.bridge = Bridge()
        status = self.bridge.call("status")
        if not status["accessibility"]:
            self.close()
            raise RuntimeError(
                "Accessibility permission is missing. System Settings > Privacy & Security > "
                "Accessibility: enable the app running this shell, then restart it."
            )
        if status["locked"]:
            self.close()
            raise RuntimeError("The screen is locked; the accessibility tree is empty until it is unlocked.")
        self.app = app
        self.instance = None
        self.menus = menus
        self.limit = limit

    def observe(self):
        page = self.bridge.call("snapshot", app=self.app, menus=self.menus, limit=self.limit,
                                process_instance=self.instance)
        self.instance = page.get("process_instance")
        page["observed_at"] = time.time()
        return page

    def permissions(self):
        """Recheck permissions in a new process, including mid-session grants."""
        return self.bridge.call("status")

    def fresh(self, page):
        """Has the window's semantic state survived since this observation?"""
        try:
            now = self.bridge.call("fingerprint", app=self.app, limit=self.limit, process_instance=self.instance)
        except BridgeError:
            return False
        return now["fingerprint"] == page["fingerprint"]

    def act(self, action, page, text=None):
        """Execute one chosen action. A refused guard raises; nothing runs twice."""
        operation = action["operation"]
        request = {"app": self.app, "op": action.get("op", operation),
                   "process_instance": page.get("process_instance"), "observation": page.get("observation")}
        if "path" in action:
            request["path"] = action["path"]
            # The element at that path must still be the one that was chosen.
            for guard in ("expect", "expect_role", "expect_id"):
                if action.get(guard):
                    request[guard] = action[guard]
        if "secure" in action:
            request["expect_secure"] = action["secure"]
        if "menu" in action:
            request["menu"] = action["menu"]
        if "option" in action:
            request["option"] = action["option"]
            source = next((e for e in page["elements"] if e["path"] == action.get("path")), {})
            option = next((o for o in source.get("options", []) if o["child"] == action["option"]), None)
            if option is None:
                raise BridgeError("The selected option was not present in the observation")
            request["option_label"] = option["label"]
        if "key" in action:
            request["key"] = action["key"]
        for field in ("start", "length"):
            if field in action:
                request[field] = action[field]
        if text is not None:
            request["text"] = text
        try:
            result = self.bridge.call("act", mutating=True, timeout=30, **request)
        except BridgeError as error:
            if str(error).startswith("stale:") or "is stale" in str(error):
                raise StaleWindow(str(error)) from None
            raise
        settle = SETTLE_MS.get(operation, 60)
        time.sleep(settle / 1000)
        return result

    def close(self):
        self.bridge.close()
