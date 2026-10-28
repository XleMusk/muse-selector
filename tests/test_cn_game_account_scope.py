import unittest
from pathlib import Path

from muse_selector.connectors.local_fixture import LocalFixtureConnector
from muse_selector.pipeline import run_search
from muse_selector.query_parser import parse_query
from muse_selector.result_card import render_markdown
from muse_selector.source_capabilities import source_capability_registry


class ChinaAndGameAccountScopeTests(unittest.TestCase):
    def test_domestic_local_fixture_is_explicit_and_returns_cny_cards(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "domestic_cn_sample.json"
        payload = run_search(
            "国内预算 CNY 8000 以内的二手迷你主机",
            connector=LocalFixtureConnector(fixture),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "fixture.local.v1")
        self.assertEqual(payload["search_spec"]["currency"], "CNY")
        self.assertEqual([item["listing_id"] for item in payload["recommended"]], ["cn-mini-001"])

    def test_unqualified_second_hand_query_uses_domestic_profile(self):
        spec = parse_query("二手显卡，预算 5000 元")
        self.assertEqual((spec.region, spec.currency), ("CN", "CNY"))
        self.assertEqual(spec.sources, ("xianyu.partner.v1", "zhuanzhuan.recommerce.mcp.v1"))

    def test_explicit_hong_kong_second_hand_query_keeps_hk_profile(self):
        spec = parse_query("香港二手显卡，预算 5000 港币")
        self.assertEqual((spec.region, spec.currency), ("HK", "HKD"))
        self.assertEqual(spec.sources, ("ebay.browse.hk.v1",))

    def test_game_account_discovery_is_structured_and_connector_free(self):
        payload = run_search("国内原神游戏账号，预算 CNY 500")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "source_unavailable")
        self.assertEqual(payload["domain"], "game_accounts")
        self.assertEqual(payload["search_spec"]["category"], "game_accounts")
        self.assertEqual(payload["search_spec"]["product_type"], "game_account")
        self.assertEqual(payload["policy"]["source_id"], "game_accounts.policy.v1")
        self.assertTrue(payload["policy"]["link_only"])
        self.assertEqual(len(payload["link_only"]), 3)
        self.assertTrue(all(item["read_only"] for item in payload["link_only"]))
        self.assertIn("transfer", payload["policy"]["blocked_actions"])
        report = render_markdown(payload)
        self.assertIn(r"策略域：game\_accounts / game\_accounts.policy.v1", report)

    def test_game_account_transaction_remains_policy_blocked(self):
        payload = run_search("帮我买一个带稀有皮肤的游戏账号并完成转移")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "policy_blocked")
        self.assertEqual(payload["domain"], "game_accounts")
        self.assertFalse(payload["policy"]["link_only"])

    def test_game_account_capability_is_read_only_policy_only(self):
        capability = source_capability_registry()["game_accounts.policy.v1"]
        self.assertTrue(capability.read_only)
        self.assertFalse(capability.listing_search)
        self.assertEqual(capability.status, "link_only")
        self.assertIn("read_only_policy", capability.capabilities)


if __name__ == "__main__":
    unittest.main()
