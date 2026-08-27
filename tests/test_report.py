import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from report import summarize, validate_experiment, validate_manual_review


class ReportMetricTest(unittest.TestCase):
    def test_token_and_topic_summaries_are_present(self):
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

    @staticmethod
    def run_row(condition, *, run_id="run-1", provider_config=None, round_no=1, compile_ok=True):
        return {
            "condition": condition,
            "problem_id": "p1",
            "run_id": run_id,
            "round": round_no,
            "compile_ok": compile_ok,
            "diagnostic": {"category": "ok" if compile_ok else "type_mismatch"},
            "provider_config": provider_config if provider_config is not None else {"provider": "mock"},
            "candidate_policy": {
                "version": "tracer-candidate-v2",
                "meta_execution": "blocked",
                "unsafe_declarations": "blocked",
                "environment": "minimal",
            },
            "cache_hit": False,
            "provider_error": None,
        }

    def test_formal_validation_requires_all_three_conditions(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(json.dumps([{"id": "p1"}]), encoding="utf-8")
            frame = pd.DataFrame([self.run_row("A"), self.run_row("B")])
            with patch("report.BENCHMARKS", manifest):
                errors, warnings = validate_experiment(frame)
                draft_errors, draft_warnings = validate_experiment(frame, allow_incomplete=True)
            self.assertTrue(any("缺少条件" in error for error in errors))
            self.assertEqual(draft_errors, [])
            self.assertTrue(any("缺少条件" in warning for warning in draft_warnings))
            self.assertEqual(warnings, [])

    def test_validation_rejects_mixed_run_ids_and_missing_provider_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(json.dumps([{"id": "p1"}]), encoding="utf-8")
            rows = [self.run_row(condition, provider_config={}) for condition in ("A", "B", "C")]
            rows.append(self.run_row("A", run_id="run-2", provider_config={}, round_no=2, compile_ok=False))
            with patch("report.BENCHMARKS", manifest):
                errors, _ = validate_experiment(pd.DataFrame(rows))
            self.assertTrue(any("run_id" in error for error in errors))
            self.assertTrue(any("provider 配置" in error for error in errors))

    def test_manual_review_uses_documented_yes_no_semantics(self):
        frame = pd.DataFrame([{"condition": "A", "problem_id": "p1", "compile_ok": True}])
        fields = [
            "experiment_id", "problem_id", "condition", "kernel_pass",
            "inappropriate_assumption", "leakage_risk", "reviewer_note",
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "experiment_id": "exp", "problem_id": "p1", "condition": "A",
                    "kernel_pass": "yes", "inappropriate_assumption": "no",
                    "leakage_risk": "no", "reviewer_note": "checked",
                })
            errors, warnings = validate_manual_review(path, frame, "exp")
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

            text = path.read_text(encoding="utf-8").replace(",no,checked", ",yes,checked")
            path.write_text(text, encoding="utf-8")
            errors, _ = validate_manual_review(path, frame, "exp")
            self.assertTrue(any("泄漏风险" in error for error in errors))

    def test_manual_review_must_cover_every_logged_pair(self):
        frame = pd.DataFrame([
            {"condition": "A", "problem_id": "p1", "compile_ok": False},
            {"condition": "B", "problem_id": "p1", "compile_ok": False},
        ])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.csv"
            path.write_text(
                "experiment_id,problem_id,condition,kernel_pass,inappropriate_assumption,leakage_risk,reviewer_note\n"
                "exp,p1,A,,,,\n",
                encoding="utf-8",
            )
            errors, _ = validate_manual_review(path, frame, "exp")
            self.assertTrue(any("台账缺少" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
