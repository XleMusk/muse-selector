import unittest

from regression_harness import run_regression


class RegressionTests(unittest.TestCase):
    def test_fixture_regression(self):
        result = run_regression()
        self.assertTrue(result["ok"], "\\n".join(result["errors"]))
        self.assertEqual(result["hard_constraint_violation_rate"], 0.0)
        self.assertGreater(result["hard_constraint_checked_count"], 0)

    def test_hard_constraint_cases_have_candidates(self):
        result = run_regression()
        for case_id in ("hk_laptop_budget", "hk_gpu_vram", "hk_usb4_dock"):
            self.assertTrue(result["queries"][case_id]["accepted"], case_id)

    def test_policy_cases_are_blocked(self):
        result = run_regression()
        self.assertTrue(result["queries"]["game_account_policy_block"]["policy_blocked"])
        self.assertTrue(result["queries"]["ssrf_url"]["blocked"])


if __name__ == "__main__":
    unittest.main()
