"""Pin complete requests captured from the pre-refactor code on a real native window."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from open_computer_use.model import choose


class RequestContracts(unittest.TestCase):
    def test_refactor_preserves_full_requests_including_history(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/decision_requests.json").read_text())
        environment = {
            "DECISION_BASE_URL": "http://127.0.0.1:18882/v1", "DECISION_MODEL": "deepseek-flash",
            "DECISION_API_KEY": "local-fixture", "JEV_API_KEY": "",
        }
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]), patch.dict(os.environ, environment, clear=True):
                bodies = []
                def capture(url, key, body):
                    bodies.append(body)
                    return {"choices": [{"message": {"content": '{"operation":"DONE","risk":0,"confidence":1}'}}],
                            "usage": {}}
                with patch("open_computer_use.model.post_json", side_effect=capture):
                    choose(fixture["pages"][case["page"]], case["goal"], case["history"],
                           pointer=case["pointer"], refused=[tuple(pair) for pair in case["refused"]])
                self.assertEqual(len(bodies), 1)
                digest = hashlib.sha256(json.dumps(bodies[0], ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
                self.assertEqual(digest, case["request_sha256"], "Model input changed in " + case["name"])
