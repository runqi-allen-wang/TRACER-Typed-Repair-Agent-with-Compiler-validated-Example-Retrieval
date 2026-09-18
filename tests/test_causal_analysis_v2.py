import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_analysis_v2 import analyze  # noqa: E402


def fixture(projects=5, pairs_per_project=1, treatment=True, control=False):
    seeds = []
    branches = []
    for index in range(projects):
        for pair in range(pairs_per_project):
            seed_id = f"model/r1/case_{index}_{pair}"
            seeds.append({
                "seed_id": seed_id,
                "project_id": f"project_{index}",
                "split": "test",
                "eligible_first_failure": True,
            })
            branches.extend([
                {
                    "seed_id": seed_id,
                    "arm": "true_structured",
                    "status": "complete",
                    "compile_ok": treatment,
                },
                {
                    "seed_id": seed_id,
                    "arm": "content_free_retry",
                    "status": "complete",
                    "compile_ok": control,
                },
            ])
    return seeds, branches


class CausalAnalysisV2Test(unittest.TestCase):
    def test_five_consistent_project_wins_reach_exact_one_sided_gate(self):
        result = analyze(*fixture(pairs_per_project=6), resamples=200)
        self.assertEqual(result["test_projects"], 5)
        self.assertEqual(result["mean_success_delta"], 1.0)
        self.assertEqual(result["one_sided_p_value"], 1 / 32)
        self.assertEqual(result["randomization_assignments_or_draws"], 32)
        self.assertEqual(result["hierarchical_interval_95"], {"low": 1.0, "high": 1.0})
        self.assertTrue(result["primary_test_pass_at_0_05"])
        self.assertTrue(result["minimum_sample_gate_pass"])
        self.assertTrue(result["confirmatory_claim_allowed"])

    def test_zero_project_effect_does_not_pass(self):
        result = analyze(*fixture(treatment=False, control=False), resamples=100)
        self.assertEqual(result["mean_success_delta"], 0.0)
        self.assertFalse(result["confirmatory_direction_pass"])
        self.assertFalse(result["primary_test_pass_at_0_05"])

    def test_incomplete_primary_pair_is_rejected(self):
        seeds, branches = fixture()
        branches.pop()
        with self.assertRaisesRegex(ValueError, "分支不完整"):
            analyze(seeds, branches, resamples=100)

    def test_duplicate_branch_is_rejected(self):
        seeds, branches = fixture()
        branches.append(dict(branches[0]))
        with self.assertRaisesRegex(ValueError, "重复"):
            analyze(seeds, branches, resamples=100)


if __name__ == "__main__":
    unittest.main()
