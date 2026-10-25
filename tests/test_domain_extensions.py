import unittest
from pathlib import Path

from muse_selector.category_registry import get_category_schema
from muse_selector.application import SearchApplication
from muse_selector.compatibility import build_compatibility_matrix
from muse_selector.contracts import CompatibilityCheck, Evidence, FilterRule, Listing, ListingInstance, RankProfile
from muse_selector.filtering import filter_rules_for_spec
from muse_selector.query_parser import parse_query
from muse_selector.source_capabilities import source_capability_registry
from muse_selector.source_normalizer import normalize_source_row
from muse_selector.pipeline import run_search


class DomainExtensionTests(unittest.TestCase):
    def test_search_accepts_a_source_connector_port_without_changing_result_contract(self):
        class FakeConnector:
            source_id = "ebay.browse.hk.v1"
            source_metadata = {"adapter": "fake", "environment": "fixture"}

            def search(self, search_spec):
                self.search_spec = search_spec
                return [
                    {
                        "listing_id": "port-1",
                        "source_id": self.source_id,
                        "title": "Mini PC 32GB 1TB NVMe",
                        "url": "https://www.ebay.com.hk/itm/port-1",
                        "price": {"value": 1000, "currency": "HKD"},
                        "availability": "IN_STOCK",
                        "condition": "New",
                        "shipping_options": [{"shippingCost": {"value": 0, "currency": "HKD"}}],
                        "evidence": [
                            {
                                "source_id": self.source_id,
                                "source_url": "https://www.ebay.com.hk/itm/port-1",
                                "field": field,
                                "value": field,
                                "status": "confirmed",
                            }
                            for field in ("title", "url", "price", "condition", "seller", "shippingOptions")
                        ],
                    }
                ]

        connector = FakeConnector()
        payload = run_search(
            "香港预算 HKD 2000 以内的迷你主机",
            connector=connector,
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_metadata"]["adapter"], "fake")
        self.assertEqual(payload["recommended"][0]["listing_id"], "port-1")
        self.assertEqual(connector.search_spec["offset"], 0)

    def test_application_use_case_uses_the_same_injected_connector(self):
        class FakeConnector:
            source_id = "ebay.browse.hk.v1"
            source_metadata = {"adapter": "application-test"}

            def search(self, search_spec):
                return []

        payload = SearchApplication(FakeConnector()).search("香港预算 HKD 2000 以内的迷你主机")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_metadata"]["adapter"], "application-test")

    def test_search_records_the_versioned_rank_profile(self):
        payload = run_search(
            "香港预算 HKD 7000 以内的迷你主机",
            Path(__file__).resolve().parent / "fixtures" / "ebay_hk_sample.json",
        )
        self.assertEqual(payload["rank_profile_id"], "source_order_preserved.v1")

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

    def test_filter_rules_are_typed_without_changing_required_spec_semantics(self):
        spec = parse_query("香港 RTX 4070 12GB 显存，预算 HKD 9000")
        rules = filter_rules_for_spec(spec)
        self.assertTrue(all(isinstance(rule, FilterRule) for rule in rules))
        self.assertEqual(rules[0].operator, "gte")
        self.assertEqual(rules[0].rule_id, "required_spec:vram_gb")

    def test_rank_profile_and_compatibility_check_are_versioned_domain_objects(self):
        profile = RankProfile("hardware-v1", {"evidence_coverage": 0.4, "availability": 0.2})
        self.assertEqual(profile.to_dict()["profile_id"], "hardware-v1")
        check = CompatibilityCheck(
            field="vram_gb",
            required=12,
            actual=8,
            status="mismatch",
            rule_id="compatibility:vram_gb",
        )
        self.assertEqual(check.to_dict()["status"], "mismatch")

    def test_compatibility_matrix_emits_typed_check_rule_ids(self):
        matrix = build_compatibility_matrix({
            "search_spec": {"required_specs": {"vram_gb": 12}},
            "recommended": [{
                "listing_id": "gpu-1",
                "specs": {"vram_gb": 8},
                "evidence": [{
                    "evidence_id": "gpu-1:ev",
                    "field": "specs",
                    "value": {"vram_gb": 8},
                    "status": "confirmed",
                }],
            }],
        })
        self.assertEqual(matrix["items"][0]["requirements"][0]["status"], "mismatch")


if __name__ == "__main__":
    unittest.main()
