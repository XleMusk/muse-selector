import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from muse_selector.smoke import main, summarize


class SmokeTests(unittest.TestCase):
    def test_summary_preserves_bounded_source_page_metadata(self):
        summary = summarize({
            "ok": True,
            "status": "complete",
            "source": "ebay.browse.hk.v1",
            "read_only": True,
            "source_metadata": {
                "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc",
                "next": "https://api.ebay.com/buy/browse/v1/item_summary/search?offset=20",
                "prev": None,
                "total": 42,
                "limit": 20,
                "offset": 0,
                "environment": "sandbox",
                "ignored": "drop me",
            },
            "recommended": [],
            "rejected": [],
            "dropped": [],
        })
        self.assertEqual(summary["source_metadata"]["total"], 42)
        self.assertEqual(summary["source_metadata"]["limit"], 20)
        self.assertEqual(summary["source_metadata"]["environment"], "sandbox")
        self.assertNotIn("ignored", summary["source_metadata"])

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
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": "", "EBAY_ENVIRONMENT": "sandbox"}, clear=False):
            with patch.object(sys, "argv", ["muse-live-smoke", "--query", "香港 RTX 4070 显卡，预算 HKD 9000"]):
                with contextlib.redirect_stdout(output):
                    code = main()
        self.assertEqual(code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["credential_state"], "missing")
        self.assertEqual(payload["source_metadata"]["environment"], "sandbox")
        self.assertNotIn("test-secret-value", output.getvalue())
        self.assertNotIn("test-token-value", output.getvalue())

    def test_partial_credentials_are_reported_without_values(self):
        payload = {
            "ok": False,
            "status": "source_unavailable",
            "source": "ebay.browse.hk.v1",
            "read_only": True,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "message": "eBay live connector disabled: set credentials",
        }
        with patch.dict(os.environ, {"EBAY_CLIENT_ID": "client-id", "EBAY_CLIENT_SECRET": ""}, clear=False):
            summary = summarize(payload)
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertEqual(summary["credential_state"], "partial")
        self.assertNotIn("client-id", serialized)
        self.assertNotIn("client-secret", serialized)


if __name__ == "__main__":
    unittest.main()
