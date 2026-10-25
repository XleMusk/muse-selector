import unittest

from muse_selector.compatibility import COMPATIBILITY_SCHEMA_VERSION, build_compatibility_matrix
from muse_selector.result_card import render_markdown


class CompatibilityTests(unittest.TestCase):
    def test_matrix_requires_evidence_and_preserves_source_references(self):
        matrix = build_compatibility_matrix({
            "search_spec": {"required_specs": {"ram_gb": 32}},
            "recommended": [{
                "listing_id": "item-1",
                "source_id": "ebay.browse.hk.v1",
                "url": "https://www.ebay.com.hk/itm/item-1",
                "specs": {"ram_gb": 32},
                "evidence": [{
                    "evidence_id": "item-1:specs",
                    "field": "specs",
                    "value": {"ram_gb": 32},
                    "status": "confirmed",
                    "source_url": "https://www.ebay.com.hk/itm/item-1",
                }],
            }],
        })
        self.assertEqual(matrix["schema_version"], COMPATIBILITY_SCHEMA_VERSION)
        requirement = matrix["items"][0]["requirements"][0]
        self.assertEqual(requirement["status"], "confirmed")
        self.assertEqual(requirement["evidence_ids"], ["item-1:specs"])
        self.assertEqual(requirement["source_urls"], ["https://www.ebay.com.hk/itm/item-1"])

    def test_matrix_keeps_missing_evidence_unknown_and_markdown_visible(self):
        payload = {
            "ok": True,
            "search_spec": {"query": "ram", "region": "HK", "currency": "HKD", "required_specs": {"ram_gb": 32}},
            "recommended": [{
                "listing_id": "item-unknown",
                "title": "Laptop",
                "source_id": "ebay.browse.hk.v1",
                "url": "https://www.ebay.com.hk/itm/item-unknown",
                "landed_cost": "5000.00",
                "currency": "HKD",
                "cost_status": "complete",
                "cost_basis": "item_price_plus_shipping_plus_tax",
                "shipping_cost": "0.00",
                "tax": "0.00",
                "evidence_coverage": 1.0,
                "source_observed_at": "2026-10-24T10:00:00Z",
                "stock_status": "in_stock",
                "condition": "new",
                "risk_flags": [],
                "specs": {"ram_gb": 16},
                "evidence": [],
            }],
            "compatibility_matrix": build_compatibility_matrix({
                "search_spec": {"required_specs": {"ram_gb": 32}},
                "recommended": [{
                    "listing_id": "item-unknown",
                    "url": "https://www.ebay.com.hk/itm/item-unknown",
                    "specs": {"ram_gb": 16},
                    "evidence": [],
                }],
            }),
            "rejected": [],
            "dropped": [],
        }
        self.assertEqual(payload["compatibility_matrix"]["items"][0]["overall_status"], "unknown")
        report = render_markdown(payload)
        self.assertIn("硬件兼容性矩阵", report)
        self.assertIn("unknown", report)


if __name__ == "__main__":
    unittest.main()
