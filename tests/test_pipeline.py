import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.pipeline import _to_listing, run_search
from muse_selector.query_parser import PolicyBlockedError, parse_query
from muse_selector.result_card import render_markdown


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class PipelineTests(unittest.TestCase):
    def test_query_parser_extracts_explicit_hk_constraints(self):
        spec = parse_query("香港预算 HKD 12000 以内，32GB 内存、1TB SSD、支持 USB4 的轻薄本")
        self.assertEqual(spec.region, "HK")
        self.assertEqual(str(spec.budget_max), "12000.00")
        self.assertEqual(spec.required_specs["ram_gb"], 32)
        self.assertEqual(spec.required_specs["storage_gb"], 1024)
        self.assertTrue(spec.required_specs["usb4"])

    def test_pipeline_produces_evidence_cards_and_drops_missing_url(self):
        payload = run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["recommended"])
        self.assertTrue(payload["dropped"])
        self.assertTrue(payload["recommended"][0]["url"].startswith("https://www.ebay.com.hk/"))
        self.assertTrue(payload["recommended"][0]["evidence"])
        self.assertEqual(payload["recommended"][0]["source_observed_at"], "unknown")
        self.assertEqual(payload["recommended"][0]["specs"], {"ram_gb": 32, "storage_gb": 1024})
        self.assertTrue(payload["read_only"])
        self.assertTrue(all("USB4 NVMe enclosure" not in card["title"] for card in payload["recommended"]))

    def test_policy_blocked_query_does_not_call_connector(self):
        with self.assertRaises(PolicyBlockedError):
            parse_query("帮我买一个游戏账号并完成转移")

    def test_policy_blocked_search_returns_read_only_state(self):
        payload = run_search("帮我买一个游戏账号并完成转移")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "policy_blocked")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["source"], "policy.guard")

    def test_missing_budget_returns_clarification_without_source_call(self):
        payload = run_search("找一台适合本地视觉模型的电脑", FIXTURE)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(payload["ask"], ["location", "max_total_hkd"])
        self.assertTrue(payload["read_only"])

    def test_explicit_unbounded_budget_can_search_fixture(self):
        payload = run_search("香港 USB4 扩展坞，双 4K、100W PD，价格不限", FIXTURE)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "complete")
        self.assertNotIn("ask", payload)

    def test_markdown_card_is_human_readable(self):
        payload = run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        report = render_markdown(payload)
        self.assertIn("结果卡", report)
        self.assertIn("打开原平台", report)
        self.assertIn("来源观测时间", report)

    def test_markdown_reports_blocked_and_unavailable_states(self):
        blocked = render_markdown(run_search("帮我买一个游戏账号并完成转移"))
        self.assertIn("policy_blocked", blocked)
        self.assertIn("只读状态：true", blocked)
        unavailable = render_markdown(run_search("香港 RTX 4070 显卡，预算 HKD 9000"))
        self.assertIn("source_unavailable", unavailable)
        self.assertIn("eBay live connector disabled", unavailable)

    def test_live_mode_without_credentials_fails_closed(self):
        payload = run_search("香港 RTX 4070 显卡，预算 HKD 9000")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertTrue(payload["read_only"])

    def test_invalid_connector_environment_fails_closed(self):
        with patch.dict(os.environ, {"EBAY_TIMEOUT_SECONDS": "invalid"}, clear=False):
            payload = run_search("香港 RTX 4070 显卡，预算 HKD 9000")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertTrue(payload["read_only"])

    def test_untrusted_listing_url_is_dropped_before_result_card(self):
        listing, evidence, reason = _to_listing({
            "listing_id": "evil-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC",
            "url": "http://169.254.169.254/latest/meta-data/",
            "price": {"value": 1, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
        })
        self.assertIsNone(listing)
        self.assertEqual(evidence, [])
        self.assertEqual(reason, "untrusted_source_url")

    def test_malformed_listing_required_fields_are_dropped_without_traceback(self):
        for field, reason in (("listing_id", "missing_listing_id"), ("title", "missing_title")):
            row = {
                "listing_id": "bad-1",
                "source_id": "ebay.browse.hk.v1",
                "title": "Mini PC",
                "url": "https://www.ebay.com.hk/itm/bad-1",
                "price": {"value": 1, "currency": "HKD"},
                "availability": "IN_STOCK",
                "condition": "New",
            }
            row[field] = None
            listing, evidence, actual = _to_listing(row)
            self.assertIsNone(listing)
            self.assertEqual(evidence, [])
            self.assertEqual(actual, reason)


if __name__ == "__main__":
    unittest.main()

