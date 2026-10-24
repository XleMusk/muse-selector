import json
import unittest
from pathlib import Path

from muse_selector.query_parser import has_explicit_unbounded_budget, parse_query


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests" / "fixtures" / "search_queries_v1.json"


class SearchQueryCatalogTests(unittest.TestCase):
    def test_v1_catalog_has_twenty_parseable_hk_queries(self):
        cases = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["case_id"] for case in cases}), 20)
        for case in cases:
            spec = parse_query(case["query"])
            self.assertEqual(spec.region, "HK", case["case_id"])
            self.assertEqual(spec.currency, "HKD", case["case_id"])
            self.assertTrue(
                spec.budget_max is not None or has_explicit_unbounded_budget(case["query"]),
                case["case_id"],
            )


if __name__ == "__main__":
    unittest.main()
