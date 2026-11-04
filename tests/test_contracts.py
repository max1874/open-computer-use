"""Regression contracts. Run in CI, never on the owner's workstation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from open_computer_use.desktop import Bridge, UnknownOutcome
from open_computer_use.model import choose, action_space


class DecisionContracts(unittest.TestCase):
    def setUp(self):
        self.page = {"app": "Scratch", "window": "Document", "text": "", "geometry": False,
                     "menus": [], "elements": [
            {"index": str(index), "path": f"0.{index}", "role": "AXTextArea", "label": name,
             "value": "Hello", "frame": [0, 0, 100, 100], "operations": ["SELECT_TEXT", "KEY_CHORD", "DRAG"]}
            for index, name in [(1, "Source"), (2, "Destination")]]}

    def decide(self, answer):
        reply = {"answer": {"risk": 0, "confidence": 1, "risk_reason": "editing", **answer},
                 "probabilities": {}, "model": "stand-in", "usage": {}, "latency_ms": 0}
        with patch.dict(os.environ, {"JEV_API_KEY": ""}), patch("open_computer_use.model.ask_chat", return_value=reply):
            return choose(self.page, "Edit the scratch document", [])

    def test_numeric_labels_are_distinct_from_model_refs_and_keep_the_native_path(self):
        self.page["elements"] = [
            {"index": index, "path": path, "role": "AXButton", "label": label,
             "frame": [0, 0, 30, 30], "operations": ["PRESS"]}
            for index, path, label in [("2", "0.7", "Delete"), ("15", "0.3", "2")]]
        elements, targets, _ = action_space(self.page)
        self.assertEqual([(e["index"], e["label"]) for e in elements], [("e2", "Delete"), ("e15", "2")])
        decision = self.decide({"operation": "PRESS", "press_target": "e15"})
        self.assertEqual(decision["action"]["path"], "0.3")
        with self.assertRaises(ValueError):
            self.decide({"operation": "PRESS", "press_target": "2"})
        self.assertEqual(self.page["elements"][1]["index"], "15")

    def test_option_refs_are_prefixed_without_changing_native_choice(self):
        element = self.page["elements"][0]
        element.update(role="AXPopUpButton", label="Color", operations=["SELECT"],
                       options=[{"index": "1:0", "child": 0, "label": "Green"}])
        decision = self.decide({"operation": "SELECT", "select_target": "e1:0"})
        self.assertEqual(decision["action"]["path"], "0.1")
        self.assertEqual(decision["action"]["option"], 0)

    def test_retired_pointer_operations_cannot_be_selected(self):
        for op in ("DRAG", "DRAG_POINT", "CLICK_POINT", "TYPE_KEYS"):
            with self.subTest(operation=op), self.assertRaises(ValueError):
                self.decide({"operation": op, "drag_target": "1", "drag_destination": "2"})

    def test_click_requires_an_observed_native_selection_capability(self):
        self.page["elements"][0]["operations"] = ["CLICK"]
        _, targets, _ = action_space(self.page)
        self.assertNotIn("CLICK", targets)
        self.page["background_clicks"] = ["1"]
        _, targets, _ = action_space(self.page)
        self.assertEqual(targets["CLICK"]["e1"]["op"], "CLICK")

    def test_unoffered_shortcut_is_refused(self):
        with self.assertRaises(ValueError):
            self.decide({"operation": "KEY_CHORD", "key_chord_target": "e1", "key_chord_key": "cmd+q"})

    def test_negative_and_boolean_selections_are_refused(self):
        for start in (-1, True):
            with self.subTest(start=start), self.assertRaises(ValueError):
                self.decide({"operation": "SELECT_TEXT", "select_text_target": "e1",
                             "selection_start": start, "selection_length": 1})

    def test_window_context_is_only_added_when_it_distinguishes_targets(self):
        self.page["windows"] = [{"title": "Document"}]
        self.page["elements"][0]["window"] = "Document"
        elements, _, _ = action_space(self.page)
        self.assertNotIn("window", elements[0])
        self.page["windows"].append({"title": "Other"})
        elements, _, _ = action_space(self.page)
        self.assertEqual(elements[0]["window"], "Document")


class TransportContracts(unittest.TestCase):
    def test_lost_mutation_reply_is_not_replayed_on_a_fresh_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "deliveries"
            helper = Path(directory) / "bridge"
            helper.write_text(f"""#!{sys.executable}
import json, sys
from pathlib import Path
for line in sys.stdin:
    request = json.loads(line)
    identity = request['id']
    if request['method'] == 'act':
        with Path({str(marker)!r}).open('a') as output:
            output.write('delivered\\n')
        identity += 1
    print(json.dumps({{'id': identity, 'ok': True, 'result': {{'pong': True}}}}), flush=True)
""")
            helper.chmod(0o700)
            with patch("open_computer_use.desktop.binary", return_value=str(helper)):
                bridge = Bridge()
            try:
                with self.assertRaises(UnknownOutcome) as caught:
                    bridge.call("act", mutating=True)
                self.assertEqual(caught.exception.disposition["retry"], "unsafe")
                self.assertEqual(bridge.call("ping"), {"pong": True})
                self.assertEqual(marker.read_text().splitlines(), ["delivered"])
            finally:
                bridge.close()
