import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_feedback import (  # noqa: E402
    ARMS, _prompt_source, branch_prompt, build_plan, donor_map, intervention_for, run_matrix, summarize,
    validate_config, validate_preregistration, validate_protocol,
)
from compiler_feedback import build_feedback_record  # noqa: E402
from error_state_graph import build_error_state_graph  # noqa: E402
from research import load_benchmark  # noqa: E402
from compiler import CompileResult, FileCompileResult  # noqa: E402
from provider import Generation  # noqa: E402


def seed(problem_id, unknown):
    seed_id = f"model/r1/{problem_id}"
    raw = f"{problem_id}.lean:4:3: error: unknown identifier '{unknown}'"
    record = build_feedback_record(
        case_id=seed_id, diagnostic_text=raw, compile_ok=False, returncode=1,
    )
    graph = build_error_state_graph(
        record, theorem_name=f"Demo.{problem_id}",
        source_text="import Std\n\nnamespace Demo\n\ntheorem target : True := by trivial\nend Demo\n",
        candidate=f"by exact {unknown}",
    )
    return {
        "model_id": "model", "repeat": 1, "problem_id": problem_id,
        "seed_id": seed_id, "candidate": f"by exact {unknown}",
        "eligible_first_failure": True,
        "diagnostic": record["normalized"],
        "feedback_record": record,
        "error_state_graph": graph,
    }


class CausalFeedbackTest(unittest.TestCase):
    def test_tracer_real_preregistration_freezes_project_test_split(self):
        config = validate_config(ROOT / "experiments/causal_feedback.tracer_real_v1.json")
        benchmark = load_benchmark(ROOT / "benchmarks/real_repairs/tracer_real_v1/manifest.json")
        prereg = validate_preregistration(
            ROOT / "experiments/preregistrations/tracer_real_causal_v1.json", config, benchmark,
        )
        plan = build_plan(config, benchmark)
        self.assertEqual(prereg["benchmark"]["version"], "tracer-real-v1")
        self.assertEqual(len(plan["seed_tasks"]), 12)
        self.assertEqual(plan["selected_projects"], ["aesop"])
        self.assertTrue(all(task["split"] == "test" for task in plan["seed_tasks"]))

    def test_preregistration_rejects_design_drift(self):
        config = validate_config(ROOT / "experiments/causal_feedback.tracer_real_v1.json")
        benchmark = load_benchmark(ROOT / "benchmarks/real_repairs/tracer_real_v1/manifest.json")
        config["repeats"] = 2
        with self.assertRaisesRegex(ValueError, "设计"):
            validate_preregistration(
                ROOT / "experiments/preregistrations/tracer_real_causal_v1.json", config, benchmark,
            )

    def test_long_source_keeps_target_and_complete_first_candidate(self):
        source = "import Std\n\n" + ("-- earlier context\n" * 1000) + '''namespace Demo
theorem target (p : Prop) : p → p := by
  -- PROOF_START
  exact missing
  -- PROOF_END
end Demo
'''
        problem = {"source_text": source, "theorem": "Demo.target"}
        view = _prompt_source(problem, limit=1000)
        self.assertLessEqual(len(view), 1000)
        self.assertIn("theorem target", view)
        self.assertIn("import Std", view)
        candidate = "by\n  " + "exact id\n  " * 800
        seed_row = {"seed_id": "m/r1/p", "candidate": candidate}
        intervention = {
            "target_seed_id": seed_row["seed_id"], "payload": "feedback",
            "retrieved_examples": [],
        }
        prompt = branch_prompt(problem, seed_row, intervention)
        self.assertIn(candidate, prompt)

    def test_protocol_and_plan_are_frozen_and_offline(self):
        protocol = validate_protocol()
        config = validate_config(ROOT / "experiments/causal_feedback.example.json")
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        plan = build_plan(config, benchmark)
        self.assertEqual(protocol["arms"], list(ARMS))
        self.assertEqual(len(plan["seed_tasks"]), 72)
        self.assertEqual(plan["maximum_branch_tasks"], 576)
        self.assertEqual(plan["maximum_generations"], 648)

    def test_negative_controls_use_other_same_category_task(self):
        left, right = seed("left", "missingLeft"), seed("right", "missingRight")
        mapping = donor_map([left, right], distinct_signals=True)
        self.assertEqual(mapping[left["seed_id"]], right["seed_id"])
        counterfactual = intervention_for("counterfactual", left, donor=right)
        self.assertEqual(counterfactual["donor_seed_id"], right["seed_id"])
        self.assertNotIn("missingLeft", counterfactual["payload"])
        self.assertIn("missingRight", counterfactual["payload"])
        irrelevant = intervention_for("irrelevant_matched", left, donor=right)
        self.assertIn("right.lean", irrelevant["payload"])

    def test_counterfactual_without_distinct_donor_is_not_available(self):
        left, right = seed("left", "same"), seed("right", "same")
        self.assertNotIn(left["seed_id"], donor_map([left, right], distinct_signals=True))
        result = intervention_for("counterfactual", left, donor=None)
        self.assertFalse(result["available"])

    def test_all_branch_prompts_include_exact_same_first_candidate(self):
        target, donor = seed("left", "missingLeft"), seed("right", "missingRight")
        problem = {"source_text": "theorem target : True := by trivial"}
        prompts = []
        for arm in ARMS:
            intervention = intervention_for(
                arm, target, donor=donor if arm in {"irrelevant_matched", "counterfactual"} else None,
                examples=[{"path": "example.lean", "snippet": "by trivial"}] if arm in {"retrieval_only", "adaptive"} else [],
            )
            prompts.append(branch_prompt(problem, target, intervention))
        self.assertTrue(all(target["candidate"] in prompt for prompt in prompts))

    def test_summary_does_not_claim_formal_causality(self):
        left = seed("left", "missingLeft")
        rows = [
            {"seed_id": left["seed_id"], "arm": arm, "status": "complete",
             "compile_ok": arm == "true_structured", "same_first_candidate": True,
             "first_candidate": left["candidate"],
             "independent_compile_ok": True if arm == "true_structured" else None}
            for arm in ARMS
        ]
        result = summarize([left], rows)
        self.assertTrue(result["same_first_candidate_invariant"])
        self.assertTrue(result["successful_proof_recompile_invariant"])
        self.assertIn("描述", result["claim_boundary"])
        self.assertEqual(result["by_arm"]["true_structured"]["success"], 1)

    def test_offline_runner_branches_from_exact_seed(self):
        class OfflineProvider:
            name = "offline"

            def metadata(self):
                return {"provider": "offline", "model": "offline-test", "temperature": 0, "max_tokens": 100}

            def generate(self, prompt):
                if "冻结首轮生成" in prompt:
                    missing = "missingLeft" if "left" in prompt else "missingRight"
                    text = "by exact " + missing
                else:
                    text = "by trivial"
                return Generation(
                    text,
                    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "offline",
                    {"choices": [{"finish_reason": "stop"}], "model": "offline-test"},
                )

        def fake_compile(_path, _source, candidate, _theorem, **_kwargs):
            if "missing" in candidate:
                missing = "missingLeft" if "missingLeft" in candidate else "missingRight"
                return CompileResult(False, 1.0, f"Demo.lean:4:3: error: unknown identifier '{missing}'", "", False, 1, ["lean"])
            return CompileResult(True, 1.0, "", "", False, 0, ["lean"])

        with TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir = root / "tasks"
            task_dir.mkdir()
            problems = []
            for name in ("left", "right"):
                source = f"import Std\nnamespace Demo\ntheorem {name} : True :=\n  -- PROOF_START\n  by exact missingOriginal\n  -- PROOF_END\nend Demo\n"
                (task_dir / f"{name}.lean").write_text(source, encoding="utf-8")
                problems.append({
                    "id": name, "file": f"tasks/{name}.lean", "theorem": f"Demo.{name}",
                    "tags": ["test"], "difficulty": "test", "expected_error": "unknown_identifier",
                    "source_text": source,
                })
            benchmark = {"version": "offline-causal-v1", "status": "test", "license": "MIT", "problems": problems}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(benchmark), encoding="utf-8")
            config = validate_config(ROOT / "experiments/causal_feedback.example.json")
            config["models"] = [{**config["models"][0], "id": "offline", "model": "offline-test"}]
            config["repeats"] = 1
            out = root / "out"
            with patch("causal_feedback._providers", return_value={"offline": OfflineProvider()}), \
                 patch("causal_feedback.compile_candidate", side_effect=fake_compile), \
                 patch("causal_feedback.run_lean_file", return_value=FileCompileResult(True, 1.0, "", False, 0, ["lean"])):
                result = run_matrix(config, manifest, out)
            self.assertEqual(result["eligible_first_failures"], 2)
            self.assertEqual(result["branch_results"], 16)
            self.assertTrue(result["same_first_candidate_invariant"])
            self.assertTrue(all(item["matched_pairs"] == 2 for item in result["paired_comparisons"]))


if __name__ == "__main__":
    unittest.main()
