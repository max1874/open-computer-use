"""CLI delivery facts are independent of the optional model loop."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from open_computer_use import cli
from open_computer_use.desktop import BridgeError, Desktop, UnknownOutcome, disposition


class CLIContracts(unittest.TestCase):
    def test_core_imports_do_not_load_optional_dependencies(self):
        # No site-packages: a CLI import must not need the installed Agent extra.
        root = str(Path(__file__).resolve().parents[1])
        subprocess.run([sys.executable, "-S", "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import open_computer_use.cli; "
                        "assert not {'httpx', 'open_computer_use.agent', 'open_computer_use.demo'} & sys.modules.keys()",
                        root], check=True)

    def test_focus_violation_is_terminal_but_does_not_erase_delivery(self):
        for failed_reply in (False, True):
            with self.subTest(error=failed_reply):
                desktop = Mock()
                desktop.observe.return_value = {"fingerprint": "observation"}
                desktop.act.return_value = {"disposition": disposition("delivered_unverified"), "took_focus": True}
                if failed_reply:
                    error = UnknownOutcome("post-action reply unavailable")
                    error.took_focus = True
                    desktop.act.side_effect = error
                options = SimpleNamespace(app="Scratch", fingerprint="observation", operation="PRESS", text=None)
                output = io.StringIO()
                with patch("open_computer_use.cli.Desktop", return_value=desktop), patch(
                    "open_computer_use.cli.resolve", return_value={"label": "Continue"}
                ), patch("open_computer_use.cli.show"), contextlib.redirect_stdout(output):
                    code = cli.act(options)
                result = json.loads(output.getvalue())
                self.assertEqual(code, 3)
                self.assertEqual(result["outcome"], "focus_violation")
                self.assertEqual(result["delivery"], "delivery_uncertain" if failed_reply else "delivered_unverified")
                desktop.act.assert_called_once()
                desktop.close.assert_called_once()


class MachineWideContracts(unittest.TestCase):
    """System Settings changes the whole Mac: only navigation runs unless the caller allows more."""

    def desktop(self, **options):
        bridge = Mock()
        bridge.call.side_effect = lambda method, **_: (
            {"accessibility": True, "locked": False} if method == "status"
            else {"disposition": disposition("delivered_unverified")})
        with patch("open_computer_use.desktop.Bridge", return_value=bridge):
            return Desktop("System Settings", **options), bridge

    def acts(self, bridge):
        return [c for c in bridge.call.call_args_list if c.args[0] == "act"]

    def test_settings_change_is_refused_before_dispatch(self):
        desktop, bridge = self.desktop()
        page = {"app": "System Settings", "bundle": "com.apple.systempreferences"}
        with self.assertRaises(BridgeError) as refused:
            desktop.act({"operation": "PRESS", "path": "0.1"}, page)
        self.assertEqual(refused.exception.disposition["delivery"], "not_delivered")
        self.assertEqual(self.acts(bridge), [])
        with patch("open_computer_use.desktop.time.sleep"):
            desktop.act({"operation": "CLICK", "path": "0.2"}, page)
        self.assertEqual(len(self.acts(bridge)), 1)

    def test_machine_wide_allows_the_change(self):
        desktop, bridge = self.desktop(machine_wide=True)
        with patch("open_computer_use.desktop.time.sleep"):
            desktop.act({"operation": "PRESS", "path": "0.1"},
                        {"app": "System Settings", "bundle": "com.apple.systempreferences"})
        self.assertEqual(len(self.acts(bridge)), 1)

