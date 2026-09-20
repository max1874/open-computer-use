"""Read Codex Computer Use's accessibility text as this project's element table.

Computer Use is reachable only from inside its host's JavaScript runtime, where
a global `cua` already exists. So the executor lives there and this stays what
it was: the part that decides. `runtime/loop.mjs` is the hundred lines on the
other side; everything below turns what it observes into the same indexed table
`model.action_space` has always been given, so one decision layer serves both
executors.

Two things are different from the bridge's snapshot and the difference is the
point of this module.

The index is the address. The bridge addresses an element by a path of child
indices and carries the label the decision was made about, because a path is a
guess about a tree that may have moved. Computer Use hands out a number per
node per observation and the numbers are only valid until the next one, so the
loop re-reads the whole tree after every action and never reuses an index.
Nothing is gained by pretending otherwise, so `path` here is a hierarchy built
from the indentation — `scaffolding` needs prefix containment and nothing else
— while `index` stays exactly what `sky.click` expects.

There is no geometry. The text says what an element is and where it sits in the
tree, never where it is on the screen. Everything here that reasons about
rectangles is therefore off: the icon/caption merge, the sparseness measure,
and the screenshot path they feed. Computer Use takes its own screenshots and
has its own opinion about when to use them.
"""

import re

# Roles as Computer Use spells them: lower case, spaces, no AX prefix. Longest
# first, because "close button" has to win against "button".
ROLES = [
    "standard window",
    "split group",
    "scroll area",
    "HTML content",
    "content list",
    "menu bar main-menu-bar",
    "menu bar",
    "menu item",
    "radio button",
    "close button",
    "zoom button",
    "minimize button",
    "full screen button",
    "search field",
    "text field",
    "pop up button",
    "toggle button",
    "date time area",
    "static text",
    "combo box",
    "check box",
    "checkbox",
    "disclosure triangle",
    "toolbar",
    "stepper",
    "button",
    "heading",
    "container",
    "image",
    "link",
    "text",
    "grid",
    "list",
    "cell",
    "row",
    "tab",
    "column",
    "group",
    "slider",
    "table",
]

# What this project calls the roles above. Only the distinctions the action
# space actually makes are worth keeping.
PRESSABLE = {
    "button",
    "close button",
    "zoom button",
    "minimize button",
    "full screen button",
    "radio button",
    "checkbox",
    "check box",
    "toggle button",
    "disclosure triangle",
    "link",
    "menu item",
    "tab",
    "pop up button",
    "combo box",
    "stepper",
}
EDITABLE = {"text field", "search field", "combo box"}
# Everything that carries content and answers to no action of its own. Computer
# Use will click any index, so these are reachable — which is the same argument
# that put CLICK in the bridge, arrived at from the other direction.
CONTENT = {"static text", "text", "row", "cell", "image", "heading", "list", "date time area"}

LINE = re.compile(r"^(?P<indent>[\t ]*)(?P<index>\d+)\s+(?P<rest>.*)$")
HEADER = re.compile(r'^Window:\s*"(?P<window>[^"]*)",\s*App:\s*(?P<app>.*?)\.?$')
# Trailing metadata, in the order Computer Use emits it.
FIELDS = ("Description", "ID", "Help", "Value", "URL", "Secondary Actions")


def split_fields(rest):
    """Separate an element's name from the metadata printed after it."""
    found = {}
    cut = len(rest)
    for name in FIELDS:
        match = re.search(rf"(?:^|,)\s*{name}:\s*", rest)
        if not match:
            continue
        cut = min(cut, match.start())
        start = match.end()
        following = [
            m.start()
            for other in FIELDS
            for m in [re.search(rf",\s*{other}:\s*", rest[start:])]
            if m
        ]
        end = start + min(following) if following else len(rest)
        found[name] = rest[start:end].strip()
    return rest[:cut].strip().strip(","), found


def parse(text, limit=250):
    """One page, shaped like the bridge's, out of Computer Use's tree text."""
    lines = text.split("\n")
    app = window = ""
    header = HEADER.match(lines[0]) if lines else None
    if header:
        app, window = header.group("app").strip(), header.group("window").strip()

    elements, texts = [], []
    stack = []  # (indent, path) of the open ancestors
    for line in lines:
        match = LINE.match(line)
        if not match:
            continue
        indent = len(match.group("indent").replace("\t", "    "))
        index = match.group("index")
        rest = match.group("rest").strip()

        enabled = "(disabled)" not in rest
        settable = "(settable)" in rest
        rest = rest.replace("(disabled)", "").replace("(settable)", "").strip()
        role = next((r for r in ROLES if rest == r or rest.startswith(r + " ") or rest.startswith(r + ",")), "")
        remainder = rest[len(role) :].strip() if role else rest
        name, fields = split_fields(remainder)
        label = name or fields.get("Description", "") or fields.get("Help", "")
        value = fields.get("Value", "")
        actions = [a.strip() for a in fields.get("Secondary Actions", "").split(",") if a.strip()]

        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = f"{stack[-1][1]}.{index}" if stack else index
        stack.append((indent, path))

        if role in ("static text", "text") and label:
            texts.append(label)

        operations = []
        if enabled:
            if role in PRESSABLE:
                operations.append("PRESS")
            if role in EDITABLE and (settable or role == "search field"):
                operations.append("TYPE_TEXT")
            if role == "pop up button":
                operations.append("SELECT")
            for action in actions:
                if action in ("Increment", "Decrement"):
                    operations.append(action.upper())
            if not operations and role in CONTENT and label:
                operations.append("CLICK")

        elements.append(
            {
                "index": index,
                "path": path,
                "role": "AX" + "".join(part.capitalize() for part in (role or "unknown").split()),
                "subrole": "",
                "identifier": fields.get("ID", ""),
                "label": label,
                "value": value,
                "enabled": enabled,
                "focused": False,
                "checked": None,
                "selected": None,
                # No geometry in this text. Callers must check `geometry`
                # before measuring anything, rather than reading four zeroes as
                # an element in the top-left corner with no size.
                "frame": [0, 0, 0, 0],
                "operations": operations,
                "options": [],
                "describe": f"{role} {label}".strip(),
            }
        )
        if len(elements) >= limit:
            break

    return {
        "app": app,
        "window": window,
        "window_frame": None,
        "geometry": False,
        "elements": elements,
        "menus": [],
        "text": "\n".join(texts)[:6000],
        # The tree text is the state, so it is also the freshness fingerprint.
        # Cheap, and exactly as strict as re-reading: any change at all is a
        # change. The bridge can afford to be subtler because it knows which
        # part of an element moved.
        "fingerprint": str(hash(text)),
        "truncated": len(elements) >= limit,
        "active": None,
        "sparse": False,
        "actionable": sum(1 for e in elements if e["operations"]),
        "named": sum(1 for e in elements if e["operations"] and e["label"]),
        "coverage": None,
    }
