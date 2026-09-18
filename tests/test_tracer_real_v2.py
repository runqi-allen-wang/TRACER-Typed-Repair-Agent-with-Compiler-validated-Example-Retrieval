import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_feedback import validate_config, validate_preregistration_record  # noqa: E402
from tracer_real_v2 import (  # noqa: E402
    audit_enrollment, build_final_preregistration, read_json,
    validate_candidate_inventory, validate_contract, validate_enrollment_preregistration,
    validate_candidate_scans, validate_candidate_screen_reports, validate_v2_benchmark,
)


CONTRACT_PATH = ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json"
ENROLLMENT_PATH = ROOT / "experiments/preregistrations/tracer_real_causal_v2_enrollment.json"
CONFIG_PATH = ROOT / "experiments/causal_feedback.tracer_real_v2.json"
CANDIDATES_PATH = ROOT / "benchmarks/real_repairs/tracer_real_v2.candidates.json"
CANDIDATE_SCANS = ROOT / "benchmarks/real_repairs/tracer_real_v2_candidates"
CANDIDATE_SCREENING = ROOT / "benchmarks/real_repairs/tracer_real_v2_screening"


def synthetic_v2_benchmark() -> dict:
    definitions = [
        ("mathlib", "development", 3),
        ("batteries", "validation", 4),
        ("aesop", "validation", 4),
        *[(f"heldout_{index}", "test", 8) for index in range(1, 6)],
    ]
    categories = ("unknown_identifier", "type_mismatch", "unsolved_goals", "elaboration")
    projects = []
    environments = []
    problems = []
    for project_id, split, count in definitions:
        repository = f"https://example.invalid/{project_id}"
        source_version = f"tracer-real-{project_id}-v2"
        projects.append({
            "project_id": project_id,
            "split": split,
            "source_benchmark_version": source_version,
            "source_repository": repository,
            "tasks": count,
        })
        environments.append({
            "project_id": project_id,
            "project_root": f"project_environments/{project_id}",
            "lean_toolchain": "leanprover/lean4:v4.32.0",
        })
        for offset in range(count):
            problem_id = f"{project_id}_case_{offset + 1}"
            problems.append({
                "id": problem_id,
                "file": f"tasks/{project_id}/{problem_id}.lean",
                "theorem": f"Demo.{problem_id}",
                "tags": ["real_history", categories[offset % len(categories)]],
                "difficulty": "natural-contextual-repair",
                "expected_error": categories[offset % len(categories)],
                "source_text": "theorem demo : True :=\n  -- PROOF_START\n  by exact missing\n  -- PROOF_END\n",
                "project_id": project_id,
                "split": split,
                "source_benchmark_version": source_version,
                "provenance": {
                    "source_repository": repository,
                    "statement_unchanged": True,
                    "initial_failure_reproduced": True,
                    "fixed_proof_recompiled": True,
                },
            })
    return {
        "version": "tracer-real-v2",
        "status": "frozen-project-disjoint-real-history",
        "license": "Each task retains its upstream license.",
        "description": "test fixture",
        "lean_toolchain": "leanprover/lean4:v4.32.0",
        "split_policy": "upstream_project_disjoint",
        "projects": projects,
        "project_environments": environments,
        "problems": problems,
    }


class TracerRealV2Test(unittest.TestCase):
    def setUp(self):
        self.contract = read_json(CONTRACT_PATH)
        self.enrollment = read_json(ENROLLMENT_PATH)
        self.config = validate_config(CONFIG_PATH)
        self.candidates = read_json(CANDIDATES_PATH)

    def test_enrollment_contract_and_preregistration_are_frozen(self):
        validate_contract(self.contract)
        validate_enrollment_preregistration(self.enrollment, self.contract, self.config)
        validate_candidate_inventory(self.candidates, self.contract)
        scans = validate_candidate_scans(self.candidates, CANDIDATE_SCANS)
        self.assertEqual(scans["candidate_scans"], 6)
        self.assertEqual(scans["history_candidates"], 1576)
        screening = validate_candidate_screen_reports(
            self.candidates, CANDIDATE_SCANS, CANDIDATE_SCREENING,
        )
        self.assertEqual(screening["screened_projects"], 1)
        self.assertEqual(screening["screened_candidates"], 51)
        self.assertEqual(screening["accepted_repairs"], 16)
        result = audit_enrollment(CONTRACT_PATH, ENROLLMENT_PATH, CONFIG_PATH)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready_for_provider_run"])
        self.assertFalse(result["provider_calls_allowed"])
        self.assertEqual(result["candidate_projects_frozen"], 6)
        self.assertEqual(result["candidate_history_window"], 120)
        self.assertEqual(result["history_candidates"], 1576)
        self.assertEqual(result["screened_projects"], 1)
        self.assertEqual(result["screened_candidates"], 51)
        self.assertEqual(result["accepted_repairs"], 16)

    def test_final_audit_requires_complete_screening_reports(self):
        with self.assertRaisesRegex(ValueError, "全部候选项目"):
            audit_enrollment(
                CONTRACT_PATH, ENROLLMENT_PATH, CONFIG_PATH,
                benchmark_path=ROOT / "benchmarks/real_repairs/tracer_real_v1/manifest.json",
            )

    def test_finalize_cli_cannot_bypass_complete_screening_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "src/tracer_real_v2.py"), "finalize",
                    "--benchmark", str(ROOT / "benchmarks/real_repairs/tracer_real_v1/manifest.json"),
                    "--experiment-id", "must-not-be-created",
                    "--out", str(Path(raw) / "forbidden.json"),
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("全部候选项目", completed.stdout)
            self.assertFalse((Path(raw) / "forbidden.json").exists())

    def test_screening_report_cannot_omit_a_frozen_candidate(self):
        report = read_json(CANDIDATE_SCREENING / "leanapap.screen.json")
        report["decisions"].pop()
        with tempfile.TemporaryDirectory() as raw:
            screen_dir = Path(raw)
            (screen_dir / "leanapap.screen.json").write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "唯一覆盖"):
                validate_candidate_screen_reports(
                    self.candidates, CANDIDATE_SCANS, screen_dir,
                )

    def test_candidate_inventory_rejects_v1_repository_alias(self):
        candidates = json.loads(json.dumps(self.candidates))
        candidates["projects"][0]["source_repository"] = "https://github.com/leanprover-community/mathlib4.git/"
        with self.assertRaisesRegex(ValueError, "复用 v1"):
            validate_candidate_inventory(candidates, self.contract)

    def test_synthetic_complete_manifest_passes_all_enrollment_gates(self):
        result = validate_v2_benchmark(synthetic_v2_benchmark(), self.contract)
        self.assertTrue(result["ready"])
        self.assertEqual(result["projects"], 8)
        self.assertEqual(result["test_projects"], 5)
        self.assertEqual(result["tasks"], 51)
        self.assertEqual(result["test_tasks"], 40)

    def test_v1_project_cannot_reenter_v2_test_split(self):
        benchmark = synthetic_v2_benchmark()
        mathlib = next(row for row in benchmark["projects"] if row["project_id"] == "mathlib")
        mathlib["split"] = "test"
        for problem in benchmark["problems"]:
            if problem["project_id"] == "mathlib":
                problem["split"] = "test"
        with self.assertRaisesRegex(ValueError, "v1 已使用项目"):
            validate_v2_benchmark(benchmark, self.contract)

    def test_v1_repository_cannot_reenter_test_under_new_name(self):
        benchmark = synthetic_v2_benchmark()
        heldout = next(row for row in benchmark["projects"] if row["project_id"] == "heldout_1")
        heldout["source_repository"] = "https://github.com/leanprover-community/mathlib4.git/"
        for problem in benchmark["problems"]:
            if problem["project_id"] == "heldout_1":
                problem["provenance"]["source_repository"] = heldout["source_repository"]
        with self.assertRaisesRegex(ValueError, "上游仓库"):
            validate_v2_benchmark(benchmark, self.contract)

    def test_project_dominance_gate_rejects_unbalanced_test_set(self):
        benchmark = synthetic_v2_benchmark()
        dominant = next(row for row in benchmark["projects"] if row["project_id"] == "heldout_1")
        source = next(row for row in benchmark["problems"] if row["project_id"] == "heldout_1")
        for offset in range(10):
            clone = json.loads(json.dumps(source))
            clone["id"] = f"heldout_1_extra_{offset}"
            clone["file"] = f"tasks/heldout_1/{clone['id']}.lean"
            benchmark["problems"].append(clone)
            dominant["tasks"] += 1
        with self.assertRaisesRegex(ValueError, "过度主导"):
            validate_v2_benchmark(benchmark, self.contract)

    def test_finalizer_emits_runner_compatible_exact_preregistration(self):
        benchmark = synthetic_v2_benchmark()
        final = build_final_preregistration(
            self.contract,
            self.enrollment,
            self.config,
            benchmark,
            experiment_id="tracer-real-causal-v2-test",
            registered_at_utc="2026-09-16T00:00:00Z",
        )
        self.assertEqual(final["stopping_rule"]["maximum_seed_generations"], 120)
        self.assertEqual(final["stopping_rule"]["maximum_branch_generations"], 960)
        self.assertEqual(final["stopping_rule"]["maximum_provider_calls"], 1080)
        self.assertTrue(final["claim_gate"]["confirmatory_claim_allowed"])
        validate_preregistration_record(final, self.config, benchmark)

    def test_finalizer_refuses_to_overstate_current_v1_inventory(self):
        current = read_json(ROOT / "benchmarks/real_repairs/tracer_real_v1/manifest.json")
        current["version"] = "tracer-real-v2"
        with self.assertRaises(ValueError):
            validate_v2_benchmark(current, self.contract)


if __name__ == "__main__":
    unittest.main()
