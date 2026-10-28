import unittest

from shadow_harness import run_shadow


class ShadowHarnessTests(unittest.TestCase):
    def test_hk_and_cn_fixture_paths_are_replay_stable_and_read_only(self):
        report = run_shadow()
        self.assertTrue(report["ok"])
        self.assertEqual(report["workload_count"], 2)
        self.assertEqual(report["success_rate"], 1.0)
        self.assertEqual(report["hard_constraint_violation_rate"], 0.0)
        self.assertEqual(report["replay_stability_rate"], 1.0)
        self.assertEqual(report["cost_proxy"]["external_requests"], 0)
        self.assertEqual({case["region"] for case in report["cases"]}, {"HK", "CN"})


if __name__ == "__main__":
    unittest.main()
