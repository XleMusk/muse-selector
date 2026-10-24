import tempfile
import unittest
from pathlib import Path

from muse_selector.persistence import SelectorStore, watch_content_fingerprint


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class PersistenceTests(unittest.TestCase):
    def test_watch_fingerprint_ignores_observation_clocks(self):
        base = {
            "status": "complete",
            "read_only": True,
            "source": "ebay.browse.hk.v1",
            "recommended": [{
                "listing_id": "x",
                "source_observed_at": "2026-10-24T00:00:00Z",
                "evidence": [{"observed_at": "2026-10-24T00:00:00Z", "value": "same"}],
            }],
        }
        later = {
            **base,
            "recommended": [{
                **base["recommended"][0],
                "source_observed_at": "2026-10-24T00:05:00Z",
                "evidence": [{"observed_at": "2026-10-24T00:05:00Z", "value": "same"}],
            }],
        }
        changed = {
            **later,
            "recommended": [{**later["recommended"][0], "evidence": [{"observed_at": "2026-10-24T00:05:00Z", "value": "changed"}]}],
        }
        self.assertEqual(watch_content_fingerprint(base), watch_content_fingerprint(later))
        self.assertNotEqual(watch_content_fingerprint(base), watch_content_fingerprint(changed))

    def test_run_is_idempotent_and_cards_are_queryable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_test")
            first = store.refresh_watch(watch_id)
            second = store.refresh_watch(watch_id)
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(first["run_id"], second["run_id"])
            self.assertTrue(store.get_run(first["run_id"])["read_only"])
            self.assertEqual(len(store.list_cards(first["run_id"])), 1)
            self.assertEqual(store.list_watches()[0]["last_run_id"], first["run_id"])

    def test_live_watch_unavailable_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港 RTX 4070 显卡，预算 HKD 9000", watch_id="watch_live")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "source_unavailable")
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_policy_blocked_watch_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("帮我买一个游戏账号并完成转移", watch_id="watch_policy")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "policy_blocked")
            self.assertTrue(result["payload"]["read_only"])
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_clarification_watch_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("找一台适合本地视觉模型的电脑", watch_id="watch_clarify")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "needs_clarification")
            self.assertTrue(result["payload"]["read_only"])
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_disabled_watch_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_disabled")
            store.disable_watch(watch_id)
            with self.assertRaises(ValueError):
                store.refresh_watch(watch_id)


if __name__ == "__main__":
    unittest.main()

