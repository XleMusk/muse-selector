import unittest

from regression_harness import build_quality_report, run_regression


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

    def test_labeled_ranking_baseline_is_reproducible(self):
        result = run_regression()
        metrics = result["ranking_metrics"]
        self.assertEqual(metrics["labeled_case_count"], 6)
        self.assertGreater(metrics["precision_at_10"], 0.0)
        self.assertEqual(metrics["recall_at_20"], 1.0)
        self.assertEqual(metrics["ndcg_at_10"], 1.0)
        self.assertEqual(metrics["top_k_jaccard"], 1.0)
        self.assertEqual(result["queries"]["hk_gpu_vram"]["ranking_metrics"]["recall_at_20"], 1.0)

    def test_policy_cases_are_blocked(self):
        result = run_regression()
        self.assertTrue(result["queries"]["game_account_policy_block"]["policy_blocked"])
        self.assertTrue(result["queries"]["ssrf_url"]["blocked"])

    def test_quality_report_is_deterministic_and_ttl_bounded(self):
        first = run_regression()["quality_report"]
        second = run_regression()["quality_report"]
        self.assertEqual(first, second)
        self.assertEqual(first["listing_count"], 6)
        self.assertEqual(first["identity_unknown_count"], 0)
        self.assertEqual(first["duplicate_listing_count"], 0)
        self.assertEqual(first["ttl_hours"], 72)
        self.assertEqual(first["stale_count"], 1)
        self.assertEqual(first["fresh_count"], 5)
        self.assertEqual(first["unknown_observed_at_count"], 0)

    def test_quality_report_does_not_infer_identity_from_title(self):
        report = build_quality_report([
            {
                "listing_id": "title-only",
                "title": "Lenovo ThinkPad 21K3 32GB",
                "source": {"observed_at": "2026-10-24T10:00:00Z"},
            },
            {
                "listing_id": "explicit-mpn-a",
                "title": "unknown",
                "mpn": "M-1",
                "source": {"observed_at": "2026-10-24T10:00:00Z"},
            },
            {
                "listing_id": "explicit-mpn-b",
                "title": "unknown",
                "mpn": "M-1",
                "source": {"observed_at": "2026-10-24T10:00:00Z"},
            },
        ])
        self.assertEqual(report["identity_unknown_count"], 1)
        self.assertEqual(report["duplicate_group_count"], 1)
        self.assertEqual(report["duplicate_listing_count"], 1)


if __name__ == "__main__":
    unittest.main()
