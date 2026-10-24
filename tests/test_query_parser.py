import unittest
from decimal import Decimal

from muse_selector.query_parser import has_explicit_unbounded_budget, parse_query


class QueryParserBudgetRangeTests(unittest.TestCase):
    def test_hkd_hyphen_range(self):
        spec = parse_query("香港轻薄本，HKD 5000-7000")
        self.assertEqual(spec.budget_min, Decimal("5000.00"))
        self.assertEqual(spec.budget_max, Decimal("7000.00"))

    def test_chinese_range_with_currency_suffix(self):
        spec = parse_query("香港轻薄本，5000 至 7000 港币")
        self.assertEqual(spec.budget_min, Decimal("5000.00"))
        self.assertEqual(spec.budget_max, Decimal("7000.00"))

    def test_existing_upper_bound_is_unchanged(self):
        spec = parse_query("香港预算 HKD 7000 以内的迷你主机")
        self.assertIsNone(spec.budget_min)
        self.assertEqual(spec.budget_max, Decimal("7000.00"))

    def test_unbounded_budget_is_still_unbounded(self):
        spec = parse_query("香港 USB4 扩展坞，价格不限")
        self.assertIsNone(spec.budget_min)
        self.assertIsNone(spec.budget_max)
        self.assertTrue(has_explicit_unbounded_budget("价格不限"))

    def test_single_value_with_suffix_currency(self):
        spec = parse_query("香港轻薄本，7000 港币")
        self.assertIsNone(spec.budget_min)
        self.assertEqual(spec.budget_max, Decimal("7000.00"))

    def test_single_value_with_hk_dollar_prefix(self):
        spec = parse_query("香港轻薄本，HK$7000")
        self.assertIsNone(spec.budget_min)
        self.assertEqual(spec.budget_max, Decimal("7000.00"))
