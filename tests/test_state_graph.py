import copy
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_selector.state_graph import STAGE_CHECKPOINT_SCHEMA_VERSION, STATE_GRAPH_SCHEMA_VERSION, load_checkpoint, main, run_search_graph, run_state_graph, save_checkpoint


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
        self.assertEqual(execution["checkpoint"]["schema_version"], STAGE_CHECKPOINT_SCHEMA_VERSION)
        self.assertTrue(execution["checkpoint"]["stage_fingerprint"])
        self.assertEqual(execution["stages"], execution["checkpoint"]["stages"])
        self.assertTrue(all(item["completed_at"] for item in execution["checkpoint"]["stages"]))
        self.assertTrue(all(item["data_fingerprint"] for item in execution["checkpoint"]["stages"]))
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

    def test_checkpoint_rejects_incomplete_stage_list(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        checkpoint = copy.deepcopy(first["execution"]["checkpoint"])
        checkpoint["stages"].pop()
        with self.assertRaisesRegex(ValueError, "checkpoint stages are incomplete"):
            run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE, checkpoint=checkpoint)

    def test_checkpoint_rejects_mismatched_stage_fingerprint(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        checkpoint = copy.deepcopy(first["execution"]["checkpoint"])
        checkpoint["stage_fingerprint"] = "tampered"
        with self.assertRaisesRegex(ValueError, "stage fingerprint"):
            run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE, checkpoint=checkpoint)

    def test_checkpoint_rejects_tampered_stage_data(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        checkpoint = copy.deepcopy(first["execution"]["checkpoint"])
        checkpoint["stages"][1]["data_fingerprint"] = "tampered"
        with self.assertRaisesRegex(ValueError, "checkpoint stages do not match payload"):
            run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE, checkpoint=checkpoint)

    def test_legacy_checkpoint_without_stage_metadata_remains_replayable(self):
        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        checkpoint = copy.deepcopy(first["execution"]["checkpoint"])
        checkpoint.pop("schema_version", None)
        checkpoint.pop("stages", None)
        checkpoint.pop("stage_fingerprint", None)
        replay = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE, checkpoint=checkpoint)
        self.assertTrue(replay["execution"]["resumed_from_checkpoint"])
        self.assertTrue(replay["execution"]["checkpoint"]["stages"])

    def test_checkpoint_file_round_trip_replays_without_pipeline(self):
        import tempfile

        first = run_search_graph("香港预算 HKD 7000 以内的迷你主机", FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(path, first["execution"]["checkpoint"])
            persisted = load_checkpoint(path)
            with patch("muse_selector.state_graph.run_search", side_effect=AssertionError("replay called pipeline")):
                replay = run_search_graph(
                    "香港预算 HKD 7000 以内的迷你主机",
                    FIXTURE,
                    checkpoint=persisted,
                )
        self.assertTrue(replay["execution"]["resumed_from_checkpoint"])
        self.assertEqual(replay["recommended"], first["recommended"])

    def test_cli_checkpoint_out_then_checkpoint_replays(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            output = io.StringIO()
            args = [
                "muse-state-graph",
                "--query", "香港预算 HKD 7000 以内的迷你主机",
                "--fixture", str(FIXTURE),
                "--checkpoint-out", str(path),
            ]
            with patch("sys.argv", args), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            output = io.StringIO()
            args[-2:] = ["--checkpoint", str(path)]
            with patch("sys.argv", args), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            self.assertTrue(json.loads(output.getvalue())["resumed_from_checkpoint"])

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
