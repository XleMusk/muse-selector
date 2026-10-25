import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.watch import default_watch_id, main


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class WatchTests(unittest.TestCase):
    def test_implicit_watch_id_is_stable_and_fixture_scoped(self):
        query = "香港预算 HKD 7000 以内的迷你主机"
        first = default_watch_id(query, Path("tests/fixtures/ebay_hk_sample.json"))
        second = default_watch_id(query, Path("tests/fixtures/ebay_hk_sample.json"))
        other_fixture = default_watch_id(query, Path("tests/fixtures/other.json"))
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_fixture)
        self.assertRegex(first, r"^watch_[0-9a-f]{16}$")

    def test_cli_lifecycle_actions_use_local_checkpoint_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "watch.sqlite3"

            def invoke(*args):
                output = io.StringIO()
                with patch.object(sys, "argv", ["muse-watch", *args]), contextlib.redirect_stdout(output):
                    code = main()
                return code, json.loads(output.getvalue())

            code, first = invoke(
                "--db", str(db), "--action", "refresh", "--watch-id", "watch_cli",
                "--query", "香港预算 HKD 7000 以内的迷你主机", "--fixture", str(FIXTURE), "--once",
            )
            self.assertEqual(code, 0)
            self.assertTrue(first["changed"])
            code, paused = invoke("--db", str(db), "--action", "pause", "--watch-id", "watch_cli")
            self.assertEqual(code, 0)
            self.assertEqual(paused["watch"]["enabled"], 0)
            code, replayed = invoke("--db", str(db), "--action", "replay", "--watch-id", "watch_cli")
            self.assertEqual(code, 0)
            self.assertTrue(replayed["payload"]["read_only"])
            code, resumed = invoke("--db", str(db), "--action", "resume", "--watch-id", "watch_cli")
            self.assertEqual(code, 0)
            self.assertEqual(resumed["watch"]["enabled"], 1)
            code, updated = invoke(
                "--db", str(db), "--action", "update", "--watch-id", "watch_cli",
                "--query", "香港 RTX 4070 显卡，预算 HKD 9000", "--interval-seconds", "60",
            )
            self.assertEqual(code, 0)
            self.assertEqual(updated["watch"]["interval_seconds"], 60)
            self.assertIsNone(updated["watch"]["last_run_id"])

    def test_cli_update_can_switch_existing_fixture_watch_to_live(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "watch.sqlite3"

            def invoke(*args):
                output = io.StringIO()
                with patch.object(sys, "argv", ["muse-watch", *args]), contextlib.redirect_stdout(output):
                    code = main()
                return code, json.loads(output.getvalue())

            code, created = invoke(
                "--db", str(db), "--action", "refresh", "--watch-id", "watch_live_switch",
                "--query", "香港预算 HKD 7000 以内的迷你主机", "--fixture", str(FIXTURE), "--once",
            )
            self.assertEqual(code, 0)
            self.assertEqual(created["payload"]["status"], "complete")

            code, updated = invoke(
                "--db", str(db), "--action", "update", "--watch-id", "watch_live_switch", "--live",
            )
            self.assertEqual(code, 0)
            self.assertIsNone(updated["watch"]["fixture_path"])
            self.assertIsNone(updated["watch"]["last_run_id"])

    def test_cli_live_switch_is_rejected_for_non_update_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "watch.sqlite3"
            with patch.object(sys, "argv", ["muse-watch", "--db", str(db), "--action", "refresh", "--live"]):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)

    def test_cli_refresh_environment_selects_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "watch.sqlite3"
            output = io.StringIO()
            with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": "", "EBAY_ENVIRONMENT": "production"}, clear=False):
                with patch.object(sys, "argv", [
                    "muse-watch", "--db", str(db), "--action", "refresh", "--watch-id", "watch_sandbox",
                    "--query", "香港 RTX 4070 显卡，预算 HKD 9000", "--environment", "sandbox", "--once",
                ]), contextlib.redirect_stdout(output):
                    code = main()
                self.assertEqual(os.environ["EBAY_ENVIRONMENT"], "production")
            self.assertEqual(code, 2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["payload"]["source_metadata"]["environment"], "sandbox")


if __name__ == "__main__":
    unittest.main()
