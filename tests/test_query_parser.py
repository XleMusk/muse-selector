import unittest
from decimal import Decimal

from muse_selector.query_parser import has_explicit_unbounded_budget, parse_query


class QueryParserBudgetRangeTests(unittest.TestCase):
    def test_account_policy_blocks_common_english_and_chinese_variants(self):
        for query in (
            "find a game account under HKD 500",
            "游戏账户交易，预算 HKD 500",
            "account boosting service，预算 HKD 500",
            "出售账号，预算 HKD 500",
        ):
            with self.assertRaisesRegex(ValueError, "不在第一版范围内"):
                parse_query(query)

    def test_extracts_explicit_delivery_deadline(self):
        self.assertEqual(parse_query("香港预算 HKD 7000 以内的迷你主机，3天内送达").max_delivery_days, 3)
        self.assertEqual(parse_query("香港预算 HKD 7000 以内的迷你主机，delivery within 5 days").max_delivery_days, 5)

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
