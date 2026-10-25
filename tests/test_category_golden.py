import json
import unittest
from decimal import Decimal
from pathlib import Path

from muse_selector.contracts import SearchSpec
from muse_selector.filtering import filter_listings
from muse_selector.source_normalizer import normalize_source_row


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "category_golden.json"


class CategoryGoldenTests(unittest.TestCase):
    def test_phone_laptop_and_gpu_golden_records_pass_common_pipeline(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual({case["product_type"] for case in cases}, {"smartphone", "laptop", "gpu"})
        for case in cases:
            listing, evidence, reason = normalize_source_row(case["listing"], product_type=case["product_type"])
            self.assertIsNone(reason, case["product_type"])
            self.assertEqual(listing.category_attributes.keys(), case["listing"]["specs"].keys())
            self.assertEqual(listing.evidence_coverage, 1.0)
            spec = SearchSpec(
                query=case["query"],
                budget_max=Decimal("10000"),
                condition="used",
                product_type=case["product_type"],
                required_specs=case["required_specs"],
            )
            accepted, decisions = filter_listings(spec, [listing])
            self.assertEqual([item.listing_id for item in accepted], [case["listing"]["listing_id"]])
            self.assertEqual(decisions[0].reasons, ())


if __name__ == "__main__":
    unittest.main()
