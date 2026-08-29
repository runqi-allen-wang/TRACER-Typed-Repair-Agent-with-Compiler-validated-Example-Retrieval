"""研究扩展的条件隔离、矩阵、轨迹门禁和度量回归测试。"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import estimate_cost, prompt_for, solve_problem
from compiler import CompileResult
from provider import Generation
from retriever import Example, diagnostic_query, find_retrieval_leaks, load_examples, retrieve
from research import ARMS, build_plan, load_benchmark, load_config, load_trials, run_matrix, summarize, trial_path, write_json
from capsule_metrics import reduction, summarize_diagnoses, summarize_replays


class CapturingProvider:
    name = "test_sequence"

    def __init__(self):
        self.prompts = []

    def metadata(self):
        return {"provider": self.name, "test_only": True}

    def generate(self, prompt):
        self.prompts.append(prompt)
        return Generation("by trivial", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, self.name)


class ResearchTest(unittest.TestCase):
    def test_frozen_corpora_do_not_overlap_repair_statements(self):
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        statements = [(p["id"], p["source_text"]) for p in benchmark["problems"]]
        corpus = json.loads((ROOT / "experiments/failure_notes.json").read_text(encoding="utf-8"))
        self.assertEqual(find_retrieval_leaks(statements, load_examples(ROOT / "examples")), [])
        self.assertEqual(find_retrieval_leaks(statements, [Example(e["path"], (), e["failure_context"]) for e in corpus["examples"]]), [])

    def test_matrix_complete_repeated_and_order_reproducible(self):
        config = load_config(ROOT / "experiments/research.example.json")
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        plan = build_plan(config, benchmark)
        self.assertEqual(len(plan), 864)
        self.assertEqual(len({tuple(task.values()) for task in plan}), 864)
        self.assertEqual(plan, build_plan(config, benchmark))
        self.assertNotEqual(plan, build_plan(dict(config, order_seed=1), benchmark))

    def test_config_rejects_plaintext_key_and_credential_url(self):
        config = json.loads((ROOT / "experiments/research.example.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            bad = copy.deepcopy(config)
            bad["models"][0]["api_key"] = "fake-test-only"
            write_json(path, bad)
            with self.assertRaises(ValueError):
                load_config(path)
            bad = copy.deepcopy(config)
            bad["models"][0]["api_url"] = "https://user:password@example.org/v1"
            write_json(path, bad)
            with self.assertRaises(ValueError):
                load_config(path)

    def test_frozen_source_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "task.lean").write_text("changed", encoding="utf-8")
            write_json(base / "manifest.json", {"version": "test", "problems": [
                {"id": "one", "file": "task.lean", "source_text": "original"}]})
            with self.assertRaisesRegex(ValueError, "冻结源码"):
                load_benchmark(base / "manifest.json")

    def test_retrieval_excludes_renamed_binders(self):
        source = "theorem t (p : Prop) : p → p := by intro h; exact h"
        example = Example("same", (), "example (q : Prop) : q → q := by intro h; exact h")
        self.assertEqual(retrieve(source, [example]), [])

    def test_diagnostic_query_changes_ranking_and_keeps_goal(self):
        examples = [Example("a", ("arithmetic",), "Nat.add_comm"),
                    Example("b", ("lists",), "List.reverse_append")]
        target = "theorem target : True := by trivial"
        query1, focus1 = diagnostic_query(target, {"category": "unknown_identifier"}, "unknown constant List.reverse_append")
        query2, focus2 = diagnostic_query(target, {"category": "unsolved_goals"}, "⊢ Nat.add_comm")
        self.assertNotEqual(query1, query2)
        self.assertEqual(retrieve(query1, examples, focus=focus1)[0]["path"], "b")
        self.assertEqual(retrieve(query2, examples, focus=focus2)[0]["path"], "a")
        self.assertIn("⊢", query2)

    def test_diagnostic_query_redacts_local_paths(self):
        query, _ = diagnostic_query("target", {"category": "type_mismatch"}, r"C:\Users\Somebody\secret.lean:1:2")
        self.assertNotIn("Somebody", query)

    def test_path_redaction_preserves_provider_https_url(self):
        from leancapsule.privacy import redact_value
        value = {"url": "https://api.deepseek.com/chat/completions", "path": r"C:\Users\Somebody\source.lean"}
        public = redact_value(value)
        self.assertEqual(public["url"], value["url"])
        self.assertNotIn("Somebody", public["path"])

    def test_retrieval_only_does_not_expose_feedback(self):
        source = "theorem test : True := by trivial"
        prompt = prompt_for(source, "test", "D", {"feedback": "PRIVATE_DIAGNOSTIC"}, [{"snippet": "example"}])
        self.assertNotIn("PRIVATE_DIAGNOSTIC", prompt)
        self.assertIn("example", prompt)

    def test_dynamic_not_allowed_for_retrieval_only(self):
        with self.assertRaisesRegex(ValueError, "D 不得读取诊断"):
            solve_problem(Path("unused"), "test", "D", CapturingProvider(), 3, 10,
                          ROOT / "examples", Path("unused"), Path("unused"), Path("unused"),
                          retrieval_strategy="diagnostic")

    def test_failure_then_success_changes_dynamic_query_not_d_prompt(self):
        for condition, strategy in [("C", "diagnostic"), ("D", "static")]:
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                source = base / "source.lean"
                source.write_text("theorem target : True :=\n -- PROOF_START\n by trivial\n -- PROOF_END\n", encoding="utf-8")
                examples = base / "examples"
                examples.mkdir()
                (examples / "list.lean").write_text("-- tags: List reverse_append\nexample : 1 = 1 := rfl", encoding="utf-8")
                provider = CapturingProvider()
                compiled = [CompileResult(False, 1, "unknown identifier List.reverse_append", "", False, 1),
                            CompileResult(True, 1, "", "theorem target : True := by trivial\n", False, 0)]
                with patch("agent.compile_candidate", side_effect=compiled):
                    result = solve_problem(source, "target", condition, provider, 3, 10, examples,
                        base / "cache", base / "solutions", base / "runs.jsonl",
                        retrieval_strategy=strategy, use_cache=False, record_prompt=True)
                rows = [json.loads(line) for line in (base / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertTrue(result["compile_ok"])
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(not row["cache_hit"] for row in rows))
                if condition == "D":
                    self.assertEqual(provider.prompts[0], provider.prompts[1])
                    self.assertEqual(rows[0]["retrieval_query"], rows[1]["retrieval_query"])
                else:
                    self.assertNotEqual(rows[0]["retrieval_query"], rows[1]["retrieval_query"])
                    self.assertIn("上一轮候选", provider.prompts[1])

    def test_cost_unknown_is_not_zero(self):
        self.assertIsNone(estimate_cost({}, {"input_price_per_1k": 1, "output_price_per_1k": 2}))
        self.assertIsNone(estimate_cost({"prompt_tokens": 10, "completion_tokens": 20}, {"input_price_per_1k": 1}))
        self.assertEqual(estimate_cost({"prompt_tokens": 1000, "completion_tokens": 1000},
                                      {"input_price_per_1k": 1, "output_price_per_1k": 2}), 3)

    def test_production_runner_does_not_read_reference_proofs(self):
        code = (ROOT / "src/research.py").read_text(encoding="utf-8")
        self.assertNotIn("fixtures/", code)
        self.assertNotIn("repair24_reference.json", code)

    def test_real_lean_matrix_saves_proofs_and_validates_without_network(self):
        config = load_config(ROOT / "experiments/research.example.json")
        config.update(models=config["models"][:1], repeats=1, arms=["A", "B", "C", "D", "C_dynamic", "C_failure"])
        config["models"][0]["model"] = "offline-test-only"
        manifest_path = ROOT / "benchmarks/repair24/manifest.json"
        benchmark = load_benchmark(manifest_path)
        benchmark["problems"] = [p for p in benchmark["problems"] if p["id"] == "forall_and"]
        references = json.loads((ROOT / "tests/fixtures/repair24_reference.json").read_text(encoding="utf-8"))

        class OfflineProvider(CapturingProvider):
            name = "openai_compatible"

            def generate(self, prompt):
                self.prompts.append(prompt)
                return Generation(references["forall_and"], {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, self.name)

            def metadata(self):
                model = config["models"][0]
                return {"provider": self.name, "url": model["api_url"],
                        **{k: model[k] for k in ("model", "temperature", "max_tokens")}}

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "research"
            with patch.dict(os.environ, {config["models"][0]["api_key_env"]: "offline-test-only"}), \
                 patch("research.OpenAICompatibleProvider", return_value=OfflineProvider()), \
                 patch("research.load_benchmark", return_value=benchmark):
                self.assertTrue(run_matrix(config, manifest_path, out))
            report = summarize(out)
            self.assertTrue(report["trajectory_valid"])
            self.assertFalse(report["release_ready"])
            self.assertEqual(len(list(out.glob("trials/**/solutions/*/*.lean"))), 6)
            self.assertFalse(list(out.rglob("*.sqlite3")))
            logs = {task["arm"]: [json.loads(s) for s in (trial_path(out, task) / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
                    for task in build_plan(config, benchmark)}
            dynamic, failure = logs["C_dynamic"][0], logs["C_failure"][0]
            self.assertEqual([e["path"] for e in dynamic["retrieved_examples"]], [e["path"] for e in failure["retrieved_examples"]])
            self.assertNotIn("failure_context", json.dumps(dynamic["retrieved_examples"]))
            self.assertIn("failure_context", json.dumps(failure["retrieved_examples"]))

    def test_api_failure_stops_the_matrix(self):
        config = load_config(ROOT / "experiments/research.example.json")
        config.update(models=config["models"][:1], repeats=1, arms=["A", "B"])
        config["models"][0]["model"] = "offline-test-only"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "failed"
            benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
            initial = [{"problem_id": p["id"], "diagnostic": {}, "raw_diagnostics": ""} for p in benchmark["problems"]]
            with patch.dict(os.environ, {config["models"][0]["api_key_env"]: "offline-test-only"}), \
                 patch("research.OpenAICompatibleProvider", return_value=CapturingProvider()), \
                 patch("research.check_benchmark", return_value=initial), \
                 patch("research.solve_problem", return_value={"compile_ok": False, "provider_error": "outage"}) as solve:
                self.assertFalse(run_matrix(config, ROOT / "benchmarks/repair24/manifest.json", out))
                self.assertEqual(solve.call_count, 1)
                self.assertFalse(json.loads((out / "completion.json").read_text())["complete"])

    def make_trace(self, base):
        config = load_config(ROOT / "experiments/research.example.json")
        config.update(models=config["models"][:1], repeats=1, arms=["A"], max_rounds=1)
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        benchmark["problems"] = benchmark["problems"][:1]
        tasks = build_plan(config, benchmark)
        write_json(base / "plan.json", {"experiment_id": "test", "config": config, "benchmark_version": benchmark["version"], "tasks": tasks})
        write_json(base / "benchmark.json", benchmark)
        task = tasks[0]
        dest = trial_path(base, task)
        write_json(dest / "trial.json", {**task, "experiment_id": "test", "compile_ok": False, "error": None, "elapsed_ms": 20})
        model = config["models"][0]
        row = {"run_id": "run", "experiment_id": "test", "problem_id": task["problem_id"], "condition": "A",
               "round": 1, "compile_ok": False, "cache_hit": False, "provider": "openai_compatible",
               "retrieval_strategy": "static", "usage": {"total_tokens": 5}, "estimated_cost_usd": None,
               "provider_config": {"url": model["api_url"], **{k: model[k] for k in ("model", "temperature", "max_tokens")}}}
        (dest / "runs.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        return dest, row

    def test_report_rejects_mixed_experiment_and_cache_reuse(self):
        for field, value in [("experiment_id", "other"), ("cache_hit", True)]:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                dest, row = self.make_trace(base)
                row[field] = value
                (dest / "runs.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "门禁"):
                    summarize(base)

    def test_report_rejects_duplicate_plan_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.make_trace(base)
            plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
            plan["tasks"].append(plan["tasks"][0])
            write_json(base / "plan.json", plan)
            self.assertTrue(load_trials(base)[2])

    def test_report_marks_missing_cost_unknown_and_not_release_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.make_trace(base)
            result = summarize(base)
            self.assertIsNone(result["summary"][0]["total_estimated_cost_usd"])
            self.assertFalse(result["release_ready"])

    def test_missing_trials_cannot_form_formal_report(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dest, _ = self.make_trace(base)
            (dest / "trial.json").unlink()
            with self.assertRaises(ValueError):
                summarize(base)


class CapsuleMetricsTest(unittest.TestCase):
    def row(self, batch, os_name, label):
        return {"batch_id": batch, "case_id": "std/example", "repeat": 1,
                "capsule_source": "source", "environment": {"os": os_name, "release": "1", "architecture": "x64",
                "actual_lean": "4.32.0", "label": label}, "size": {"original": None},
                "replay": {"ok": True, "elapsed_ms": 10}}

    def test_labels_do_not_create_fake_environments(self):
        result = summarize_replays([self.row("1", "Windows", "a"), self.row("2", "Windows", "b")])
        self.assertFalse(result["cross_environment_observed"])
        self.assertEqual(result["distinct_environments"], 1)

    def test_cross_os_requires_matching_case_source(self):
        a, b = self.row("1", "Windows", "a"), self.row("2", "Linux", "b")
        self.assertTrue(summarize_replays([a, b])["cross_environment_observed"])
        b["capsule_source"] = "different"
        with self.assertRaises(ValueError):
            summarize_replays([a, b])

    def test_duplicate_replays_are_rejected(self):
        row = self.row("1", "Windows", "a")
        with self.assertRaises(ValueError):
            summarize_replays([row, row])

    def test_reduction_is_measured_not_inferred(self):
        result = reduction("a\nb\nc\nd\n", "a\nb\n")
        self.assertEqual(result["line_reduction"], 0.5)
        self.assertIsNone(reduction("", "")["line_reduction"])

    def test_pending_human_review_is_not_counted_as_correct(self):
        row = {"session": "s", "participant": "p", "case_id": "c", "representation": "capsule",
               "elapsed_seconds": 2, "correctness": "pending"}
        result = summarize_diagnoses([row])
        self.assertEqual(result["groups"]["capsule"]["pending_review"], 1)
        self.assertEqual(result["groups"]["capsule"]["reviewed_correct"], 0)
        self.assertFalse(result["both_representations"])
