import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.doctor import DEFAULT_QUERY, main, run_doctor


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class DoctorTests(unittest.TestCase):
    def test_fixture_check_reports_healthy_without_network(self):
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": "", "ZHUANZHUAN_MCP_TOKEN": ""}, clear=False):
            report = run_doctor(FIXTURE)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "healthy")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["schema_version"], "muse.doctor.v1")
        self.assertEqual(
            set(report["runtime"]),
            {"package_version", "python_version", "python_implementation", "platform", "executable"},
        )
        self.assertTrue(report["runtime"]["package_version"])
        self.assertEqual(report["credential_state"], {"ebay": "missing", "zhuanzhuan": "missing"})
        fixture_check = next(item for item in report["checks"] if item["name"] == "fixture_pipeline")
        self.assertTrue(fixture_check["ok"])

    def test_missing_fixture_fails_closed(self):
        report = run_doctor(ROOT / "does-not-exist.json")
        self.assertFalse(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "fixture_pipeline")
        self.assertFalse(check["ok"])
        self.assertIn("fixture not found", check["detail"])

    def test_no_fixture_is_a_skipped_local_check(self):
        report = run_doctor()
        self.assertTrue(report["ok"])
        check = next(item for item in report["checks"] if item["name"] == "fixture_pipeline")
        self.assertTrue(check["skipped"])

    def test_cli_returns_json_and_nonzero_for_bad_limit(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["muse-doctor", "--fixture", str(FIXTURE), "--limit", "0"]), contextlib.redirect_stdout(output):
            code = main()
        self.assertEqual(code, 2)
        report = json.loads(output.getvalue())
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "unhealthy")

    def test_version_command_reports_package_version(self):
        with self.assertRaises(SystemExit) as raised:
            with patch.object(sys, "argv", ["muse-doctor", "--version"]):
                main()
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
