"""The observed action table and the answer schema shared by both model backends."""

import json

from .questions import GUARD, TARGET, TEXT_VALUE


CONTROLS = {
    "PRESS_RETURN": ("Press Return, to commit the focused field or accept a dialog.", {"op": "KEY", "key": "return"}),
    "PRESS_ESCAPE": ("Press Escape, to dismiss an open menu, popover, or sheet.", {"op": "KEY", "key": "esc"}),
    "WAIT": ("Wait briefly for the interface to settle.", {"op": "WAIT"}),
}


TARGETED = {
    "SCROLL_UP": "Scroll an observed scroll area up.",
    "SCROLL_DOWN": "Scroll an observed scroll area down.",
    "PRESS": "Press an element: a button, checkbox, row, tab, link, or disclosure triangle.",
    "TYPE_TEXT": "Enter or replace the whole contents of an editable field.",
    "PASTE_TEXT": "Insert Unicode text at the observed field's current selection.",
    "SELECT_TEXT": "Select a UTF-16 character range in an observed text field.",
    "KEY_CHORD": "Send a keyboard editing command to an observed field.",
    "SELECT": "Choose a value from a pop-up button's menu.",
    "MENU": "Run a menu-bar command by name, without opening the menu first.",
    "CLICK": "Select an observed row through the app's native selection API.",

}


def icons(candidates, gap=16):
    """Paths of icons that only repeat the label sitting next to them.

    A sidebar entry is an icon and a word, and the tree publishes both, so the
    table offered "搜索" twice — once as the picture, once as the text. The
    model split its answer between them: 0.30 on one and 0.16 on the other for
    a single control, against a runner-up on 0.25. Nothing was wrong with
    either choice and the pair still lost.

    Only a picture that shares a line and a name with its own caption is
    dropped. Three elements reading 陈奕迅 in the same window are three
    different songs, sitting in three different places, and merging by name
    alone would take two of them away. So the test is geometric: same label,
    overlapping vertical band, horizontally within `gap` points.
    """
    text = [c for c in candidates if c["role"] == "AXStaticText" and c["label"]]
    out = set()
    for candidate in candidates:
        if candidate["role"] != "AXImage" or not candidate["label"]:
            continue
        x, y, w, h = candidate["frame"]
        for other in text:
            if other["label"] != candidate["label"]:
                continue
            ox, oy, ow, oh = other["frame"]
            same_line = y < oy + oh and oy < y + h
            near = min(abs(ox - (x + w)), abs(x - (ox + ow))) <= gap
            if same_line and near:
                out.add(candidate["path"])
                break
    return out


def scaffolding(candidates):
    """Paths of the unnamed elements that exist only to contain another one.

    A Chromium interface is built out of nested anonymous containers, and the
    accessibility tree reports each one as a pressable group with no name. Laid
    out as a flat indexed table they become a hundred choices that read alike
    and differ only by number — Lark offered 143 elements of which 121 were
    these. They are not choices. Whatever they wrap is the choice, and it is in
    the table too.

    A container is dropped when something else in the table sits inside it and
    the container either has no name of its own, or has the same name as the
    thing inside it. The second case is the common one once unnamed containers
    take their name from the words underneath: a row and the single box inside
    it both come back reading "HJDM", and only the inner one should be offered.

    A group with no name and no words under it is dropped outright. A group is
    a container by definition, and one that cannot say what it contains is not
    something a model can choose: in Lark these are the 24x21 avatars inside
    chat rows that are already offered by name, and the sidebar itself. An
    unnamed *button* is kept — that is an icon-only control, and nothing else
    in the table reaches it.
    """
    drop = {
        candidate["path"]
        for candidate in candidates
        if candidate["role"] == "AXGroup" and not candidate["label"] and not candidate.get("value")
    }
    for candidate in candidates:
        if candidate["role"] == "AXScrollArea":
            continue  # Its scroll action belongs to the container, not its children.
        inside = [
            other for other in candidates if other["path"].startswith(candidate["path"] + ".")
        ]
        if not inside:
            continue
        if not candidate["label"] or any(other["label"] == candidate["label"] for other in inside):
            drop.add(candidate["path"])
    return drop


def action_space(page, refused=()):
    """One index per element; each operation carries only the targets it can use.

    Returns the table shown to the model, the per-operation target maps, and the
    targetless controls. Only native background delivery is offered.

    `refused` is (operation, path) pairs the app turned down since the window
    last changed, and they are not offered again. Telling the model that a
    press was refused is not enough: on Music it chose the same button three
    times in a row with "outcome: failed" sitting in its history each time, and
    the run ended blocked having done nothing. A control the app has just
    refused is the one choice that is known to be wrong, and the cheapest place
    to act on that is the table, not the prompt.
    """
    refused = set(refused)
    background_clicks = set(page.get("background_clicks", []))
    candidates = []
    for source in page["elements"]:
        operations = [
            op for op in source["operations"]
            if op in TARGETED and (
                op != "CLICK" or source["index"] in background_clicks
            )
        ]
        if operations or source["role"] == "AXTextArea" or source.get("identity_proven") is False:
            candidates.append((source, operations))
    usable = [source for source, _ in candidates]
    wrappers = scaffolding(usable) | icons(usable)

    elements, targets = [], {}
    for source, available in candidates:
        if source["path"] in wrappers:
            continue
        operations = [op for op in available if (op, source["path"]) not in refused]
        # Every operation on it has just been refused, so it is not a choice.
        if not operations and source["role"] != "AXTextArea" and source.get("identity_proven") is not False:
            continue
        # References must not look like numeric control labels (Calculator digits).
        index = "e" + source["index"]
        shown = {"index": index, "role": source["role"].removeprefix("AX")}
        # No invented label. Writing the role into the label field turned a
        # hundred anonymous containers into a hundred elements all called
        # "Group", which reads as a table of real choices and is not one.
        if source["label"]:
            shown["label"] = source["label"]
        if source.get("secure"):
            shown["secure"] = True
        if len(page.get("windows", [])) > 1 and source.get("window"):
            shown["window"] = source["window"]
        if source.get("identity_proven") is False:
            shown["identity_proven"] = False
        if source.get("subtree_truncated"):
            shown["subtree_truncated"] = True
        shown["operations"] = operations
        name = source["label"] or source["role"].removeprefix("AX")
        for key in ("value", "checked", "selected", "selection"):
            value = source.get(key)
            # `checked` is about the control's own state, so False is news.
            # `selected` is False on almost everything and says nothing.
            if value in (None, "") or (key == "selected" and not value):
                continue
            shown[key] = value
        # The identity that must still hold at execution time. The identifier
        # is the strongest of these and the label the weakest, so all three go.
        expect = source["label"] or source["role"]
        identity = {"expect": expect, "expect_role": source["role"], "expect_id": source.get("identifier", "")}
        identity["secure"] = bool(source.get("secure"))
        for operation in operations:
            if operation == "SELECT":
                for position, option in enumerate(source.get("options", [])):
                    targets.setdefault("SELECT", {})["e" + option["index"]] = {
                        "operation": "SELECT",
                        "op": "SELECT",
                        "path": source["path"],
                        "option": option["child"],
                        **identity,
                        "label": f"{name} → {option['label']}",
                    }
                if source.get("options"):
                    shown["options"] = [o["label"] for o in source["options"]]
                else:
                    shown["operations"] = [o for o in operations if o != "SELECT"]
            else:
                targets.setdefault(operation, {})[index] = {
                    "operation": operation,
                    "op": operation,
                    "path": source["path"],
                    **identity,
                    "label": name,
                    "role": shown["role"],
                    "value": shown.get("value", ""),
                }
        elements.append(shown)

    for item in page.get("menus", []):
        targets.setdefault("MENU", {})[item["index"]] = {
            "operation": "MENU",
            "op": "MENU",
            "menu": item["path"],
            "label": item["label"],
        }

    controls = {name: {"operation": name, **body} for name, (_, body) in CONTROLS.items()}
    return elements, targets, controls


def questions_for(targets, controls):
    descriptions = CONTROLS
    operations = {name: TARGETED[name] for name in targets}
    operations.update({name: descriptions[name][0] for name in controls})
    operations["DONE"] = "Every requirement is visibly satisfied in the current window."
    operations["BLOCKED"] = "No offered operation can make progress."
    return operations


EDITING_KEYS = ["cmd+a", "cmd+c", "cmd+x", "cmd+v", "cmd+z", "cmd+shift+z", "cmd+left", "cmd+right",
                "left", "right", "up", "down", "shift+left", "shift+right", "alt+left", "alt+right",
                "shift+alt+left", "shift+alt+right", "delete", "forwarddelete", "tab", "shift+tab", "return", "escape"]


def parameter_properties(operations, targets):
    properties = {}
    if "KEY_CHORD" in operations:
        properties["key_chord_key"] = {"type": "string", "enum": EDITING_KEYS}
    if "SELECT_TEXT" in operations:
        bound = max((len(c.get("value", "").encode("utf-16-le")) // 2
                     for c in targets["SELECT_TEXT"].values()), default=0)
        for name in ("selection_start", "selection_length"):
            properties[name] = {"type": "integer", "enum": list(range(bound + 1)),
                                "description": "UTF-16 offset or length, assuming SELECT_TEXT runs."}
    return properties


def head_properties(operations, targets):
    """The fields the answer must contain: the operation, and one head per operation."""
    properties = {
        "operation": {"type": "string", "enum": sorted(operations)},
        "confidence": {"type": "number", "description": "0-1, how sure the operation is right"},
        "risk": {"type": "number", "description": GUARD},
        "risk_reason": {"type": "string", "description": "One clause naming what this operation changes."},
    }
    for operation, candidates in targets.items():
        properties[operation.lower() + "_target"] = {
            "type": "string",
            "enum": sorted(candidates),
            "description": f"{TARGET}\n\nThe operation assumed by this answer is {operation}.",
        }
    for operation in ("TYPE_TEXT", "PASTE_TEXT"):
        if operation in targets:
            properties[operation.lower() + "_value"] = {
                "type": ["string", "null"],
                "description": TEXT_VALUE + f" Answer as if {operation} is the operation that runs.",
            }
    properties.update(parameter_properties(operations, targets))
    return properties


def head_order(properties):
    """`operation` first, then the rest by name.

    A model writes the object in the order it is given, and every other head is
    conditioned on the operation. Asking for them alphabetically asked each one
    to be answered before the thing it depends on had been decided.
    """
    return ["operation"] + sorted(name for name in properties if name != "operation")


def schema_format(properties):
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "next_operation",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {name: properties[name] for name in head_order(properties)},
                "required": head_order(properties),
                "additionalProperties": False,
            },
        },
    }


def object_format_instructions(properties):
    """Spell the schema out for a provider that guarantees JSON but not its shape.

    Nothing downstream trusts this: an answer outside the offered choices is
    refused by `choose`, exactly as an invalid schema answer would be.
    """
    lines = [
        "Reply with one JSON object and nothing else. Write the keys in the order given,",
        "all of them required. Every key after the first is answered as if its own operation",
        "is the one that runs, whichever one you choose in the first:",
    ]
    for name in head_order(properties):
        spec = properties[name]
        kinds = spec.get("type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if "enum" in spec:
            lines.append(f'- "{name}": exactly one of {json.dumps(spec["enum"], ensure_ascii=False)}')
        elif "number" in kinds:
            lines.append(f'- "{name}": a number')
        elif name == "type_text_value":
            lines.append(f'- "{name}": a string, or null when the operation is not TYPE_TEXT')
        else:
            lines.append(f'- "{name}": a short string')
        if spec.get("description"):
            lines.append(f"    {spec['description']}")
    return "\n".join(lines)
