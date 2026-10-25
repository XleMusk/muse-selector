import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.cli import main


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with patch.object(sys, "argv", ["muse-selector", *args]), contextlib.redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_fixture_markdown_command_succeeds(self):
        code, output = self._run(
            "--query", "香港预算 HKD 7000 以内的迷你主机",
            "--fixture", str(FIXTURE),
            "--format", "markdown",
        )
        self.assertEqual(code, 0)
        self.assertIn("Mini PC Ryzen 7", output)
        self.assertIn("来源观测时间", output)

    def test_version_command_reports_package_version(self):
        with self.assertRaises(SystemExit) as raised:
            self._run("--version")
        self.assertEqual(raised.exception.code, 0)

    def test_fixture_comparison_artifact_preserves_source_order(self):
        code, output = self._run(
            "--query", "香港预算 HKD 30000 以内的电脑",
            "--fixture", str(FIXTURE),
            "--format", "comparison",
        )
        self.assertEqual(code, 0)
        self.assertIn("# Muse Selector 比较表", output)
        self.assertIn("| 来源顺序 | 商品 |", output)
        self.assertLess(output.index("Mini PC Ryzen 7"), output.index("USB4 NVMe enclosure"))

    def test_policy_blocked_command_is_read_only_error(self):
        code, output = self._run("--query", "帮我买一个游戏账号并完成转移", "--format", "markdown")
        self.assertEqual(code, 2)
        self.assertIn("policy_blocked", output)
        self.assertIn("只读状态：true", output)

    def test_live_command_without_credentials_is_fail_closed(self):
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""}, clear=False):
            code, output = self._run("--query", "香港 RTX 4070 显卡，预算 HKD 9000", "--format", "json")
        self.assertEqual(code, 2)
        self.assertIn('"status": "source_unavailable"', output)
        self.assertIn('"read_only": true', output)

    def test_environment_argument_selects_sandbox_without_persisting_env(self):
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": "", "EBAY_ENVIRONMENT": "production"}, clear=False):
            code, output = self._run(
                "--environment", "sandbox",
                "--query", "香港 RTX 4070 显卡，预算 HKD 9000",
                "--format", "json",
            )
            self.assertEqual(os.environ["EBAY_ENVIRONMENT"], "production")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["source_metadata"]["environment"], "sandbox")


if __name__ == "__main__":
    unittest.main()
