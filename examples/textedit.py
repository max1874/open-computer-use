#!/usr/bin/env python3
"""Replace an already-open scratch TextEdit document without activating the app.

Open a disposable document yourself, then switch to another app before running:
    uv run --env-file .env python examples/textedit.py

The example operates on the observed TextEdit window. It creates no windows and
never closes or quits TextEdit or any of the user's other documents.
"""

from open_computer_use import Agent

SENTENCE = "The quick brown fox jumps over the lazy dog."
GOAL = f"Replace everything in the document with exactly this one sentence: '{SENTENCE}'"


def reached(page):
    return any(e["role"] == "AXTextArea" and e["value"].strip() == SENTENCE for e in page["elements"])


def main():
    with Agent("TextEdit", GOAL, verify=reached) as agent:
        for state in agent.run():
            print(state["status"])
        print(f"Observed outcome: {agent.state['verified']}")
        print("Endpoint focus samples are diagnostic; full-run focus acceptance needs activation events.")


if __name__ == "__main__":
    main()
