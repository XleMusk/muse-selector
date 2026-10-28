import unittest
from decimal import Decimal
from pathlib import Path

from muse_selector.contracts import (
    Evidence,
    Listing,
    PolicyRecord,
    SearchSpec,
    SourceCapability,
    normalize_source_access_mode,
    normalize_source_status,
)
from muse_selector.filtering import filter_listings
from muse_selector.result_card import build_card


class ContractTests(unittest.TestCase):
    def test_source_registry_keeps_ebay_adapter_read_only_and_aspect_allowed(self):
        registry = Path(__file__).resolve().parents[1] / "data" / "source_registry.yaml"
        text = registry.read_text(encoding="utf-8")
        self.assertIn("source_id: ebay.browse.hk.v1", text)
        self.assertIn("read_only: true", text)
        self.assertIn("writes_enabled: false", text)
        self.assertIn("localizedAspects", text)
        self.assertIn("EBAY_PRODUCTION_CLIENT_ID", text)
        self.assertIn("EBAY_SANDBOX_CLIENT_ID", text)
        self.assertIn("xianyu.partner.v1", text)
        self.assertIn("zhuanzhuan.recommerce.mcp.v1", text)

    def test_source_contracts_normalize_legacy_modes_and_statuses(self):
        self.assertEqual(normalize_source_access_mode("official_partner_api"), "authorized_partner")
        self.assertEqual(normalize_source_access_mode("user_authorized"), "user_link")
        self.assertEqual(normalize_source_status("partner_api_pending"), "credential_pending")
        policy = PolicyRecord(
            source_id="xianyu.partner.v1",
            category="computers_hardware",
            access_mode="licensed_feed",
            authorization_evidence_url="https://open.goofish.com/doc/development/dev/server.html",
            default_policy="link_only",
        )
        self.assertEqual(policy.access_mode, "authorized_partner")
        capability = SourceCapability(
            source_id="zhuanzhuan.recommerce.mcp.v1",
            display_name="转转官方 MCP 回收估价",
            category="computers_hardware",
            access_mode="official_mcp",
            status="partner_api_pending",
        )
        self.assertEqual(capability.to_dict()["access_mode"], "authorized_partner")
        self.assertEqual(capability.to_dict()["status"], "credential_pending")

    def test_search_spec_normalizes_money(self):
        spec = SearchSpec.from_dict({"query": "USB4 laptop", "budget_max": "12000", "required_specs": {"ram_gb": 32}})
        self.assertEqual(spec.budget_max, Decimal("12000.00"))
        self.assertEqual(spec.region, "HK")

    def test_search_spec_rejects_unregistered_sources(self):
        with self.assertRaisesRegex(ValueError, "unsupported source"):
            SearchSpec.from_dict({"query": "laptop", "sources": ["untrusted.example.v1"]})

    def test_search_spec_accepts_cn_cny_domestic_profile(self):
        spec = SearchSpec.from_dict({
            "query": "国内二手显卡",
            "region": "CN",
            "currency": "CNY",
            "sources": ["xianyu.partner.v1", "zhuanzhuan.recommerce.mcp.v1"],
        })
        self.assertEqual(spec.region, "CN")
        self.assertEqual(spec.currency, "CNY")

    def test_listing_accepts_cn_cny_contract(self):
        listing = Listing(
            listing_id="domestic:1",
            source_id="zhuanzhuan.recommerce.mcp.v1",
            title="二手显卡",
            url="https://www.zhuanzhuan.com/item/1",
            region="CN",
            currency="CNY",
            price=3000,
            stock_status="unknown",
            condition="used",
        )
        self.assertEqual(listing.currency, "CNY")

    def test_listing_landed_cost_and_filter(self):
        spec = SearchSpec(query="laptop", budget_max=12000, required_specs={"ram_gb": 32})
        listing = Listing(
            listing_id="ebay:1",
            source_id="ebay_browse",
            title="Test laptop",
            url="https://www.ebay.com.hk/itm/1",
            price=10000,
            shipping_cost=200,
            tax=0,
            stock_status="in_stock",
            condition="new",
            specs={"ram_gb": 32},
        )
        accepted, decisions = filter_listings(spec, [listing])
        self.assertEqual(listing.landed_cost, Decimal("10200.00"))
        self.assertEqual(len(accepted), 1)
        self.assertTrue(decisions[0].accepted)

    def test_missing_required_spec_is_rejected(self):
        spec = SearchSpec(query="laptop", required_specs={"usb4": True})
        listing = Listing(
            listing_id="ebay:2",
            source_id="ebay_browse",
            title="Unknown laptop",
            url="https://www.ebay.com.hk/itm/2",
            price=1000,
            stock_status="in_stock",
            condition="new",
        )
        accepted, decisions = filter_listings(spec, [listing])
        self.assertFalse(accepted)
        self.assertIn("required_spec:usb4", decisions[0].reasons)

    def test_partial_cost_is_not_labeled_complete_landed_cost(self):
        listing = Listing(
            listing_id="ebay:partial-cost",
            source_id="ebay_browse",
            title="Partial cost",
            url="https://www.ebay.com.hk/itm/partial-cost",
            price=100,
            shipping_cost=20,
            tax=None,
            stock_status="in_stock",
            condition="new",
        )
        self.assertEqual(listing.landed_cost, Decimal("120.00"))
        self.assertEqual(listing.cost_status, "partial")
        self.assertEqual(listing.cost_basis, "item_price_plus_shipping")
        card = build_card(listing, [])
        self.assertEqual(card.cost_status, "partial")
        self.assertIsNone(card.tax)

    def test_evidence_and_policy_require_http_source(self):
        evidence = Evidence("ev1", "ebay_browse", "https://www.ebay.com.hk/itm/1", "price", "10")
        self.assertEqual(evidence.status, "confirmed")
        policy = PolicyRecord(
            source_id="ebay_browse",
            category="computers_hardware",
            access_mode="official_api",
            authorization_evidence_url="https://developer.ebay.com/api-docs/buy/browse/overview.html",
            allowed_fields=("title", "price"),
        )
        self.assertEqual(policy.default_policy, "allow_read_only")


if __name__ == "__main__":
    unittest.main()

