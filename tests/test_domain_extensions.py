import unittest

from muse_selector.category_registry import get_category_schema
from muse_selector.contracts import Evidence, Listing, ListingInstance
from muse_selector.query_parser import parse_query
from muse_selector.source_capabilities import source_capability_registry
from muse_selector.source_normalizer import normalize_source_row


class DomainExtensionTests(unittest.TestCase):
    def test_first_phase_category_registry_covers_phone_laptop_and_gpu(self):
        for category_id, required_attribute in (
            ("smartphone", "battery_health_pct"),
            ("laptop", "ram_gb"),
            ("gpu", "vram_gb"),
        ):
            schema = get_category_schema(category_id)
            self.assertEqual(schema.category_id, category_id)
            self.assertIsNotNone(schema.attribute(required_attribute))

    def test_parser_retains_product_type_and_clarification_state(self):
        spec = parse_query("香港二手 RTX 4070 显卡")
        self.assertEqual(spec.product_type, "gpu")
        self.assertIn("budget_max", spec.clarification_fields)
        self.assertLess(spec.parse_confidence, 1.0)

    def test_evidence_keeps_extraction_and_normalization_metadata(self):
        evidence = Evidence(
            "ev1",
            "ebay.browse.hk.v1",
            "https://www.ebay.com.hk/itm/1",
            "vram_gb",
            12,
            extraction_method="source_json",
            raw_field="localizedAspects.VRAM",
            normalization_rule="normalize_storage_gb",
        )
        payload = evidence.to_dict()
        self.assertEqual(payload["raw_field"], "localizedAspects.VRAM")
        self.assertEqual(payload["normalization_rule"], "normalize_storage_gb")

    def test_source_normalizer_separates_registered_category_attributes(self):
        listing, evidence, reason = normalize_source_row(
            {
                "listing_id": "gpu-1",
                "source_id": "ebay.browse.hk.v1",
                "title": "RTX 4070 12GB VRAM",
                "url": "https://www.ebay.com.hk/itm/gpu-1",
                "price": {"value": 5000, "currency": "HKD"},
                "availability": "IN_STOCK",
                "condition": "Used",
                "shipping_options": [{"shippingCost": {"value": 0, "currency": "HKD"}}],
                "specs": {"vram_gb": 12, "unregistered_note": "ignore for category"},
            },
            product_type="gpu",
        )
        self.assertIsNone(reason)
        self.assertEqual(evidence, [])
        self.assertEqual(listing.category_attributes, {"vram_gb": 12})
        self.assertNotIn("unregistered_note", listing.category_attributes)

    def test_listing_instance_preserves_v1_listing_and_adds_identity_boundary(self):
        listing = Listing(
            listing_id="laptop-1",
            source_id="ebay.browse.hk.v1",
            title="Laptop",
            url="https://www.ebay.com.hk/itm/laptop-1",
            product_id="model-1",
            specs={"ram_gb": 32},
        )
        instance = ListingInstance.from_listing(listing, category_attributes={"ram_gb": 32})
        self.assertEqual(instance.product_model_id, "model-1")
        self.assertEqual(instance.to_dict()["category_attributes"], {"ram_gb": 32})

    def test_source_capability_registry_exposes_four_access_modes(self):
        capabilities = source_capability_registry()
        self.assertEqual(capabilities["ebay.browse.hk.v1"].access_mode, "official_api")
        self.assertEqual(capabilities["xianyu.partner.v1"].access_mode, "authorized_partner")
        self.assertEqual(capabilities["fixture.local.v1"].access_mode, "local_fixture")
        self.assertTrue(all(item.read_only and not item.write_actions for item in capabilities.values()))


if __name__ == "__main__":
    unittest.main()
