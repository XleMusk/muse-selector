import tempfile
import unittest
from pathlib import Path

from muse_selector.persistence import SelectorStore
from muse_selector.watch_contracts import AuditRecord, RefreshJob, WatchEvent, WatchSpec


class WatchContractTests(unittest.TestCase):
    def test_watch_spec_round_trips_existing_store_shape(self):
        value = WatchSpec.from_mapping(
            {
                "watch_id": "watch-1",
                "query": "香港预算 HKD 7000 以内的迷你主机",
                "fixture_path": "tests/fixtures/ebay_hk_sample.json",
                "environment": "sandbox",
                "interval_seconds": 60,
                "enabled": 1,
                "revision": 2,
                "thresholds": {"price_max": "7000.00"},
            }
        )
        self.assertEqual(value.environment, "sandbox")
        self.assertEqual(value.to_dict()["thresholds"], {"price_max": "7000.00"})

    def test_refresh_job_requires_run_id_only_when_complete(self):
        queued = RefreshJob("job-1", "watch-1", "queued")
        self.assertEqual(queued.to_dict()["status"], "queued")
        with self.assertRaises(ValueError):
            RefreshJob("job-2", "watch-1", "complete")
        completed = RefreshJob("job-3", "watch-1", "complete", run_id="run-1")
        self.assertEqual(completed.run_id, "run-1")

    def test_watch_event_and_audit_record_are_read_only(self):
        event = WatchEvent.from_mapping(
            {
                "event_id": 1,
                "watch_id": "watch-1",
                "run_id": "run-1",
                "event_key": "stock:listing-1:in_stock",
                "event_type": "stock_available",
                "observed_at": "2026-10-25T00:00:00Z",
                "details": {"stock_status": "in_stock"},
            }
        )
        self.assertEqual(event.details["stock_status"], "in_stock")
        audit = AuditRecord("audit-1", "watch.refresh", "complete", event.observed_at)
        self.assertTrue(audit.to_dict()["read_only"])
        with self.assertRaises(ValueError):
            AuditRecord("audit-2", "watch.refresh", "complete", event.observed_at, read_only=False)

    def test_store_exposes_typed_watch_and_event_views(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "ebay_hk_sample.json"
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                fixture,
                watch_id="watch-typed",
                thresholds={"stock_required": True},
            )
            spec = store.get_watch_spec(watch_id)
            self.assertIsInstance(spec, WatchSpec)
            self.assertEqual(spec.thresholds["stock_required"], True)
            store.refresh_watch(watch_id)
            self.assertIsInstance(store.list_watch_event_models(watch_id), list)
            refreshed = store.refresh_watch(watch_id)
            self.assertEqual(refreshed["refresh_job"]["status"], "complete")
            self.assertEqual(refreshed["refresh_job"]["run_id"], refreshed["run_id"])

    def test_refresh_job_marks_source_failure_without_hiding_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch("香港 RTX 4070 显卡，预算 HKD 9000", watch_id="watch-failure")
            result = store.refresh_watch(watch_id)
            self.assertEqual(result["payload"]["status"], "source_unavailable")
            self.assertEqual(result["refresh_job"]["status"], "failed")
            self.assertTrue(result["refresh_job"]["error"])


if __name__ == "__main__":
    unittest.main()
