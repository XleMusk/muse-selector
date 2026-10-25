import unittest
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


if __name__ == "__main__":
    unittest.main()
