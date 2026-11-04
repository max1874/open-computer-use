"""CI-only contracts: a correct result cannot hide focus loss or missing cleanup."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from evals.run import Budget, accepted
from evals.tasks import TASKS


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

    def test_settings_reads_the_detail_heading_not_the_selected_sidebar_label(self):
        page = {"window": "", "elements": [
            {"role": "AXScrollArea", "path": "0.sidebar", "label": "Sidebar"},
            {"role": "AXStaticText", "path": "0.sidebar.0", "value": "Keyboard", "selected": True},
            {"role": "AXScrollArea", "path": "0.detail", "label": "General"},
            {"role": "AXStaticText", "path": "0.detail.0", "value": "General"}]}
        task = next(t for t in TASKS if t.id == "settings-keyboard")
        desktop = Mock(); desktop.observe.return_value = page
        with patch("evals.tasks.Desktop", return_value=desktop):
            self.assertEqual(task.read(123), (False, "General"))
            page["elements"][-1]["value"] = "Keyboard"
            self.assertEqual(task.read(123), (True, "Keyboard"))
            page["elements"][-1]["value"] = "Adjust keyboard brightness in low light"
            self.assertEqual(task.read(123), (None, "Adjust keyboard brightness in low light"))
            page["window"] = "Keyboard"
            self.assertEqual(task.read(123), (True, "Keyboard"))
            page["window"] = ""
            page["elements"].pop(0)
            self.assertEqual(task.read(123), (None, None))
