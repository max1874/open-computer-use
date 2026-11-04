"""CI-only contracts: a correct result cannot hide focus loss or missing cleanup."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from evals.run import Budget, accepted


class AcceptanceContracts(unittest.TestCase):
    def test_every_required_reading_is_needed_even_when_the_model_says_done(self):
        good = dict(before=False, after=True, status="done", monitor_complete=True,
                    cleaned=True, focus=[], error=None)
        self.assertTrue(accepted(good))
        for change in (dict(before=True), dict(before=None), dict(after=False), dict(after=None),
                       dict(status="blocked"), dict(status="decision_limit"), dict(monitor_complete=False),
                       dict(cleaned=False), dict(focus=None), dict(focus=[{"event": "activated", "phase": "cleanup"}]),
                       dict(error="ownership was lost")):
            with self.subTest(change=change):
                self.assertFalse(accepted({**good, **change}))

    def test_a_lost_reply_is_charged_before_the_request_and_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            client = Mock()
            def lost(*args, **kwargs):
                self.assertEqual(json.loads(path.read_text())["calls"], 1)
                raise RuntimeError("reply lost")
            client.post.side_effect = lost
            with self.assertRaisesRegex(RuntimeError, "reply lost"):
                Budget(client, path, 1).post("example")
            with self.assertRaisesRegex(RuntimeError, "exhausted"):
                Budget(client, path, 1).post("example")
            self.assertEqual(client.post.call_count, 1)
