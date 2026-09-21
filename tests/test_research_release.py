import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_research_release import ARMS, FORMAT, audit_release  # noqa: E402
from export_research_release import _public_attempt, _public_plan, _retry_inventory, export_release  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def make_release(root: Path) -> None:
    experiment_id = "research-synthetic-release-test"
    models = [
        {
            "id": "flash", "model": "model-a", "api_url": "https://example.test/chat/completions",
            "temperature": 0, "max_tokens": 12000, "thinking": "enabled", "reasoning_effort": "high",
            "input_price_per_1k": 0.1, "output_price_per_1k": 0.2,
        },
        {
            "id": "pro", "model": "model-b", "api_url": "https://example.test/chat/completions",
            "temperature": 0, "max_tokens": 12000, "thinking": "enabled", "reasoning_effort": "high",
            "input_price_per_1k": 0.3, "output_price_per_1k": 0.4,
        },
    ]
    problem_ids = [f"p{index:02d}" for index in range(24)]
    tasks = [
        {"model_id": model["id"], "repeat": repeat, "arm": arm, "problem_id": problem_id}
        for model in models
        for repeat in range(1, 4)
        for arm in ARMS
        for problem_id in problem_ids
    ]
    config = {
        "models": models,
        "repeats": 3,
        "arms": list(ARMS),
        "max_rounds": 3,
        "compile_timeout": 180,
    }
    plan = {
        "experiment_id": experiment_id,
        "config": config,
        "benchmark_version": "repair24-v1",
        "tasks": tasks,
        "prompt_template_files": [
            "protocol/feedback.txt", "protocol/feedback_retrieval.txt", "protocol/proof_contract.txt",
            "protocol/retrieval_only.txt", "protocol/theorem_only.txt",
        ],
    }
    preregistration = {
        "version": "tracer-repair24-six-arm-preregistration-v1",
        "planned_tasks": 864,
        "max_generations": 2592,
        "primary_comparison": "B - A",
        "config": config,
    }
    benchmark = {
        "version": "repair24-v1",
        "problems": [{"id": problem_id} for problem_id in problem_ids],
    }
    trials: list[dict] = []
    attempts: list[dict] = []
    success_key = ("flash", "1", "A", "p00")
    for index, task in enumerate(tasks):
        key = (task["model_id"], str(task["repeat"]), task["arm"], task["problem_id"])
        success = key == success_key
        solution = None
        if success:
            solution = "solutions/flash/1/A/p00.lean"
        trials.append({
            **task,
            "experiment_id": experiment_id,
            "compile_ok": success,
            "independent_compile_ok": True if success else None,
            "error": None,
            "solution": solution,
        })
        rounds = 1 if success else 3
        runtime = {
            "A": ("A", "static"), "B": ("B", "static"), "C": ("C", "static"),
            "D": ("D", "static"), "C_dynamic": ("C", "diagnostic"), "C_failure": ("C", "diagnostic"),
        }[task["arm"]]
        model = next(item for item in models if item["id"] == task["model_id"])
        for round_number in range(1, rounds + 1):
            attempts.append({
                **task,
                "experiment_id": experiment_id,
                "run_id": f"run-{index}",
                "round": round_number,
                "compile_ok": success and round_number == rounds,
                "provider_error": None,
                "cache_hit": False,
                "provider": "openai_compatible",
                "condition": runtime[0],
                "retrieval_strategy": runtime[1],
                "compile_timed_out": False,
                "provider_config": {
                    "url": model["api_url"],
                    **{field: model[field] for field in (
                        "model", "temperature", "max_tokens", "thinking", "reasoning_effort",
                        "input_price_per_1k", "output_price_per_1k",
                    )},
                },
            })

    write_json(root / "plan.sanitized.json", plan)
    write_json(root / "preregistration.json", preregistration)
    write_json(root / "benchmark.json", benchmark)
    write_json(root / "examples.sanitized.json", [])
    write_json(root / "failure_notes.sanitized.json", {})
    write_json(root / "initial_compilation.sanitized.json", {})
    write_json(root / "completion.sanitized.json", {
        "complete": True,
        "infrastructure_errors": 0,
        "budget": {"attempted_calls": len(attempts)},
    })
    write_json(root / "summary.json", {
        "experiment_id": experiment_id,
        "trajectory_valid": True,
        "full_research_design": True,
        "manual_review_complete": True,
        "release_ready": True,
        "publication_retry_inventory": {"observed_attempt_directories": 0, "observed_round_records": 0},
    })
    write_json(root / "ai_review_report.json", {
        "format": "tracer-research-ai-assisted-review-v1",
        "experiment_id": experiment_id,
        "review_mode": "ai_assisted",
        "tasks": 864,
        "successful_tasks": 1,
        "failed_tasks_not_proof_reviewed": 863,
        "reviewed_successes": 1,
        "successes_with_linter_warnings": 0,
        "checks": ["synthetic independent check"],
        "errors": [],
        "complete": True,
    })
    write_jsonl(root / "trials.jsonl", trials)
    write_jsonl(root / "attempts.sanitized.jsonl", attempts)
    (root / "solutions/flash/1/A").mkdir(parents=True)
    (root / "solutions/flash/1/A/p00.lean").write_text("import Std\ntheorem releaseTest : True := by trivial\n", encoding="utf-8")
    (root / "README.md").write_text("# synthetic release\n", encoding="utf-8")
    (root / "FILES.md").write_text("# files\n", encoding="utf-8")
    protocol = root / "protocol"
    protocol.mkdir()
    for name in ("theorem_only.txt", "feedback.txt", "feedback_retrieval.txt", "retrieval_only.txt", "proof_contract.txt"):
        (protocol / name).write_text("static template\n", encoding="utf-8")
    fields = [
        "experiment_id", "model_id", "repeat", "arm", "problem_id", "kernel_pass",
        "inappropriate_assumption", "leakage_risk", "review_mode", "reviewer_note",
    ]
    with (root / "ai_assisted_review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for task in tasks:
            key = (task["model_id"], str(task["repeat"]), task["arm"], task["problem_id"])
            writer.writerow({
                "experiment_id": experiment_id,
                **task,
                "kernel_pass": "yes" if key == success_key else "",
                "inappropriate_assumption": "no" if key == success_key else "",
                "leakage_risk": "no" if key == success_key else "",
                "review_mode": "ai_assisted",
                "reviewer_note": "synthetic independent check" if key == success_key else "",
            })
    files = sorted(path for path in root.rglob("*") if path.is_file())
    write_json(root / "MANIFEST.json", {
        "format": FORMAT,
        "experiment_id": experiment_id,
        "counts": {
            "tasks": len(trials),
            "attempts": len(attempts),
            "successes": 1,
            "failed_tasks": len(trials) - 1,
            "proof_files": 1,
            "review_rows": len(tasks),
            "reported_retry_attempts": 0,
            "archived_retry_attempts": 0,
            "archived_retry_round_records": 0,
            "attempted_call_reservations": len(attempts),
            "unmatched_call_reservations": 0,
        },
        "files": [
            {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size}
            for path in files
        ],
    })


class ResearchReleaseTest(unittest.TestCase):
    def test_full_synthetic_matrix_passes_static_release_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            release.mkdir()
            make_release(release)
            result = audit_release(release)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual((result["tasks"], result["successes"], result["failed_tasks"]), (864, 1, 863))

    def test_public_records_drop_request_prompt_response_id_and_auth_env(self):
        row = {"prompt": "private", "provider_response": {"id": "remote-id", "model": "m"}, "candidate": "by trivial"}
        self.assertEqual(_public_attempt(row, ROOT), {"provider_response": {"model": "m"}, "candidate": "by trivial"})
        plan = {
            "config": {"models": [{"id": "m", "api_key_env": "SECRET_ENV"}]},
            "preregistration": {"config": {"models": [{"id": "m", "api_key_env": "NESTED_SECRET_ENV"}]}},
            "prompt_templates": {"a.txt": "x"},
        }
        public = _public_plan(plan, ROOT)
        self.assertNotIn("prompt_templates", public)
        self.assertNotIn("api_key_env", public["config"]["models"][0])
        self.assertNotIn("api_key_env", public["preregistration"]["config"]["models"][0])

    def test_retry_inventory_counts_incomplete_attempt_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            attempt = source / "retry_history/m/1/C/p/attempt-1"
            attempt.mkdir(parents=True)
            (attempt / "runs.jsonl").write_text("{}\n{}\n", encoding="utf-8")
            self.assertEqual(_retry_inventory(source), {"attempt_directories": 1, "round_records": 2})

    def test_export_refuses_incomplete_or_unreviewed_run_before_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "run"
            source.mkdir()
            out = Path(directory) / "release"
            with patch("export_research_release.summarize", return_value={"release_ready": False}):
                with self.assertRaisesRegex(ValueError, "AI 辅助复核"):
                    export_release(source, out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
