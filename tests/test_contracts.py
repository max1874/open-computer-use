"""Regression contracts. Run in CI, never on the owner's workstation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from open_computer_use.cua import parse
from open_computer_use.desktop import Bridge, UnknownOutcome
from open_computer_use.model import choose


class TreeContracts(unittest.TestCase):
    def test_exact_limit_does_not_claim_missing_nodes(self):
        page = parse("1 group Root\n  2 button Save", limit=2)
        self.assertTrue(page["complete"])
        self.assertFalse(page["truncated"])

    def test_omitted_descendant_marks_its_published_parent(self):
        page = parse("1 group Root\n  2 button Save\n  3 button Cancel", limit=2)
        self.assertFalse(page["complete"])
        self.assertTrue(page["elements"][0]["subtree_truncated"])
        self.assertFalse(page["elements"][1]["subtree_truncated"])
        self.assertEqual(page["nodes_observed"], 3)

    def test_secure_host_field_does_not_enter_the_value_table(self):
        page = parse("1 secure text field Password, Value: synthetic-secret")
        self.assertTrue(page["elements"][0]["secure"])
        self.assertEqual(page["elements"][0]["value"], "")
        self.assertNotIn("synthetic-secret", json.dumps(page))


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
            return choose(self.page, "Edit the scratch document", [], pointer=True)

    def test_destination_is_looked_up_in_the_observed_table(self):
        result = self.decide({"operation": "DRAG", "drag_target": "1", "drag_destination": "2"})
        self.assertEqual(result["action"]["destination_path"], "0.2")

    def test_generated_destination_path_cannot_be_executed(self):
        with self.assertRaises(ValueError):
            self.decide({"operation": "DRAG", "drag_target": "1", "drag_destination": "0.99"})

    def test_unoffered_shortcut_is_refused(self):
        with self.assertRaises(ValueError):
            self.decide({"operation": "KEY_CHORD", "key_chord_target": "1", "key_chord_key": "cmd+q"})

    def test_negative_and_boolean_selections_are_refused(self):
        for start in (-1, True):
            with self.subTest(start=start), self.assertRaises(ValueError):
                self.decide({"operation": "SELECT_TEXT", "select_text_target": "1",
                             "selection_start": start, "selection_length": 1})


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
