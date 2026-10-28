import json
import tempfile
import unittest
from pathlib import Path

from muse_selector.feedback_contracts import FeedbackRecord, load_feedback_fixture, replay_feedback
from muse_selector.persistence import SelectorStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "feedback_events.json"


class FeedbackTests(unittest.TestCase):
    def test_fixture_replays_against_regression_membership(self):
        records = load_feedback_fixture(str(FIXTURE))
        report = replay_feedback(
            records,
            {
                "regression:hk_laptop_budget": ["ebay-hk-laptop-001"],
                "regression:hk_gpu_vram": ["ebay-hk-gpu-001"],
                "regression:hk_usb4_dock": ["ebay-hk-dock-001"],
            },
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["event_count"], 4)
        self.assertEqual(report["disagreement_count"], 0)

    def test_feedback_record_validates_labels(self):
        with self.assertRaisesRegex(ValueError, "label"):
            FeedbackRecord("f", "run", "listing", "unknown", "2026-10-24T00:00:00Z")

    def test_feedback_persists_idempotently_and_imports_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            run_id, inserted = store.save_run({
                "ok": True,
                "status": "complete",
                "search_spec": {"query": "fixture"},
                "recommended": [{"listing_id": "listing-1", "source_rank": 1}],
                "rejected": [],
                "dropped": [],
                "source": "fixture",
                "read_only": True,
            })
            self.assertTrue(inserted)
            record = FeedbackRecord(
                "feedback-1", run_id, "listing-1", "relevant", "2026-10-24T00:00:00Z",
                {"source": "test"},
            )
            _, first = store.save_feedback(record)
            _, second = store.save_feedback(record)
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(store.list_feedback(run_id=run_id)[0]["feedback_id"], "feedback-1")

            imported_fixture = Path(directory) / "feedback.json"
            imported_fixture.write_text(json.dumps({
                "events": [{
                    "feedback_id": "feedback-2",
                    "run_id": run_id,
                    "listing_id": "listing-1",
                    "label": "needs_review",
                    "recorded_at": "2026-10-24T00:00:01Z",
                }],
            }), encoding="utf-8")
            result = store.import_feedback_fixture(imported_fixture)
            self.assertEqual(result["inserted_count"], 1)
            self.assertEqual(len(store.list_feedback(run_id=run_id)), 2)


if __name__ == "__main__":
    unittest.main()
