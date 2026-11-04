"""The public loop must preserve execution evidence across its terminal paths."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from open_computer_use.agent import Agent
from open_computer_use.cua import parse
from open_computer_use.desktop import BridgeError, UnknownOutcome, disposition


class AgentContracts(unittest.TestCase):
    def setUp(self):
        self.page = parse("1 secure text field (settable) Message, Value: before")
        self.desktop = Mock(activation={})
        self.desktop.observe.return_value = self.page
        self.desktop.fresh.return_value = True
        self.desktop.act.return_value = {"disposition": disposition("delivered_unverified")}
        self.decision = {
            "operation": "TYPE_TEXT", "target": "1", "text": "synthetic-input", "pixels": False,
            "action": {"operation": "TYPE_TEXT", "path": "1", "label": "Message", "secure": True},
            "risk": 0, "risk_reason": "editing", "confidence": 1, "model": "fixture",
            "usage": {}, "latency_ms": 0, "probabilities": {}, "offered": {},
        }
        self.enterContext(patch("open_computer_use.agent.Desktop", return_value=self.desktop))
        self.enterContext(patch("open_computer_use.agent.choose", side_effect=lambda *a, **kw: deepcopy(self.decision)))

    def test_unknown_delivery_is_recorded_once_and_cannot_be_replayed(self):
        self.desktop.act.side_effect = UnknownOutcome("reply lost")
        with Agent("Scratch", "Edit message", pixels=False) as agent:
            result = agent.command("tick")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(len(result["history"]), 1)
            self.assertEqual(result["history"][0]["disposition"], disposition("delivery_uncertain"))
            self.assertNotIn("synthetic-input", json.dumps(result))
            with self.assertRaises(ValueError):
                agent.command("act", {"fingerprint": self.page["fingerprint"]})
            self.assertEqual(self.desktop.act.call_count, 1)

    def test_delivery_is_recorded_before_the_following_observation(self):
        with Agent("Scratch", "Edit message", pixels=False) as agent:
            def observation_failed():
                self.assertEqual(len(agent.state["history"]), 1)
                raise BridgeError("window disappeared")
            self.desktop.observe.side_effect = observation_failed
            result = agent.command("tick")
            self.assertEqual(result["status"], "blocked")
            row = result["history"][0]
            self.assertEqual(row["disposition"], disposition("delivered_unverified"))
            self.assertEqual(row["unobserved"], "window disappeared")
            self.assertIsNone(row["text"])

    def test_preparation_failure_never_reaches_the_executor(self):
        self.decision["text"] = None
        with patch("open_computer_use.agent.field_text", side_effect=ValueError("synthetic-input")):
            with Agent("Scratch", "Edit message", pixels=False) as agent:
                result = agent.command("tick")
                self.assertEqual(result["history"][0]["outcome"], "not attempted")
                self.assertEqual(result["history"][0]["disposition"], disposition("not_delivered"))
                self.assertNotIn("synthetic-input", json.dumps(result))
                self.desktop.act.assert_not_called()

    def test_three_refusals_keep_their_history_and_stop(self):
        self.page = parse("1 secure text field (settable) Message\n2 secure text field (settable) Second\n3 secure text field (settable) Third")
        self.desktop.observe.return_value = self.page
        self.desktop.act.side_effect = BridgeError("disabled")
        with Agent("Scratch", "Edit message", pixels=False) as agent:
            for index, label in enumerate(("Message", "Second", "Third"), 1):
                self.decision["target"] = str(index)
                self.decision["action"].update(path=str(index), label=label)
                result = agent.command("tick")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual([h["step"] for h in result["history"]], [1, 2, 3])
            self.assertTrue(all(h["disposition"] == disposition("not_delivered") for h in result["history"]))

    def test_a_new_observation_invalidates_previous_refusals(self):
        with Agent("Scratch", "Edit message", pixels=False) as agent:
            agent.refused.add(("TYPE_TEXT", "1"))
            changed = deepcopy(self.page)
            changed["fingerprint"] = "new observation"
            self.desktop.observe.return_value = changed
            self.desktop.fresh.return_value = False
            result = agent.command("predict")
            self.assertEqual(result["status"], "predicted")
            self.assertFalse(agent.refused)
            self.desktop.act.assert_not_called()
