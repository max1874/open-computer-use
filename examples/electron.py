#!/usr/bin/env python3
"""The same window, read twice, with one number changed.

The most useful thing this project learned is also the easiest to get wrong,
because the wrong answer comes with real measurements attached. Read a Chromium
window — Lark, Feishu, Slack, VS Code, anything Electron — with the traversal
limit that suits native apps, and it reports a handful of elements, almost no
text and nowhere to type. The obvious conclusion is that Electron keeps its
interface out of the accessibility tree and only a screenshot will do.

It is not true. The tree is there. Chromium puts the web area about nine levels
below the window and the interface another ten to twenty below that, so a walk
that stops at eighteen ends in the empty scaffolding above the content and
reports, accurately, that it found nothing.

This reads one window at several depths and prints what each one sees. Nothing
is pressed, nothing is typed, nothing is brought to the front, and no model is
called — it only looks.

    uv run python examples/electron.py                 # Lark
    uv run python examples/electron.py --app Slack
    uv run python examples/electron.py --app Finder    # a native window, flat

A native window is the control: it puts everything within a dozen levels, so
its numbers do not move and the deeper walk costs it nothing.
"""

import argparse
import time

from open_computer_use.desktop import Bridge

DEPTHS = [18, 26, 40, 60]


def look(bridge, app, depth, limit):
    """One snapshot, and what it would let an agent do."""
    started = time.perf_counter()
    page = bridge.call("snapshot", app=app, menus=False, limit=limit, depth=depth, timeout=60)
    elapsed = round((time.perf_counter() - started) * 1000)
    return {
        "depth": depth,
        "ms": elapsed,
        "elements": len(page["elements"]),
        "named": sum(bool(e["label"]) for e in page["elements"]),
        "text": len(page["text"]),
        "typeable": len([e for e in page["elements"] if "TYPE_TEXT" in e["operations"]]),
        "page": page,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="Lark", help="app name, bundle id, or pid")
    parser.add_argument("--limit", type=int, default=600)
    options = parser.parse_args()

    bridge = Bridge()
    try:
        status = bridge.call("status")
        if not status["accessibility"]:
            raise SystemExit(
                "Accessibility permission is missing. System Settings > Privacy & Security > "
                "Accessibility: enable the app running this shell, then restart it."
            )
        try:
            bridge.call("snapshot", app=options.app, menus=False, limit=10, depth=8)
        except Exception as error:
            raise SystemExit(f"Cannot read {options.app!r}: {error}") from None

        rows = [look(bridge, options.app, depth, options.limit) for depth in DEPTHS]

        print(f"\n{options.app} — the same window, read at four traversal depths\n")
        for row in rows:
            print(f"depth {row['depth']}: {row['elements']} elements, {row['named']} named, "
                  f"{row['text']} text characters, {row['typeable']} editable, {row['ms']} ms")

        first, last = rows[0], rows[-1]
        print()
        gained = last["text"] - first["text"]
        if gained > 200 or last["typeable"] > first["typeable"]:
            print(f'At depth {first["depth"]}: {first["text"]} characters of readable text, '
                  f'{first["typeable"]} places to type, {first["named"]} named elements.')
            print(f'At depth {last["depth"]}: {last["text"]}, {last["typeable"]}, {last["named"]}. '
                  f'Same window, same instant, one number changed.')
        else:
            print(f'Nothing was hiding: this window reads the same at depth {first["depth"]} '
                  f'as at depth {last["depth"]}. That is what a native window looks like.')

        # What the deeper walk actually put within reach.
        named = [e for e in last["page"]["elements"] if e["label"] and e["operations"]]
        if named:
            print(f'\nNamed and actionable at depth {last["depth"]} ({len(named)} of them):')
            for element in named[:12]:
                label = element["label"].replace("\n", " ")
                print(f'  {element["role"].removeprefix("AX"):<12} {label[:66]}')
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
