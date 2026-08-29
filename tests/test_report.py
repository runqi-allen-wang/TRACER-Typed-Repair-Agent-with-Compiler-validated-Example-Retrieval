import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from report import summarize


class ReportMetricTest(unittest.TestCase):
    def test_token_and_topic_summaries_are_present(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "condition": "A",
                    "problem_id": "p1",
                    "round": 1,
                    "compile_ok": True,
                    "compile_elapsed_ms": 10,
                    "retrieved_examples": [],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                    "diagnostic": {"category": "ok"},
                    "tags": ["logic"],
                    "difficulty": "easy",
                },
                {
                    "condition": "B",
                    "problem_id": "p1",
                    "round": 1,
                    "compile_ok": False,
                    "compile_elapsed_ms": 11,
                    "retrieved_examples": [],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                    "diagnostic": {"category": "type_mismatch"},
                    "tags": ["logic"],
                    "difficulty": "easy",
                },
                {
                    "condition": "B",
                    "problem_id": "p1",
                    "round": 2,
                    "compile_ok": True,
                    "compile_elapsed_ms": 12,
                    "retrieved_examples": [],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
                    "diagnostic": {"category": "ok"},
                    "tags": ["logic"],
                    "difficulty": "easy",
                },
            ]
        )
        summary, failures, report = summarize(frame)
        self.assertEqual(summary.loc[summary["condition"] == "B", "avg_total_tokens"].iloc[0], 18.0)
        self.assertEqual(report["by_tag"][0]["tag"], "logic")
        self.assertTrue(failures.empty)

    def test_mixed_run_ids_are_rejected(self):
        import pandas as pd
        from report import summarize

        frame = pd.DataFrame(
            [
                {"run_id": "run-a", "condition": "A", "problem_id": "p1", "round": 1, "compile_ok": True, "compile_elapsed_ms": 1, "retrieved_examples": [], "usage": {}, "diagnostic": {"category": "ok"}, "tags": [], "difficulty": None},
                {"run_id": "run-b", "condition": "A", "problem_id": "p1", "round": 1, "compile_ok": False, "compile_elapsed_ms": 1, "retrieved_examples": [], "usage": {}, "diagnostic": {"category": "compile_error"}, "tags": [], "difficulty": None},
            ]
        )
        with self.assertRaisesRegex(ValueError, "多个 run_id"):
            summarize(frame)

    def test_unconfigured_cost_is_none(self):
        import pandas as pd
        from report import summarize

        frame = pd.DataFrame(
            [{"condition": "A", "problem_id": "p1", "round": 1, "compile_ok": True, "compile_elapsed_ms": 1, "retrieved_examples": [], "usage": {}, "estimated_cost_usd": None, "diagnostic": {"category": "ok"}, "tags": [], "difficulty": None}]
        )
        summary, _, _ = summarize(frame)
        self.assertIsNone(summary.iloc[0]["avg_cost_usd"])

    def test_manual_review_requires_every_problem_condition_pair(self):
        import tempfile
        import report

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manual_review.csv"
            path.write_text(
                "experiment_id,problem_id,condition,kernel_pass,inappropriate_assumption,leakage_risk,reviewer_note\n"
                "exp-1,p1,A,yes,no,no,checked\n",
                encoding="utf-8",
            )
            previous = report.REVIEW
            try:
                report.REVIEW = path
                self.assertFalse(report.manual_review_complete("exp-1", {("A", "p1"), ("B", "p1")}))
                with path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write("exp-1,p1,B,yes,no,no,checked\n")
                self.assertTrue(report.manual_review_complete("exp-1", {("A", "p1"), ("B", "p1")}))
            finally:
                report.REVIEW = previous


if __name__ == "__main__":
    unittest.main()
