import unittest
from pathlib import Path

from muse_selector.application import SearchApplication


class _FakeConnector:
    source_id = "ebay.browse.hk.v1"
    source_metadata = {"adapter": "factory-test"}

    def search(self, search_spec):
        return []


class SourceFactoryTests(unittest.TestCase):
    def test_application_builds_connector_at_composition_boundary(self):
        calls = []

        def factory(*, fixture_path=None, environment=None):
            calls.append((fixture_path, environment))
            return _FakeConnector()

        fixture = Path("tests/fixtures/ebay_hk_sample.json")
        payload = SearchApplication(source_factory=factory).search(
            "香港预算 HKD 2000 以内的迷你主机",
            fixture,
            environment="sandbox",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_metadata"], {"adapter": "factory-test"})
        self.assertEqual(calls, [(fixture, "sandbox")])

    def test_policy_only_queries_do_not_construct_a_source(self):
        calls = []

        def factory(*, fixture_path=None, environment=None):
            calls.append((fixture_path, environment))
            raise AssertionError("source factory should not run for policy-only queries")

        app = SearchApplication(source_factory=factory)
        game = app.search("国内原神游戏账号，预算 CNY 500")
        domestic = app.search("国内预算 CNY 8000 以内的二手迷你主机")
        self.assertEqual(game["domain"], "game_accounts")
        self.assertEqual(domestic["source"], "domestic.secondhand.pending")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
