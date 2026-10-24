import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from muse_selector.smoke import main, summarize


class SmokeTests(unittest.TestCase):
    def test_summary_contains_no_credentials(self):
        summary = summarize({
            "ok": True,
            "status": "complete",
            "source": "ebay.browse.hk.v1",
            "read_only": True,
            "recommended": [{"evidence": [{"observed_at": "2026-10-24T04:00:00Z"}]}],
            "rejected": [],
            "dropped": [],
        })
        self.assertEqual(summary["observed_at_samples"], ["2026-10-24T04:00:00Z"])
        self.assertIn(summary["credential_state"], {"missing", "partial", "present"})
        self.assertNotIn("client_secret", json.dumps(summary))

    def test_no_credentials_is_source_unavailable(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""}, clear=False):
            with patch.object(sys, "argv", ["muse-live-smoke", "--query", "香港 RTX 4070 显卡，预算 HKD 9000"]):
                with contextlib.redirect_stdout(output):
                    code = main()
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["credential_state"], "missing")
        self.assertNotIn("test-secret-value", output.getvalue())
        self.assertNotIn("test-token-value", output.getvalue())


if __name__ == "__main__":
    unittest.main()
