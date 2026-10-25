import unittest

from metrics_harness import METRICS_SCHEMA_VERSION, run_metrics


class MetricsTests(unittest.TestCase):
    def test_synthetic_metrics_have_replay_and_read_only_baseline(self):
        report = run_metrics(repetitions=2)
        self.assertEqual(report["schema_version"], METRICS_SCHEMA_VERSION)
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["failure_count"], 0)
        self.assertEqual(report["hard_constraint_violation_rate"], 0.0)
        self.assertEqual(report["replay_mismatch_count"], 0)
        self.assertEqual(report["cost_proxy"]["external_requests"], 0)
        self.assertEqual(len(report["per_query"]), 5)


if __name__ == "__main__":
    unittest.main()
