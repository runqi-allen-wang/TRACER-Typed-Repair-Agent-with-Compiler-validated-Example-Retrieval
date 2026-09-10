import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feedback_adoption import analyze_trace, load_trace_files, summarize_analyses  # noqa: E402


def row(round_no, candidate, category, raw, *, query="", paths=(), strategy="diagnostic", cache=False):
    return {
        "run_id": "run-one",
        "experiment_id": "experiment-one",
        "problem_id": "problem-one",
        "condition": "C",
        "round": round_no,
        "candidate": candidate,
        "diagnostic": {"category": category},
        "raw_diagnostics": raw,
        "compile_ok": category == "ok",
        "compile_returncode": 0 if category == "ok" else 1,
        "compile_timed_out": False,
        "cache_hit": cache,
        "retrieval_strategy": strategy,
        "retrieval_query": query,
        "retrieved_examples": [{"path": path} for path in paths],
        "feedback_payload": "recorded feedback" if round_no > 1 else None,
    }


class FeedbackAdoptionTest(unittest.TestCase):
    def test_unknown_identifier_repair_is_relevant_change(self):
        rows = [
            row(1, "by exact misspelledName", "unknown_identifier", "error: unknown identifier 'misspelledName'", query="q1", paths=("a",)),
            row(2, "by trivial", "ok", "", query="q2", paths=("b",)),
        ]
        result = analyze_trace(rows)
        transition = result["transitions"][0]
        self.assertEqual(transition["adoption_observation"], "relevant_change")
        self.assertTrue(transition["query_changed"])
        self.assertTrue(transition["top_k_changed"])

    def test_unchanged_candidate_and_cache_reuse_are_separate(self):
        rows = [
            row(1, "by exact x", "unknown_identifier", "error: unknown identifier 'x'"),
            row(2, "by exact x", "unknown_identifier", "error: unknown identifier 'x'", cache=True),
        ]
        result = analyze_trace(rows)
        self.assertEqual(result["transitions"][0]["adoption_observation"], "cache_reuse")

    def test_dynamic_and_static_query_rates_are_reported_separately(self):
        dynamic = analyze_trace([
            row(1, "by exact x", "unknown_identifier", "error: unknown identifier 'x'", query="q1", paths=("a",)),
            row(2, "by exact y", "unknown_identifier", "error: unknown identifier 'y'", query="q2", paths=("b",)),
        ])
        static = analyze_trace([
            {**row(1, "by exact x", "unknown_identifier", "error: unknown identifier 'x'", query="same", paths=("a",), strategy="static"), "run_id": "run-two"},
            {**row(2, "by exact y", "unknown_identifier", "error: unknown identifier 'y'", query="same", paths=("a",), strategy="static"), "run_id": "run-two"},
        ])
        summary = summarize_analyses([dynamic, static])
        self.assertEqual(summary["dynamic_retrieval"]["query_change_rate"], 1)
        self.assertEqual(summary["static_retrieval"]["query_change_rate"], 0)

    def test_directory_loader_keeps_each_runs_file_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "trial" / "runs.jsonl"
            path.parent.mkdir()
            rows = [
                row(1, "by exact x", "unknown_identifier", "error: unknown identifier 'x'"),
                row(2, "by trivial", "ok", ""),
            ]
            path.write_text("\n".join(json.dumps(item) for item in rows), encoding="utf-8")
            self.assertEqual(len(load_trace_files([base])), 1)


if __name__ == "__main__":
    unittest.main()
