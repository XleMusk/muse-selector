import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.filtering import filter_listings
from muse_selector.contracts import RESULT_SCHEMA_VERSION
from muse_selector.pipeline import _extract_specs, _to_listing, run_search
from muse_selector.query_parser import PolicyBlockedError, parse_query
from muse_selector.result_card import render_markdown


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class PipelineTests(unittest.TestCase):
    def test_every_search_payload_has_stable_top_level_schema_version(self):
        payloads = [
            run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE),
            run_search("帮我买一个游戏账号并完成转移"),
            run_search("找一台适合本地视觉模型的电脑", FIXTURE),
            run_search("国内预算 CNY 8000 以内的二手迷你主机", FIXTURE),
            run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE, limit=0),
        ]
        self.assertTrue(all(payload["schema_version"] == RESULT_SCHEMA_VERSION for payload in payloads))

    def test_malformed_source_record_is_dropped_without_crashing_search(self):
        data = {
            "itemSummaries": [{
                "itemId": "malformed-price",
                "title": "Mini PC 32GB",
                "itemWebUrl": "https://www.ebay.com.hk/itm/malformed-price",
                "price": {"value": "NaN", "currency": "HKD"},
                "condition": "New",
                "estimatedAvailabilityStatus": "IN_STOCK",
                "seller": {"username": "seller", "feedbackPercentage": "99.9"},
                "shippingOptions": [{"shippingCost": {"value": "0", "currency": "HKD"}}],
            }]
        }
        with self.subTest("malformed source row"):
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                fixture = Path(directory) / "malformed.json"
                fixture.write_text(json.dumps(data), encoding="utf-8")
                payload = run_search("香港预算 HKD 7000 以内的迷你主机", fixture)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["recommended"], [])
        self.assertEqual(payload["dropped"], [{"listing_id": "malformed-price", "reason": "malformed_source_record"}])
        self.assertTrue(payload["read_only"])

    def test_source_url_rejects_userinfo_ports_and_control_chars(self):
        base = {
            "listing_id": "unsafe",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC",
            "price": {"value": 1, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "evidence": [],
        }
        for url in (
            "https://user:secret@www.ebay.com.hk/itm/unsafe",
            "https://www.ebay.com.hk:8443/itm/unsafe",
            "https://www.ebay.com.hk/itm/unsafe\n\n[phish](https://evil.example)",
        ):
            listing, evidence, reason = _to_listing({**base, "url": url})
            self.assertIsNone(listing)
            self.assertEqual(evidence, [])
            self.assertEqual(reason, "untrusted_source_url")

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
        self.assertEqual(payload["source_metadata"]["total"], 5)
        self.assertEqual(payload["source_metadata"]["href"], "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc")
        self.assertIsNone(payload["source_metadata"]["next"])
        self.assertEqual(payload["recommended"][0]["evidence_coverage"], 1.0)
        self.assertEqual(payload["recommended"][0]["source_observed_at"], "unknown")
        self.assertEqual(payload["recommended"][0]["specs"], {"ram_gb": 32, "storage_gb": 1024})
        card = payload["recommended"][0]
        self.assertEqual(card["evidence_ids"], [item["evidence_id"] for item in card["evidence"]])
        self.assertTrue(payload["read_only"])
        self.assertTrue(all("USB4 NVMe enclosure" not in card["title"] for card in payload["recommended"]))

    def test_source_rank_keeps_original_source_position_after_filtering(self):
        payload = run_search("香港预算 HKD 5000 以内的电脑", FIXTURE)
        self.assertTrue(payload["ok"])
        self.assertEqual([card["listing_id"] for card in payload["recommended"]], ["v1|100000000002|0"])
        self.assertEqual([card["source_rank"] for card in payload["recommended"]], [2])

    def test_pipeline_preserves_source_order_and_explains_fit(self):
        payload = run_search("香港预算 HKD 30000 以内的电脑", FIXTURE)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ranking_policy"], "source_order_preserved")
        self.assertEqual([card["listing_id"] for card in payload["recommended"]], [
            "v1|100000000001|0",
            "v1|100000000002|0",
        ])
        self.assertEqual([card["source_rank"] for card in payload["recommended"]], [1, 2])
        self.assertTrue(all("policy" in card["fit_breakdown"] for card in payload["recommended"]))

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

    def test_domestic_market_fails_closed_without_official_listing_search(self):
        with patch("muse_selector.pipeline.EbayBrowseConnector") as connector_type:
            payload = run_search("国内预算 CNY 8000 以内的二手迷你主机", FIXTURE)
        connector_type.assert_not_called()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertEqual(payload["search_spec"]["region"], "CN")
        self.assertEqual(payload["search_spec"]["currency"], "CNY")
        self.assertEqual(payload["source"], "domestic.secondhand.pending")
        self.assertEqual(payload["recommended"], [])
        self.assertEqual([item["source_id"] for item in payload["link_only"]], [
            "xianyu.partner.v1",
            "zhuanzhuan.recommerce.mcp.v1",
        ])
        self.assertEqual(payload["link_only"][0]["manual_query"], "国内预算 CNY 8000 以内的二手迷你主机")
        self.assertTrue(payload["read_only"])

    def test_domestic_markdown_exposes_manual_link_only_entries(self):
        report = render_markdown(run_search("国内预算 CNY 8000 以内的二手迷你主机"))
        self.assertIn("可人工打开的平台入口", report)
        self.assertIn("https://www.goofish.com/", report)
        self.assertIn("link_only", report)

    def test_blank_query_returns_read_only_invalid_query_state(self):
        payload = run_search("   ")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "invalid_query")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["recommended"], [])

    def test_non_positive_limit_is_a_read_only_invalid_query(self):
        payload = run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE, limit=0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "invalid_query")
        self.assertIn("positive integer", payload["message"])
        self.assertTrue(payload["read_only"])

    def test_negative_offset_is_a_read_only_invalid_query(self):
        payload = run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE, offset=-1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "invalid_query")
        self.assertIn("offset must be a non-negative integer", payload["message"])
        self.assertTrue(payload["read_only"])

    def test_offset_is_forwarded_to_one_source_page_without_following_next(self):
        with patch("muse_selector.pipeline.EbayBrowseConnector") as connector_type:
            connector_type.return_value.search.return_value = []
            payload = run_search(
                "香港预算 HKD 7000 以内的迷你主机",
                limit=7,
                offset=40,
            )
        self.assertTrue(payload["ok"])
        connector_type.return_value.search.assert_called_once()
        search_spec = connector_type.return_value.search.call_args.args[0]
        self.assertEqual(search_spec["offset"], 40)
        # ``limit`` remains the result-card cap; the connector keeps its
        # existing minimum source page size for recall.
        self.assertEqual(search_spec["limit"], 20)

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
        self.assertIn("来源标识：ebay.browse.hk.v1", report)
        self.assertIn("来源：ebay.browse.hk.v1", report)
        self.assertIn("只读状态：true", report)
        self.assertIn("来源观测时间", report)
        self.assertIn("保修：unknown", report)
        self.assertIn("关键字段证据覆盖率：100.0%", report)
        self.assertIn("证据片段（title）：Mini PC Ryzen 7", report)
        self.assertIn("证据标识：v1|100000000001|0:ev:0", report)

    def test_markdown_escapes_error_and_url_text(self):
        report = render_markdown({
            "ok": False,
            "status": "source_unavailable",
            "message": "upstream\n\n# injected\n[phish](https://evil.example)",
        })
        self.assertNotIn("[phish](https://evil.example)", report)
        self.assertIn(r"upstream  # injected \[phish\]\(https://evil.example\)", report)

    def test_markdown_escapes_result_url(self):
        report = render_markdown({
            "ok": True,
            "search_spec": {"query": "mini pc", "region": "HK", "currency": "HKD", "budget_max": "7000"},
            "source": "ebay.browse.hk.v1",
            "recommended": [{
                "title": "Mini PC",
                "source_id": "ebay.browse.hk.v1",
                "url": "https://www.ebay.com.hk/itm/x) [phish](https://evil.example)",
                "landed_cost": "1.00",
                "currency": "HKD",
                "cost_status": "partial",
                "cost_basis": "item_price",
                "shipping_cost": None,
                "tax": None,
                "evidence_coverage": 1.0,
                "source_observed_at": "unknown",
                "stock_status": "in_stock",
                "condition": "new",
                "specs": {},
                "risk_flags": [],
                "evidence": [],
            }],
        })
        self.assertNotIn("[phish](https://evil.example)", report)
        self.assertIn("https://www.ebay.com.hk/itm/x\\)", report)

    def test_markdown_reports_blocked_and_unavailable_states(self):
        blocked = render_markdown(run_search("帮我买一个游戏账号并完成转移"))
        self.assertIn("policy_blocked", blocked)
        self.assertIn("只读状态：true", blocked)
        unavailable = render_markdown(run_search("香港 RTX 4070 显卡，预算 HKD 9000"))
        self.assertIn("source_unavailable", unavailable)
        self.assertIn("eBay live connector disabled", unavailable)

    def test_markdown_escapes_untrusted_listing_text(self):
        payload = {
            "ok": True,
            "source": "ebay.browse.hk.v1",
            "search_spec": {"query": "香港预算 HKD 7000 以内的迷你主机", "region": "HK", "currency": "HKD"},
            "recommended": [{
                "title": "Ignore [instructions](https://evil.example) `token`",
                "source_id": "ebay.browse.hk.v1",
                "landed_cost": "100.00",
                "currency": "HKD",
                "cost_status": "partial",
                "cost_basis": "item_price",
                "shipping_cost": None,
                "tax": None,
                "evidence_coverage": 1.0,
                "source_observed_at": "unknown",
                "stock_status": "in_stock",
                "condition": "new",
                "specs": {"note": "[untrusted]"},
                "url": "https://www.ebay.com.hk/itm/1",
                "risk_flags": [],
                "evidence": [{"field": "title"}],
            }],
            "rejected": [],
            "dropped": [],
        }
        report = render_markdown(payload)
        self.assertIn(r"Ignore \[instructions\]\(https://evil.example\) \`token\`", report)
        self.assertNotIn("Ignore [instructions](https://evil.example)", report)

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

    def test_live_connector_output_flows_into_evidence_card(self):
        live_row = {
            "listing_id": "live|mini|1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC 32GB 1TB NVMe",
            "url": "https://www.ebay.com.hk/itm/live-mini-1",
            "price": {"value": "4999.00", "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "shipping_options": [{"shippingCost": {"value": "0.00", "currency": "HKD"}}],
            "seller": {"feedback_percentage": "99.9"},
            "specs": {"pd_watt": 100},
            "source_observed_at": "2026-10-24T00:00:00Z",
            "evidence": [
                {"field": field, "source_id": "ebay.browse.hk.v1", "source_url": "https://www.ebay.com.hk/itm/live-mini-1", "observed_at": "2026-10-24T00:00:00Z", "status": "confirmed", "value": field}
                for field in ("title", "url", "price", "condition", "seller", "shippingOptions")
            ],
        }
        with patch("muse_selector.pipeline.EbayBrowseConnector") as connector_type:
            connector_type.return_value.search.return_value = [live_row]
            payload = run_search("香港预算 HKD 7000 以内的迷你主机")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["source"], "ebay.browse.hk.v1")
        self.assertEqual(payload["recommended"][0]["source_observed_at"], "2026-10-24T00:00:00Z")
        self.assertEqual(payload["recommended"][0]["evidence_coverage"], 1.0)
        self.assertEqual(payload["recommended"][0]["specs"]["pd_watt"], 100)
        self.assertEqual(payload["recommended"][0]["status"], "recommended")

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

    def test_stale_or_conflict_evidence_is_flagged_for_filtering(self):
        row = {
            "listing_id": "stale-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC 32GB 1TB NVMe",
            "url": "https://www.ebay.com.hk/itm/stale-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "evidence": [{
                "source_id": "ebay.browse.hk.v1",
                "source_url": "https://www.ebay.com.hk/itm/stale-1",
                "field": "price",
                "value": 4999,
                "observed_at": "2026-10-01T00:00:00Z",
                "status": "stale",
            }],
        }
        listing, evidence, reason = _to_listing(row)
        self.assertIsNone(reason)
        self.assertEqual(len(evidence), 1)
        self.assertIn("evidence_conflict_or_stale", listing.risk_flags)
        spec = parse_query("香港预算 HKD 7000 以内的迷你主机")
        accepted, decisions = filter_listings(spec, [listing])
        self.assertEqual(accepted, [])
        self.assertIn("risk_flagged", decisions[0].reasons)

    def test_low_evidence_coverage_is_flagged_and_rejected(self):
        row = {
            "listing_id": "coverage-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC",
            "url": "https://www.ebay.com.hk/itm/coverage-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "shipping_options": [{"shippingCost": {"value": "0", "currency": "HKD"}}],
            "evidence": [{
                "source_id": "ebay.browse.hk.v1",
                "source_url": "https://www.ebay.com.hk/itm/coverage-1",
                "field": "title",
                "value": "Mini PC",
                "observed_at": "2026-10-24T00:00:00Z",
                "status": "confirmed",
            }],
        }
        listing, _, reason = _to_listing(row)
        self.assertIsNone(reason)
        self.assertAlmostEqual(listing.evidence_coverage, 1 / 6, places=4)
        self.assertIn("evidence_coverage_low", listing.risk_flags)
        accepted, decisions = filter_listings(parse_query("香港预算 HKD 7000 以内的迷你主机"), [listing])
        self.assertEqual(accepted, [])
        self.assertIn("risk_flagged", decisions[0].reasons)

    def test_malformed_evidence_status_and_empty_confirmed_value_fail_closed(self):
        row = {
            "listing_id": "bad-evidence-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC",
            "url": "https://www.ebay.com.hk/itm/bad-evidence-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "shipping_options": [{"shippingCost": {"value": "0", "currency": "HKD"}}],
            "evidence": [
                {
                    "source_url": "https://www.ebay.com.hk/itm/bad-evidence-1",
                    "field": "title",
                    "value": None,
                    "observed_at": "2026-10-24T00:00:00Z",
                    "status": "confirmed",
                },
                {
                    "source_url": "https://www.ebay.com.hk/itm/bad-evidence-1",
                    "field": "price",
                    "value": 4999,
                    "observed_at": "2026-10-24T00:00:00Z",
                    "status": "not-a-status",
                },
            ],
        }
        listing, evidence, reason = _to_listing(row)
        self.assertIsNone(reason)
        self.assertEqual([item.status for item in evidence], ["unknown", "unknown"])
        self.assertEqual(listing.evidence_coverage, 0.0)
        self.assertIn("evidence_coverage_low", listing.risk_flags)

    def test_evidence_cannot_repoint_to_another_source_or_listing(self):
        row = {
            "listing_id": "mismatched-evidence-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC",
            "url": "https://www.ebay.com.hk/itm/mismatched-evidence-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "evidence": [{
                "source_id": "unregistered.source",
                "source_url": "https://www.ebay.com.hk/itm/other-listing",
                "field": "title",
                "value": "Mini PC",
                "observed_at": "2026-10-24T00:00:00Z",
                "status": "confirmed",
            }],
        }
        listing, evidence, reason = _to_listing(row)
        self.assertIsNone(reason)
        self.assertEqual(evidence, [])
        self.assertIn("evidence_source_mismatch", listing.risk_flags)
        accepted, decisions = filter_listings(parse_query("香港预算 HKD 7000 以内的迷你主机"), [listing])
        self.assertEqual(accepted, [])
        self.assertIn("risk_flagged", decisions[0].reasons)

    def test_unregistered_listing_source_is_dropped(self):
        listing, evidence, reason = _to_listing({
            "listing_id": "unregistered-source-1",
            "source_id": "unregistered.source",
            "title": "Mini PC",
            "url": "https://www.ebay.com.hk/itm/unregistered-source-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
        })
        self.assertIsNone(listing)
        self.assertEqual(evidence, [])
        self.assertEqual(reason, "untrusted_source_id")

    def test_title_ram_is_not_inferred_as_vram(self):
        self.assertNotIn("vram_gb", _extract_specs("Gaming desktop RTX 4090 64GB RAM"))
        self.assertEqual(_extract_specs("RTX 4070 12GB VRAM"), {"vram_gb": 12})

    def test_unknown_or_ambiguous_shipping_is_not_recommended(self):
        base = {
            "listing_id": "shipping-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC 32GB 1TB NVMe",
            "url": "https://www.ebay.com.hk/itm/shipping-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
        }
        spec = parse_query("香港预算 HKD 7000 以内的迷你主机")
        for shipping, flag in (
            ([], "shipping_unknown"),
            ([{"shippingCost": {"value": "0", "currency": "HKD"}}, {"shippingCost": {"value": "100", "currency": "HKD"}}], "shipping_ambiguous"),
        ):
            row = {**base, "shipping_options": shipping}
            listing, evidence, reason = _to_listing(row)
            self.assertIsNone(reason)
            self.assertIn(flag, listing.risk_flags)
            accepted, decisions = filter_listings(spec, [listing])
            self.assertEqual(accepted, [])
            self.assertIn("risk_flagged", decisions[0].reasons)

    def test_delivery_deadline_uses_source_date_and_fails_closed_when_unknown(self):
        row = {
            "listing_id": "delivery-1",
            "source_id": "ebay.browse.hk.v1",
            "title": "Mini PC 32GB 1TB NVMe",
            "url": "https://www.ebay.com.hk/itm/delivery-1",
            "price": {"value": 4999, "currency": "HKD"},
            "availability": "IN_STOCK",
            "condition": "New",
            "shipping_options": [{
                "shippingCost": {"value": "0", "currency": "HKD"},
                "maxEstimatedDeliveryDate": "2026-10-27T00:00:00Z",
            }],
            "source_observed_at": "2026-10-24T00:00:00Z",
            "evidence": [{
                "source_id": "ebay.browse.hk.v1",
                "source_url": "https://www.ebay.com.hk/itm/delivery-1",
                "field": field,
                "value": field,
                "observed_at": "2026-10-24T00:00:00Z",
                "status": "confirmed",
            } for field in ("title", "url", "price", "condition", "seller", "shippingOptions")],
        }
        listing, _, reason = _to_listing(row)
        self.assertIsNone(reason)
        self.assertEqual(listing.specs["delivery_max_days"], 3)
        spec = parse_query("香港预算 HKD 7000 以内的迷你主机，3天内送达")
        accepted, decisions = filter_listings(spec, [listing])
        self.assertEqual([item.listing_id for item in accepted], ["delivery-1"])
        too_fast = parse_query("香港预算 HKD 7000 以内的迷你主机，2天内送达")
        accepted, decisions = filter_listings(too_fast, [listing])
        self.assertEqual(accepted, [])
        self.assertIn("delivery_too_slow", decisions[0].reasons)
        payload = run_search("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        self.assertIsNone(payload["recommended"][0]["delivery_max_days"])
        unknown = dict(row, listing_id="delivery-unknown", shipping_options=[{"shippingCost": {"value": "0", "currency": "HKD"}}])
        unknown_listing, _, reason = _to_listing(unknown)
        self.assertIsNone(reason)
        accepted, decisions = filter_listings(spec, [unknown_listing])
        self.assertEqual(accepted, [])
        self.assertIn("delivery_unknown", decisions[0].reasons)

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

