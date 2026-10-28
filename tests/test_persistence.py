import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.persistence import SelectorStore, watch_change_summary, watch_content_fingerprint


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class PersistenceTests(unittest.TestCase):
    def test_existing_watch_schema_migrates_change_summary_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE watches (
                        watch_id TEXT PRIMARY KEY,
                        query TEXT NOT NULL,
                        fixture_path TEXT,
                        interval_seconds INTEGER NOT NULL,
                        enabled INTEGER NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        last_run_id TEXT,
                        last_refreshed_at TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO watches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("legacy", "mini pc", None, 900, 1, 0, "2026-01-01T00:00:00Z", None, None),
                )
                conn.commit()
            finally:
                conn.close()
            store = SelectorStore(db_path)
            self.assertIsNone(store.get_watch("legacy")["last_change_summary"])
            conn = store._connect()
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(watches)")}
            finally:
                conn.close()
            self.assertIn("last_change_summary_json", columns)
            self.assertIn("environment", columns)
            self.assertEqual(store.get_watch("legacy")["environment"], "production")

    def test_watch_environment_is_persisted_and_used_for_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_sandbox",
                environment="sandbox",
            )
            payload = {
                "ok": True,
                "status": "complete",
                "search_spec": {"query": "sandbox"},
                "recommended": [],
                "rejected": [],
                "dropped": [],
                "source": "ebay.browse.hk.v1",
                "read_only": True,
            }
            with patch("muse_selector.persistence.run_search", return_value=payload) as search:
                store.refresh_watch(watch_id)
            self.assertEqual(store.get_watch(watch_id)["environment"], "sandbox")
            self.assertEqual(search.call_args.kwargs["environment"], "sandbox")
            updated = store.update_watch(watch_id, environment="production")
            self.assertEqual(updated["environment"], "production")
            self.assertIsNone(updated["last_run_id"])

    def test_watch_threshold_events_are_persisted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_thresholds",
                thresholds={"price_max": "7000", "stock_required": True},
            )
            first = store.refresh_watch(watch_id)
            second = store.refresh_watch(watch_id)
            self.assertEqual(len(first["events"]), 2)
            self.assertEqual(second["events"], [])
            self.assertEqual(store.get_watch(watch_id)["thresholds"], {"price_max": "7000.00", "stock_required": True})
            events = store.list_watch_events(watch_id)
            self.assertEqual(len(events), 2)
            self.assertEqual({event["event_type"] for event in events}, {"price_max_reached", "stock_available"})

    def test_watch_thresholds_reject_unknown_or_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            with self.assertRaisesRegex(ValueError, "unsupported watch threshold"):
                store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, thresholds={"unknown": 1})
            with self.assertRaisesRegex(ValueError, "price_max"):
                store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, thresholds={"price_max": -1})

    def test_list_cards_preserves_source_rank_for_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            payload = {
                "ok": True,
                "status": "complete",
                "search_spec": {"query": "same"},
                "recommended": [
                    {"listing_id": "source-second", "source_rank": 2},
                    {"listing_id": "source-first", "source_rank": 1},
                ],
                "rejected": [],
                "dropped": [],
                "source": "ebay.browse.hk.v1",
                "read_only": True,
            }
            run_id, inserted = store.save_run(payload)
            self.assertTrue(inserted)
            self.assertEqual(
                [card["listing_id"] for card in store.list_cards(run_id)],
                ["source-first", "source-second"],
            )

    def test_concurrent_same_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "selector.sqlite3"
            first_store = SelectorStore(db_path)
            second_store = SelectorStore(db_path)
            watch_id = first_store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_race")
            payload = {
                "ok": True,
                "status": "complete",
                "search_spec": {"query": "same"},
                "recommended": [],
                "rejected": [],
                "dropped": [],
                "source": "ebay.browse.hk.v1",
                "read_only": True,
            }
            barrier = threading.Barrier(2)
            results = []
            errors = []

            def fake_search(*_args):
                barrier.wait(timeout=2)
                return payload

            def refresh(store):
                try:
                    results.append(store.refresh_watch(watch_id))
                except Exception as exc:  # pragma: no cover - assertion reports the unexpected error
                    errors.append(exc)

            with patch("muse_selector.persistence.run_search", side_effect=fake_search):
                threads = [threading.Thread(target=refresh, args=(store,)) for store in (first_store, second_store)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
            self.assertFalse(errors)
            self.assertEqual(len(results), 2)
            self.assertEqual({item["run_id"] for item in results}, {results[0]["run_id"]})

    def test_refresh_rejects_watch_update_during_search(self):
        """A result for an old query cannot become the new query's checkpoint."""

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "selector.sqlite3"
            store = SelectorStore(db_path)
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_update_race",
            )
            started = threading.Event()
            release = threading.Event()
            errors = []
            payload = {
                "ok": True,
                "status": "complete",
                "search_spec": {"query": "old"},
                "recommended": [],
                "rejected": [],
                "dropped": [],
                "source": "ebay.browse.hk.v1",
                "read_only": True,
            }

            def fake_search(*_args):
                started.set()
                release.wait(timeout=2)
                return payload

            def refresh():
                try:
                    store.refresh_watch(watch_id)
                except Exception as exc:  # pragma: no cover - assertion reports the unexpected error
                    errors.append(str(exc))

            with patch("muse_selector.persistence.run_search", side_effect=fake_search):
                thread = threading.Thread(target=refresh)
                thread.start()
                self.assertTrue(started.wait(timeout=2))
                store.update_watch(watch_id, query="香港 RTX 4070 显卡，预算 HKD 9000")
                release.set()
                thread.join(timeout=3)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [f"watch changed during refresh: {watch_id}"])
            self.assertIsNone(store.get_watch(watch_id)["last_run_id"])
            conn = store._connect()
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
            finally:
                conn.close()

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

    def test_watch_change_summary_tracks_listing_and_status_changes(self):
        previous = {
            "status": "complete",
            "recommended": [
                {"listing_id": "same", "title": "same", "source_observed_at": "2026-10-24T00:00:00Z"},
                {"listing_id": "removed", "title": "removed"},
            ],
        }
        current = {
            "status": "source_unavailable",
            "recommended": [
                {"listing_id": "same", "title": "updated", "source_observed_at": "2026-10-24T00:05:00Z"},
                {"listing_id": "added", "title": "added"},
            ],
        }
        self.assertEqual(
            watch_change_summary(previous, current),
            {
                "has_previous": True,
                "status_changed": True,
                "added_listing_ids": ["added"],
                "removed_listing_ids": ["removed"],
                "changed_listing_ids": ["same"],
            },
        )

    def test_run_is_idempotent_and_cards_are_queryable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_test")
            first = store.refresh_watch(watch_id)
            second = store.refresh_watch(watch_id)
            self.assertTrue(first["changed"])
            self.assertEqual(first["change_summary"]["has_previous"], False)
            self.assertEqual(len(first["change_summary"]["added_listing_ids"]), 1)
            self.assertFalse(second["changed"])
            self.assertEqual(
                second["change_summary"],
                {
                    "has_previous": True,
                    "status_changed": False,
                    "added_listing_ids": [],
                    "removed_listing_ids": [],
                    "changed_listing_ids": [],
                },
            )
            self.assertEqual(first["run_id"], second["run_id"])
            self.assertTrue(store.get_run(first["run_id"])["read_only"])
            self.assertEqual(len(store.list_cards(first["run_id"])), 1)
            self.assertEqual(store.list_watches()[0]["last_run_id"], first["run_id"])
            self.assertEqual(store.get_watch(watch_id)["last_change_summary"], second["change_summary"])

    def test_watch_change_history_is_distinct_and_replayable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_history",
            )
            first = store.refresh_watch(watch_id)
            store.refresh_watch(watch_id)
            store.update_watch(watch_id, query="香港 RTX 4070 显卡，预算 HKD 9000")
            second = store.refresh_watch(watch_id)

            changes = store.list_watch_changes(watch_id, include_payload=True)
            self.assertEqual([item["run_id"] for item in changes], [second["run_id"], first["run_id"]])
            self.assertEqual(changes[0]["change_summary"], second["change_summary"])
            self.assertEqual(changes[0]["payload"], second["payload"])
            self.assertEqual(changes[1]["payload"], first["payload"])
            self.assertEqual(len(store.list_watch_changes(watch_id)), 2)

    def test_watch_change_history_paginates_and_rejects_invalid_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_page")
            store.refresh_watch(watch_id)
            with self.assertRaises(ValueError):
                store.list_watch_changes(watch_id, limit=0)
            with self.assertRaises(ValueError):
                store.list_watch_changes(watch_id, offset=-1)
            self.assertEqual(len(store.list_watch_changes(watch_id, limit=1, offset=1)), 0)

    def test_watch_change_history_backfills_an_upgraded_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "selector.sqlite3"
            store = SelectorStore(db_path)
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_backfill")
            first = store.refresh_watch(watch_id)
            conn = store._connect()
            try:
                conn.execute("DELETE FROM watch_changes WHERE watch_id = ?", (watch_id,))
                conn.commit()
            finally:
                conn.close()
            second = store.refresh_watch(watch_id)
            self.assertFalse(second["changed"])
            history = store.list_watch_changes(watch_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["run_id"], first["run_id"])

    def test_live_watch_unavailable_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港 RTX 4070 显卡，预算 HKD 9000", watch_id="watch_live")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "source_unavailable")
            self.assertTrue(result["auto_paused"])
            self.assertEqual(store.get_watch(watch_id)["enabled"], 0)
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_store_uses_injected_search_function(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def fake_search(query, fixture_path, **kwargs):
                calls.append((query, fixture_path, kwargs))
                return {
                    "ok": True,
                    "status": "complete",
                    "source": "fixture.local.v1",
                    "recommended": [],
                    "rejected": [],
                    "dropped": [],
                    "read_only": True,
                }

            store = SelectorStore(Path(directory) / "selector.sqlite3", search_fn=fake_search)
            watch_id = store.add_watch("国内预算 CNY 8000 以内的二手显卡", watch_id="injected_search")
            store.refresh_watch(watch_id)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "国内预算 CNY 8000 以内的二手显卡")

    def test_policy_blocked_watch_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("帮我买一个游戏账号并完成转移", watch_id="watch_policy")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "policy_blocked")
            self.assertTrue(result["auto_paused"])
            self.assertEqual(store.get_watch(watch_id)["enabled"], 0)
            self.assertTrue(result["payload"]["read_only"])
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_clarification_watch_is_saved_as_read_only_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("找一台适合本地视觉模型的电脑", watch_id="watch_clarify")
            result = store.refresh_watch(watch_id)
            self.assertFalse(result["payload"]["ok"])
            self.assertEqual(result["payload"]["status"], "needs_clarification")
            self.assertTrue(result["auto_paused"])
            self.assertEqual(store.get_watch(watch_id)["enabled"], 0)
            self.assertTrue(result["payload"]["read_only"])
            self.assertIsNotNone(store.get_run(result["run_id"]))

    def test_disabled_watch_does_not_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_disabled")
            store.disable_watch(watch_id)
            with self.assertRaises(ValueError):
                store.refresh_watch(watch_id)

    def test_watch_can_pause_resume_and_replay_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_lifecycle")
            first = store.refresh_watch(watch_id)
            store.pause_watch(watch_id)
            self.assertFalse(store.get_watch(watch_id)["enabled"])
            self.assertEqual(store.replay_watch(watch_id), first["payload"])
            with self.assertRaises(ValueError):
                store.refresh_watch(watch_id)
            store.resume_watch(watch_id)
            second = store.refresh_watch(watch_id)
            self.assertFalse(second["changed"])
            self.assertEqual(store.replay_run(first["run_id"]), first["payload"])

    def test_manual_watch_edit_clears_checkpoint_but_preserves_old_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港预算 HKD 7000 以内的迷你主机", FIXTURE, watch_id="watch_edit")
            first = store.refresh_watch(watch_id)
            updated = store.update_watch(watch_id, query="香港 RTX 4070 显卡，预算 HKD 9000", interval_seconds=60)
            self.assertEqual(updated["interval_seconds"], 60)
            self.assertIsNone(updated["last_run_id"])
            self.assertIsNone(updated["last_change_summary"])
            self.assertEqual(store.replay_run(first["run_id"]), first["payload"])
            second = store.refresh_watch(watch_id)
            self.assertNotEqual(second["run_id"], first["run_id"])

    def test_refresh_rolls_back_run_when_checkpoint_update_fails(self):
        """A failed checkpoint cannot leave an orphan persisted observation."""

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "selector.sqlite3"
            store = SelectorStore(db_path)
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_atomic",
            )
            conn = store._connect()
            try:
                conn.execute(
                    """
                    CREATE TRIGGER abort_watch_checkpoint
                    BEFORE UPDATE OF last_run_id ON watches
                    BEGIN
                        SELECT RAISE(ABORT, 'checkpoint write blocked');
                    END;
                    """
                )
                conn.commit()
            finally:
                conn.close()

            with self.assertRaises(sqlite3.IntegrityError):
                store.refresh_watch(watch_id)

            watch = store.get_watch(watch_id)
            self.assertIsNone(watch["last_run_id"])
            conn = store._connect()
            try:
                run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(run_count, 0)


if __name__ == "__main__":
    unittest.main()

