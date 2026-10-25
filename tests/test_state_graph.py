import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.state_graph import STATE_GRAPH_SCHEMA_VERSION, run_search_graph, run_state_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class StateGraphTests(unittest.TestCase):
    def test_graph_has_observable_stages_and_checkpoint(self):
        result = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        self.assertTrue(result["ok"])
        execution = result["execution"]
        self.assertEqual(execution["schema_version"], STATE_GRAPH_SCHEMA_VERSION)
        self.assertEqual(execution["current_stage"], "present")
        self.assertEqual([item["name"] for item in execution["stages"]], [
            "parse", "fanout", "normalize", "filter", "rank", "verify", "present"
        ])
        self.assertTrue(all(item["status"] == "complete" for item in execution["stages"]))
        self.assertEqual(execution["checkpoint"]["completed_stage"], "present")
        self.assertTrue(execution["read_only"])

    def test_checkpoint_replay_does_not_call_pipeline(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        checkpoint = first["execution"]["checkpoint"]
        with patch("muse_selector.state_graph.run_search", side_effect=AssertionError("replay called pipeline")):
            replay = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE, checkpoint=checkpoint)
        self.assertTrue(replay["ok"])
        self.assertTrue(replay["execution"]["resumed_from_checkpoint"])
        self.assertEqual(replay["recommended"], first["recommended"])
        self.assertEqual(replay["execution"]["checkpoint"]["payload_fingerprint"], checkpoint["payload_fingerprint"])

    def test_mismatched_checkpoint_fails_closed(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        with self.assertRaisesRegex(ValueError, "different execution"):
            run_search_graph("香港 RTX 4070 显卡，预算 HKD 9000", FIXTURE, checkpoint=first["execution"]["checkpoint"])

    def test_compact_state_graph_envelope_is_replayable(self):
        first = run_state_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        self.assertEqual(first["schema_version"], STATE_GRAPH_SCHEMA_VERSION)
        self.assertEqual(first["status"], "complete")
        self.assertTrue(first["run_id"].startswith("exec_"))
        replay = run_state_graph(
            "香港预算 HKD 7000 以内的迷你主机",
            FIXTURE,
            checkpoint=first["checkpoint"],
        )
        self.assertEqual(replay["run_id"], first["run_id"])
        self.assertTrue(replay["resumed_from_checkpoint"])
        self.assertEqual(replay["payload"], first["payload"])


if __name__ == "__main__":
    unittest.main()
