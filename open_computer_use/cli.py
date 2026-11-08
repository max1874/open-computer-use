"""The command line: let a coding agent be the decision model.

    open-computer-use observe TextEdit
    open-computer-use act TextEdit 3f9a1c2e7b10 TYPE_TEXT e4 --text 'Hello'

`observe` prints the same element table the built-in decision model is shown.
`act` executes one operation on it through the same native bridge, then prints
the next observation. Every invocation starts its own bridge, and the bridge's
observation tokens live only as long as that process, so `act` observes afresh
and refuses unless the window's fingerprint is still the one the caller chose
from: the decision and the execution stay on one observed state.
"""

import argparse
import json
import sys
import time
from contextlib import closing

from .actions import EDITING_KEYS, action_space
from .desktop import Bridge, BridgeError, Desktop, Executed, StaleWindow, UnknownOutcome

TEXT_OPERATIONS = {"TYPE_TEXT", "PASTE_TEXT"}


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))


def show(page, text=False):
    """One header line, then one line per element and menu command."""
    elements, targets, controls = action_space(page)
    header = {k: page[k] for k in ("app", "window", "active")}
    header["fingerprint"] = page["fingerprint"][:12]
    if page.get("complete") is False:
        header.update(complete=False, truncations=page.get("truncations", []))
    if page.get("truncated"):
        header["truncated"] = "more elements than listed; scrolling brings others into view"
    header["controls"] = sorted(controls)
    emit(header)
    for element in elements:
        if element.get("options"):
            refs = [r for r in targets.get("SELECT", {}) if r.startswith(element["index"] + ":")]
            element["options"] = dict(zip(refs, element["options"]))
        emit(element)
    for item in page.get("menus", []):
        emit({"index": item["index"], "menu": item["label"]})
    if text and page.get("text"):
        print(page["text"])


def resolve(page, options):
    """The action the caller named, built only from what this observation offers."""
    _, targets, controls = action_space(page)
    operation = options.operation
    if operation in controls:
        return dict(controls[operation])
    if operation not in targets:
        raise ValueError(f"{operation} is not offered on this window")
    action = targets[operation].get(options.target)
    if action is None:
        raise ValueError(f"{operation} target {options.target!r} is not offered; offered: {sorted(targets[operation])}")
    action = dict(action)
    if operation == "KEY_CHORD":
        if options.key not in EDITING_KEYS:
            raise ValueError(f"KEY_CHORD needs --key, one of {EDITING_KEYS}")
        action["key"] = options.key
    if operation == "SELECT_TEXT":
        if options.start is None or options.length is None:
            raise ValueError("SELECT_TEXT needs --start and --length (UTF-16 offsets)")
        action.update(start=options.start, length=options.length)
    if operation in TEXT_OPERATIONS and options.text is None:
        raise ValueError(f"{operation} needs --text")
    return action


def act(options):
    with closing(Desktop(options.app, machine_wide=options.machine_wide)) as desktop:
        page = desktop.observe()
        if len(options.fingerprint) < 8 or not page["fingerprint"].startswith(options.fingerprint):
            emit({"outcome": "stale", "delivery": "not_delivered",
                  "detail": "The window changed since that observation; nothing was sent. Choose again from this one."})
            show(page)
            return 1
        try:
            action = resolve(page, options)
        except ValueError as error:
            emit({"outcome": "refused", "delivery": "not_delivered", "detail": str(error)})
            return 1
        code = 0
        try:
            if options.operation == "WAIT":
                time.sleep(0.15)
                outcome = {"outcome": "waited", "delivery": "not_delivered"}
            else:
                text = options.text if options.operation in TEXT_OPERATIONS else None
                result = desktop.act(action, page, text=text)
                outcome = {"outcome": "delivered", "delivery": result["disposition"]["delivery"],
                           **{k: result[k] for k in ("verified", "took_focus", "detail", "mechanism") if k in result}}
        except StaleWindow as error:
            outcome, code = {"outcome": "stale", "delivery": "not_delivered", "detail": str(error)}, 1
        except UnknownOutcome as error:
            # Executed is the certain-delivery subclass. Either way: never retry blind.
            outcome = {"outcome": "executed, unconfirmed" if isinstance(error, Executed) else "unknown",
                       "delivery": error.disposition["delivery"],
                       "took_focus": getattr(error, "took_focus", False),
                       "detail": f"{error} Read the window before sending anything else."}
            code = 2
        except BridgeError as error:
            outcome, code = {"outcome": "refused", "delivery": error.disposition["delivery"],
                             "took_focus": getattr(error, "took_focus", False), "detail": str(error)}, 1
        if outcome.get("took_focus"):
            outcome["outcome"], code = "focus_violation", 3
        emit({"operation": options.operation, "label": action.get("label", options.operation), **outcome})
        try:
            show(desktop.observe())
        except BridgeError as error:
            emit({"unobserved": str(error)})
        return code


def main(argv=None):
    parser = argparse.ArgumentParser(prog="open-computer-use", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="permissions, screen lock and the frontmost app")
    commands.add_parser("apps", help="running apps")
    observe = commands.add_parser("observe", help="print one app's element table")
    observe.add_argument("app", help="app name, bundle id, or pid")
    observe.add_argument("--text", action="store_true", help="also print the window's visible text")
    run = commands.add_parser("act", help="execute one operation, then observe again")
    run.add_argument("app")
    run.add_argument("fingerprint", help="from the observation the operation was chosen on")
    run.add_argument("operation")
    run.add_argument("target", nargs="?", help="element or menu index, e.g. e4, e5:2, m3")
    run.add_argument("--text", help="TYPE_TEXT / PASTE_TEXT value")
    run.add_argument("--key", help="KEY_CHORD key")
    run.add_argument("--start", type=int, help="SELECT_TEXT UTF-16 offset")
    run.add_argument("--length", type=int, help="SELECT_TEXT UTF-16 length")
    run.add_argument("--machine-wide", action="store_true",
                     help="allow a change to the whole Mac (System Settings); only after the user said yes")
    commands.add_parser("inspect", help="the local inspector for the built-in agent", add_help=False)
    options, rest = parser.parse_known_args(argv)
    if rest and options.command != "inspect":
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
    try:
        if options.command == "inspect":
            from .demo import main as inspect
            return inspect(rest)
        if options.command in {"status", "apps"}:
            with closing(Bridge()) as bridge:
                emit(bridge.call(options.command))
            return 0
        if options.command == "observe":
            with closing(Desktop(options.app)) as desktop:
                show(desktop.observe(), text=options.text)
            return 0
        return act(options)
    except (BridgeError, RuntimeError) as error:
        print(f"open-computer-use: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
