import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.doctor import main, run_doctor


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
        self.assertEqual(
            report["ebay_target"],
            {
                "environment": "production",
                "api_host": "api.ebay.com",
                "token_path": "/identity/v1/oauth2/token",
                "credential_env": {
                    "scoped": ["EBAY_PRODUCTION_CLIENT_ID", "EBAY_PRODUCTION_CLIENT_SECRET"],
                    "legacy_fallback": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"],
                },
                "read_only": True,
            },
        )
        fixture_check = next(item for item in report["checks"] if item["name"] == "fixture_pipeline")
        self.assertTrue(fixture_check["ok"])

    def test_environment_override_is_reported_without_network_or_env_mutation(self):
        with patch.dict(os.environ, {"EBAY_ENVIRONMENT": "production"}, clear=False):
            report = run_doctor(FIXTURE, environment="sandbox")
            self.assertEqual(report["ebay_target"]["environment"], "sandbox")
            self.assertEqual(report["ebay_target"]["api_host"], "api.sandbox.ebay.com")
            self.assertEqual(report["ebay_target"]["credential_env"]["scoped"][0], "EBAY_SANDBOX_CLIENT_ID")
            self.assertEqual(os.environ["EBAY_ENVIRONMENT"], "production")

    def test_environment_specific_credentials_drive_selected_state(self):
        with patch.dict(
            os.environ,
            {
                "EBAY_CLIENT_ID": "legacy-id",
                "EBAY_CLIENT_SECRET": "legacy-secret",
                "EBAY_SANDBOX_CLIENT_ID": "sandbox-id",
                "EBAY_SANDBOX_CLIENT_SECRET": "sandbox-secret",
            },
            clear=False,
        ):
            report = run_doctor(environment="sandbox")
        self.assertEqual(report["credential_state"]["ebay"], "present")

    def test_invalid_environment_is_unhealthy(self):
        report = run_doctor(environment="staging")
        self.assertFalse(report["ok"])
        self.assertEqual(report["ebay_target"]["environment"], "invalid")
        check = next(item for item in report["checks"] if item["name"] == "ebay_environment")
        self.assertFalse(check["ok"])

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
