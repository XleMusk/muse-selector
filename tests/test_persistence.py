import tempfile
import unittest
from pathlib import Path

from muse_selector.persistence import SelectorStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class PersistenceTests(unittest.TestCase):
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

    def test_disabled_watch_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_disabled")
            store.disable_watch(watch_id)
            with self.assertRaises(ValueError):
                store.refresh_watch(watch_id)


if __name__ == "__main__":
    unittest.main()

