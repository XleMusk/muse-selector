import unittest
import json
import tempfile
from pathlib import Path

from muse_selector.release_check import RELEASE_SCHEMA_VERSION, run_release_check


ROOT = Path(__file__).resolve().parents[1]


class ReleaseCheckTests(unittest.TestCase):
    def test_local_readiness_is_complete_but_live_gate_remains_pending(self):
        result = run_release_check(ROOT)
        self.assertEqual(result["schema_version"], RELEASE_SCHEMA_VERSION)
        self.assertTrue(result["ok"])
        self.assertTrue(result["local_ready"])
        self.assertFalse(result["go"])
        self.assertEqual(result["status"], "local_ready_external_gate_pending")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["live_gate"]["credential_state"], "missing")

    def test_valid_smoke_evidence_is_recorded_without_opening_go_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("regression_result", "fault_result", "metrics_result"):
                (root / "examples").mkdir(exist_ok=True)
                (root / "examples" / f"{name}.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            for name in ("README.md", "acceptance_matrix.md", "remaining_execution_plan.md", "release_runbook.md"):
                (root / name).write_text("ready", encoding="utf-8")
            (root / "examples" / "live_smoke_result.json").write_text(json.dumps({
                "schema_version": "muse.selector.v1",
                "ok": True,
                "status": "complete",
                "source": "ebay.browse.hk.v1",
                "read_only": True,
                "source_metadata": {"environment": "sandbox"},
                "source_capability": {
                    "source_id": "ebay.browse.hk.v1",
                    "access_mode": "official_api",
                    "status": "ready",
                    "read_only": True,
                    "listing_search": True,
                },
                "recommended_count": 0,
            }), encoding="utf-8")
            result = run_release_check(root)
        self.assertTrue(result["local_ready"])
        self.assertTrue(result["live_gate"]["real_smoke_recorded"])
        self.assertFalse(result["go"])


if __name__ == "__main__":
    unittest.main()
