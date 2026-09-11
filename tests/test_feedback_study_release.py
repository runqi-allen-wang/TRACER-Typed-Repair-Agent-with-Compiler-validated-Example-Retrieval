import csv
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_feedback_study import audit_release  # noqa: E402
from audit_feedback_comparison import audit_comparison  # noqa: E402


RELEASE = ROOT / "published" / "feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248"
SECOND_RELEASE = ROOT / "published" / "feedback-study-562ad440-3446-4138-801e-59726ed0e108"
COMPARISON = ROOT / "published" / "feedback-cross-model-8ccb89dd-562ad440"


class FeedbackStudyReleaseTest(unittest.TestCase):
    def test_published_release_passes_static_audit(self):
        result = audit_release(RELEASE)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(
            (result["tasks"], result["attempts"], result["successes"], result["failed_tasks"], result["proof_files"]),
            (216, 283, 199, 17, 199),
        )

    def test_public_attempts_exclude_exact_prompts_and_provider_ids(self):
        attempts = [
            json.loads(line)
            for line in (RELEASE / "attempts.sanitized.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(attempts), 283)
        self.assertTrue(all("prompt" not in row for row in attempts))
        self.assertTrue(all("id" not in row.get("provider_response", {}) for row in attempts))
        self.assertFalse((RELEASE / "retry_history").exists())

    def test_review_and_call_disclosure_are_explicit(self):
        with (RELEASE / "ai_assisted_review.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        manifest = json.loads((RELEASE / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 216)
        self.assertEqual({row["review_mode"] for row in rows}, {"ai_assisted"})
        self.assertEqual(manifest["counts"]["attempted_call_reservations"], 286)
        self.assertEqual(manifest["counts"]["archived_retry_round_records"], 2)
        self.assertEqual(manifest["counts"]["unmatched_call_reservations"], 1)

    def test_second_model_release_passes_static_audit(self):
        result = audit_release(SECOND_RELEASE)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(
            (result["tasks"], result["attempts"], result["successes"], result["failed_tasks"], result["proof_files"]),
            (216, 245, 209, 7, 209),
        )

    def test_cross_model_comparison_passes_static_audit(self):
        result = audit_comparison(COMPARISON)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["matched_tasks"], 216)


if __name__ == "__main__":
    unittest.main()
