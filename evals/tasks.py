"""Legacy task goals and independent application readings, without scripted solves."""
from contextlib import closing
from dataclasses import dataclass

from open_computer_use.desktop import Desktop

BUNDLES = {"Calculator": "com.apple.calculator", "TextEdit": "com.apple.TextEdit",
           "System Settings": "com.apple.systempreferences", "Dictionary": "com.apple.Dictionary",
           "Safari": "com.apple.Safari", "Finder": "com.apple.finder"}


@dataclass(frozen=True)
class Task:
    id: str
    app: str
    goal: str
    initial: str
    expected: str

    def launch(self, scratch):
        config = {"bundle": BUNDLES[self.app]}
        if self.app == "TextEdit":
            document = scratch / "task.txt"
            document.write_text(self.initial)
            config["url"] = document.as_uri()
        elif self.app == "Finder":
            for name in ("Reports", "Photos", "Notes"):
                (scratch / name).mkdir()
            config["folder"] = str(scratch)
        elif self.app in {"Safari", "System Settings"}:
            config["url"] = self.initial
        return config

    def prepare(self, pid):
        if self.app not in {"Calculator", "Dictionary"}:
            return
        with closing(Desktop(str(pid), menus=False)) as desktop:
            page = desktop.observe()
            if self.app == "Calculator":
                target = next(e for e in page["elements"] if e["label"] in {"Clear", "All Clear"})
                desktop.act({"operation": "PRESS", "path": target["path"]}, page)
            else:
                target = next(e for e in page["elements"] if "TYPE_TEXT" in e["operations"] and "search" in e["label"].lower())
                desktop.act({"operation": "TYPE_TEXT", "path": target["path"]}, page, text=self.initial)
                desktop.act({"operation": "PRESS_RETURN", "op": "KEY", "key": "return"}, desktop.observe())

    def read(self, pid):
        # The native owner reads Finder's exact window target at lease/cleanup.
        if self.app == "Finder":
            return None, None
        # A new client reads the app, never the Agent's cached page or its DONE.
        with closing(Desktop(str(pid), menus=False)) as desktop:
            page = desktop.observe()
        if self.app == "Calculator":
            lines = [s.strip() for s in page["text"].replace("\u200e", "").splitlines() if s.strip()]
            actual = lines[-1].replace(",", "") if lines else ""
        elif self.app == "TextEdit":
            actual = next(e["value"] for e in page["elements"] if e["role"] == "AXTextArea").strip()
        elif self.app == "System Settings":
            # Pane titles can arrive after the content. A sidebar selection or
            # an arbitrary setting label never establishes navigation.
            actual = page["window"].replace("\u2011", "-").strip()
            if not actual:
                sidebar = [e for e in page["elements"] if e["role"] == "AXScrollArea" and e["label"] == "Sidebar"]
                if len(sidebar) != 1:
                    return None, None
                actual = next((e["value"].strip() for e in page["elements"]
                               if e["role"] == "AXStaticText" and not e["path"].startswith(sidebar[0]["path"] + ".")), None)
            if actual not in {"General", "Keyboard", "Wi-Fi", "Appearance"}:
                return None, actual
            return actual == self.expected, actual
        elif self.app == "Dictionary":
            actual = page["text"].lower()
            return all(word in actual for word in self.expected.split("|")), actual
        else:
            actual = page["window"].replace("\u2011", "-")
        return (self.expected in actual if self.app == "Safari" else actual == self.expected), actual


GENERAL = "x-apple.systempreferences:com.apple.systempreferences.GeneralSettings"
TASKS = [
    Task("calc-multiply", "Calculator", "Compute 12 times 34 and leave the result on the display.", "", "408"),
    Task("calc-divide", "Calculator", "Compute 1024 divided by 16 and leave the result on the display.", "", "64"),
    Task("calc-decimal", "Calculator", "Compute 3.5 plus 2.25 and leave the result on the display.", "", "5.75"),
    Task("calc-chain", "Calculator", "Compute 15 plus 27, then subtract 8, and leave the result on the display.", "", "34"),
    Task("textedit-write", "TextEdit", "Write 'Meeting moved to Thursday' in the document.", "", "Meeting moved to Thursday"),
    Task("textedit-edit", "TextEdit", "Change Monday to Friday in the document, keeping the rest of the sentence.",
         "The review is on Monday at 10.", "The review is on Friday at 10."),
    Task("textedit-append", "TextEdit", "Add a second line that says 'Bring the slides.' below the existing text.",
         "Team sync at 3pm.", "Team sync at 3pm.\nBring the slides."),
    Task("settings-wifi", "System Settings", "Open the Wi-Fi settings.", GENERAL, "Wi-Fi"),
    Task("settings-keyboard", "System Settings", "Open the Keyboard settings.", GENERAL, "Keyboard"),
    Task("settings-appearance", "System Settings", "Open the Appearance settings.", GENERAL, "Appearance"),
    Task("dictionary-serendipity", "Dictionary", "Look up the word 'serendipity'.", "apple", "serendipity|chance"),
    Task("dictionary-ephemeral", "Dictionary", "Look up the word 'ephemeral'.", "apple", "ephemeral|short time"),
    Task("safari-example", "Safari", "Go to example.com.", "about:blank", "Example Domain"),
    Task("safari-wikipedia", "Safari", "Open the Wikipedia article about Alan Turing.", "about:blank", "Alan Turing"),
    Task("finder-reports", "Finder", "Open the Reports folder.", "", "Reports"),
    Task("finder-notes", "Finder", "Open the Notes folder.", "", "Notes"),
]
