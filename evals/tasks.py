"""The task set: one goal, one app, a reset, and a check that reads the result back.

Every check reads the app's own state after the run — AppleScript, the file
system, or a fresh snapshot — and never the agent's history or its DONE. Each
setup puts the app in a state where its check is false, so a pass is something
this run did. Each task also has a `solve` that reaches the goal without a
model, by script or by pressing the buttons directly, and
`python -m evals.run --sensitivity` runs setup → check → solve → check for every
task: a check is only trusted if it says false before and true after.

Nothing here takes the screen: no task asks for `activate`, so menus are out
and every task is one a background run can finish.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from open_computer_use.desktop import Desktop

SCRATCH = Path.home() / "OCU-Eval"


@dataclass(frozen=True)
class Task:
    id: str
    app: str
    goal: str
    setup: Callable[[], None]
    check: Callable[[], bool]
    solve: Callable[[], None]


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True).stdout.strip()


def launch(app):
    # macOS quits an idle background app on its own, so make sure it is up.
    subprocess.run(["open", "-g", "-a", app], check=True)
    time.sleep(1.5)


def page(app):
    desktop = Desktop(app, menus=False)
    try:
        return desktop.observe()
    finally:
        desktop.close()


# Calculator ---------------------------------------------------------------


def calculator_clear():
    """A cleared display and a hidden tape, so only this run's result can match."""
    launch("Calculator")
    desktop = Desktop("Calculator", menus=True)
    try:
        current = desktop.observe()
        if any(m["label"] == "View > Hide History" for m in current.get("menus", [])):
            desktop.act({"operation": "MENU", "op": "MENU", "menu": "View > Hide History"}, current)
            current = desktop.observe()
        for _ in range(2):  # Clear, then All Clear
            button = next((e for e in current["elements"] if e["label"] in ("All Clear", "Clear")), None)
            if button:
                desktop.act({"operation": "PRESS", "op": "PRESS", "path": button["path"], "expect": "Clear"}, current)
                current = desktop.observe()
    finally:
        desktop.close()


def calculator_press(*labels):
    def solve():
        desktop = Desktop("Calculator", menus=False)
        try:
            for label in labels:
                current = desktop.observe()
                button = next(e for e in current["elements"] if e["label"] == label)
                desktop.act({"operation": "PRESS", "op": "PRESS", "path": button["path"], "expect": label}, current)
        finally:
            desktop.close()

    return solve


def calculator_shows(expected):
    def check():
        lines = [line for line in page("Calculator")["text"].replace("‎", "").splitlines() if line.strip()]
        return bool(lines) and lines[-1].replace(",", "").strip() == expected

    return check


# TextEdit -----------------------------------------------------------------


# The task document is a file of our own, opened and closed by name, so a reset
# never touches a document Max has open in TextEdit.
DOCUMENT = SCRATCH / "task.txt"


def textedit_with(text):
    def setup():
        close_document()
        SCRATCH.mkdir(exist_ok=True)
        DOCUMENT.write_text(text)
        # A cold TextEdit puts up its Open panel next to any document it is
        # given, and the snapshot then reads the panel. The argument turns the
        # panel off for this launch only, leaving Max's own setting alone.
        subprocess.run(["open", "-g", "-a", "TextEdit", str(DOCUMENT), "--args",
                        "-NSShowAppCentricOpenPanelInsteadOfUntitledFile", "NO"], check=True)
        time.sleep(1.0)

    return setup


def close_document():
    osa('if application "TextEdit" is running then tell application "TextEdit" to '
        f'close (every document whose name is "{DOCUMENT.name}") saving no')


def textedit_set(text):
    literal = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return lambda: osa(f'tell application "TextEdit" to set text of document "{DOCUMENT.name}" to "{literal}"')


def textedit_text():
    return osa(f'tell application "TextEdit" to get text of document "{DOCUMENT.name}"')


# System Settings ----------------------------------------------------------


def settings_at_general():
    subprocess.run(["open", "-g", "x-apple.systempreferences:com.apple.systempreferences.GeneralSettings"], check=True)
    time.sleep(2.0)


def settings_open(pane):
    def solve():
        subprocess.run(["open", "-g", f"x-apple.systempreferences:{pane}"], check=True)
        time.sleep(2.0)

    return solve


def settings_window_is(title):
    # The pane title is typeset: Wi‑Fi carries a non-breaking hyphen.
    return lambda: page("System Settings")["window"].replace("\u2011", "-") == title


# Dictionary ---------------------------------------------------------------


def dictionary_at_apple():
    subprocess.run(["open", "-g", "dict://apple"], check=True)
    time.sleep(1.5)


def dictionary_open(word):
    def solve():
        subprocess.run(["open", "-g", f"dict://{word}"], check=True)
        time.sleep(1.5)

    return solve


def dictionary_shows(*words):
    def check():
        text = page("Dictionary")["text"].lower()
        return all(word in text for word in words)

    return check


# Safari -------------------------------------------------------------------
# Read through the window, not AppleScript: scripting Safari needs an Automation
# grant that a background run should not be the thing that asks for it.


def safari_open(url):
    def go():
        subprocess.run(["open", "-g", "-a", "Safari", url], check=True)
        time.sleep(2.5)

    return go


def safari_title_has(fragment):
    def check():
        # Give a navigation that was just submitted time to load its title.
        for _ in range(10):
            if fragment in page("Safari")["window"]:
                return True
            time.sleep(0.5)
        return False

    return check


# Finder -------------------------------------------------------------------


def finder_at_scratch():
    for name in ("Reports", "Photos", "Notes"):
        (SCRATCH / name).mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", "-g", str(SCRATCH)], check=True)
    time.sleep(1.0)


def finder_go(folder):
    def go():
        subprocess.run(["open", "-g", str(SCRATCH / folder)], check=True)
        time.sleep(1.0)

    return go


def finder_in(folder):
    return lambda: page("Finder")["window"] == folder


def running_apps():
    names = osa('tell application "System Events" to get name of every process whose background only is false')
    return set(names.split(", "))


def tidy(app, was_running):
    """Put an app back the way the run found it: close what the tasks opened,
    and quit the app if it was not running before."""
    if app == "Finder":
        for name in ("OCU-Eval", "Reports", "Photos", "Notes"):
            osa(f'tell application "Finder" to repeat while exists Finder window "{name}"\n'
                f'close Finder window "{name}"\nend repeat')
        return
    if app == "TextEdit":
        close_document()
    if app not in was_running:
        osa(f'tell application "{app}" to quit')


TASKS = [
    Task("calc-multiply", "Calculator", "Compute 12 times 34 and leave the result on the display.",
         calculator_clear, calculator_shows("408"),
         calculator_press("1", "2", "Multiply", "3", "4", "Equals")),
    Task("calc-divide", "Calculator", "Compute 1024 divided by 16 and leave the result on the display.",
         calculator_clear, calculator_shows("64"),
         calculator_press("1", "0", "2", "4", "Divide", "1", "6", "Equals")),
    Task("calc-decimal", "Calculator", "Compute 3.5 plus 2.25 and leave the result on the display.",
         calculator_clear, calculator_shows("5.75"),
         calculator_press("3", "Point", "5", "Add", "2", "Point", "2", "5", "Equals")),
    Task("calc-chain", "Calculator", "Compute 15 plus 27, then subtract 8, and leave the result on the display.",
         calculator_clear, calculator_shows("34"),
         calculator_press("1", "5", "Add", "2", "7", "Subtract", "8", "Equals")),
    Task("textedit-write", "TextEdit", "Write 'Meeting moved to Thursday' in the document.",
         textedit_with(""), lambda: textedit_text().strip() == "Meeting moved to Thursday",
         textedit_set("Meeting moved to Thursday")),
    Task("textedit-edit", "TextEdit", "Change Monday to Friday in the document, keeping the rest of the sentence.",
         textedit_with("The review is on Monday at 10."),
         lambda: textedit_text().strip() == "The review is on Friday at 10.",
         textedit_set("The review is on Friday at 10.")),
    Task("textedit-append", "TextEdit", "Add a second line that says 'Bring the slides.' below the existing text.",
         textedit_with("Team sync at 3pm."),
         lambda: [l.strip() for l in textedit_text().splitlines() if l.strip()] == ["Team sync at 3pm.", "Bring the slides."],
         textedit_set("Team sync at 3pm.\nBring the slides.")),
    Task("settings-wifi", "System Settings", "Open the Wi-Fi settings.",
         settings_at_general, settings_window_is("Wi-Fi"),
         settings_open("com.apple.wifi-settings-extension")),
    Task("settings-keyboard", "System Settings", "Open the Keyboard settings.",
         settings_at_general, settings_window_is("Keyboard"),
         settings_open("com.apple.Keyboard-Settings.extension")),
    Task("settings-appearance", "System Settings", "Open the Appearance settings.",
         settings_at_general, settings_window_is("Appearance"),
         settings_open("com.apple.Appearance-Settings.extension")),
    Task("dictionary-serendipity", "Dictionary", "Look up the word 'serendipity'.",
         dictionary_at_apple, dictionary_shows("serendipity", "chance"),
         dictionary_open("serendipity")),
    Task("dictionary-ephemeral", "Dictionary", "Look up the word 'ephemeral'.",
         dictionary_at_apple, dictionary_shows("ephemeral", "short time"),
         dictionary_open("ephemeral")),
    Task("safari-example", "Safari", "Go to example.com.",
         safari_open("about:blank"), safari_title_has("Example Domain"),
         safari_open("https://example.com/")),
    Task("safari-wikipedia", "Safari", "Open the Wikipedia article about Alan Turing.",
         safari_open("about:blank"), safari_title_has("Alan Turing"),
         safari_open("https://en.wikipedia.org/wiki/Alan_Turing")),
    Task("finder-reports", "Finder", "Open the Reports folder.",
         finder_at_scratch, finder_in("Reports"), finder_go("Reports")),
    Task("finder-notes", "Finder", "Open the Notes folder.",
         finder_at_scratch, finder_in("Notes"), finder_go("Notes")),
]
