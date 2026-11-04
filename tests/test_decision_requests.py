"""Native requests retain observed targets/history and never offer frontmost input."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from open_computer_use.model import choose


class RequestContracts(unittest.TestCase):
    def test_native_request_shape_includes_history_without_visual_or_logprob_branches(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/native_observations.json").read_text())
        for case in fixture["cases"]:
            for mode in ("json_schema", "json_object"):
                environment = {"DECISION_BASE_URL": "http://localhost/v1", "DECISION_MODEL": "fixture",
                               "DECISION_API_KEY": "dummy", "DECISION_RESPONSE_FORMAT": mode}
                with self.subTest(case=case["name"], mode=mode), patch.dict(os.environ, environment, clear=True):
                    bodies = []
                    def capture(url, key, body):
                        bodies.append(body)
                        return {"choices": [{"message": {"content": '{"operation":"DONE","risk":0}'}}]}
                    with patch("open_computer_use.model.post_json", side_effect=capture):
                        choose(fixture["pages"][case["page"]], case["goal"], case["history"],
                               refused=[tuple(pair) for pair in case["refused"]])
                    self.assertEqual(len(bodies), 1)
                    body = bodies[0]
                    self.assertNotIn("logprobs", body)
                    self.assertNotIn("top_logprobs", body)
                    self.assertIsInstance(body["messages"][1]["content"], str)
                    state = json.loads(body["messages"][1]["content"])
                    self.assertEqual(state["goal"], case["goal"])
                    self.assertNotIn("screenshot", state)
                    for op in ("DRAG", "DRAG_POINT", "CLICK_POINT", "TYPE_KEYS"):
                        self.assertNotIn(op, state["offered_operations"])
                    if case["history"]:
                        self.assertEqual(state["recent_actions"][-1]["text"], case["history"][-1]["text"])
                        self.assertEqual(state["recent_actions"][-1]["disposition"], case["history"][-1]["disposition"])
                    if case["refused"]:
                        field = next(e for e in state["elements"] if e.get("label") == "Message")
                        self.assertNotIn("TYPE_TEXT", field["operations"])

    def test_jev_keeps_the_same_background_targets(self):
        page = {"app": "Scratch", "window": "Document", "text": "", "elements": [
            {"index": "1", "path": "0.1", "role": "AXButton", "label": "Advance", "frame": [0, 0, 30, 30],
             "operations": ["PRESS"]}]}
        reply = {"answers": {"operation": {"choice": "PRESS", "confidence": 1},
                             "press_target": {"choice": "1"}, "risk": {"score": 0}}}
        with patch.dict(os.environ, {"JEV_API_KEY": "dummy"}, clear=True), patch(
            "open_computer_use.model.post_json", return_value=reply
        ):
            decision = choose(page, "Advance", [])
        self.assertEqual(decision["action"]["path"], "0.1")
