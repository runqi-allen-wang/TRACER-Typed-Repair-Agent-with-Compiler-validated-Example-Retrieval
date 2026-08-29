"""证明输出协议、截断、警告与旧批次兼容性；不进行模型 API 调用。"""
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

from agent import PROMPT_TEMPLATES, canonical_request, prompt_for, solve_problem
from compiler import compile_candidate
from diagnostics import normalize_diagnostics
from proof_protocol import LEGACY_PROTOCOL_VERSION, PROOF_PROTOCOL
from provider import Generation, MockProvider, parse_generation
from research import build_plan, load_benchmark, load_config, load_trials, summarize, trial_path, valid_protocol_record, write_json

LEAN_TIMEOUT = float(os.environ.get("TRACER_TEST_LEAN_TIMEOUT", "120"))


class TruncatedProvider:
    name = "test_only"

    def __init__(self, content=""):
        self.content = content
        self.prompts = []

    def metadata(self):
        return {"provider": self.name}

    def generate(self, prompt):
        self.prompts.append(prompt)
        return Generation(self.content, {"completion_tokens": 12, "total_tokens": 20}, self.name,
                          {"choices": [{"finish_reason": "length"}]})


class ProofProtocolTest(unittest.TestCase):
    def solve(self, base, provider, rounds=1, source=None, condition="B"):
        path = base / "task.lean"
        path.write_text(source or "import Std\ntheorem target : True := sorry\n", encoding="utf-8")
        return solve_problem(path, "target", condition, provider, rounds, LEAN_TIMEOUT, ROOT / "examples",
                             base / "cache", base / "solutions", base / "runs.jsonl",
                             use_cache=False, record_prompt=True)

    def test_all_arms_share_whole_proof_contract(self):
        source = "theorem target : True := by trivial"
        contracts = []
        for arm in "ABCD":
            prompt = prompt_for(source, "target", arm, {"feedback": "PRIVATE_DIAGNOSTIC"}, [])
            contracts.append(prompt.split("输出协议：")[1])
            self.assertIn("完整替换", prompt)
            self.assertIn("必须以 by 开始", prompt)
            self.assertIn("所有分支", prompt)
            self.assertEqual(prompt.count(source), 1)
            if arm in "AD":
                self.assertNotIn("PRIVATE_DIAGNOSTIC", prompt)
        self.assertEqual(len(set(contracts)), 1)

    def test_custom_markers_and_frozen_templates(self):
        templates = {name: (ROOT / "prompts" / name).read_text(encoding="utf-8")
                     for name in set(PROMPT_TEMPLATES.values()) | {"proof_contract.txt"}}
        with patch("pathlib.Path.read_text", side_effect=AssertionError("不得读取运行中模板")):
            prompt = prompt_for("theorem target : True := sorry", "target", "B", {}, [],
                                start_marker="BEGIN", end_marker="END", prompt_templates=templates)
        self.assertIn("BEGIN 与 END", prompt)

    def test_request_text_includes_readable_protocol(self):
        request = json.loads(canonical_request("prompt", "A", {"model": "test"}))
        self.assertEqual(request["proof_protocol"], PROOF_PROTOCOL)

    def test_null_content_is_empty_not_identifier(self):
        result = parse_generation(json.dumps({"choices": [{"message": {"content": None}, "finish_reason": "length"}]}), "test")
        self.assertEqual(result.candidate, "")
        self.assertEqual(result.raw["choices"][0]["finish_reason"], "length")

    def test_non_text_content_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_generation('{"choices":[{"message":{"content":{}}}]}', "test")

    def test_truncated_generation_not_compiled_even_with_code(self):
        for content in ("", "by trivial"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                with patch("agent.compile_candidate") as compiler:
                    result = self.solve(Path(directory), TruncatedProvider(content))
                compiler.assert_not_called()
                self.assertEqual(result["diagnostic"]["category"], "generation_truncated")
                self.assertEqual(result["generation_status"], "truncated")
                self.assertFalse(result["compile_ok"])
                self.assertIsNone(result["kernel_pass"])
                self.assertEqual(result["usage"]["completion_tokens"], 12)
                self.assertTrue(valid_protocol_record(result))

    def test_truncation_uses_three_rounds_without_changing_generation_budget(self):
        for arm in "AB":
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as directory:
                provider = TruncatedProvider()
                result = self.solve(Path(directory), provider, rounds=3, condition=arm)
                self.assertEqual(result["round"], 3)
                self.assertEqual(len(provider.prompts), 3)
                if arm == "B":
                    self.assertIn("被输出额度截断", provider.prompts[1])
                else:
                    self.assertEqual(provider.prompts[0], provider.prompts[1])

    def test_complete_empty_output_is_not_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.solve(Path(directory), MockProvider(""))
            self.assertEqual(result["diagnostic"]["category"], "invalid_candidate")
            self.assertNotEqual(result["generation_status"], "truncated")

    def test_warnings_are_recorded_separately(self):
        text = "task.lean:1:2: warning: This simp argument is unused:\n  Nat.add_comm\nHint: Omit it"
        result = normalize_diagnostics(text, returncode=0)
        self.assertEqual(result["category"], "ok")
        self.assertEqual(result["warning_count"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["errors"], [])

    def test_real_lean_linter_does_not_reject_valid_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result = self.solve(base, MockProvider("by simp [Nat.add_comm]"),
                                source="import Std\ntheorem target (n : Nat) : n = n := sorry\n")
            self.assertTrue(result["compile_ok"], result)
            self.assertTrue(result["kernel_pass"])
            self.assertTrue(result["compile_has_warnings"])
            self.assertFalse(result["warning_free"])
            self.assertTrue(valid_protocol_record(result))
            self.assertEqual(len(list((base / "solutions/B").glob("*.lean"))), 1)

    def test_sorry_warning_remains_fatal_without_warning_as_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.lean"
            source = "import Std\ntheorem target : True := sorry\n"
            path.write_text(source, encoding="utf-8")
            result = compile_candidate(path, source, "by exact sorryAx _ true", "target", timeout=LEAN_TIMEOUT)
            self.assertFalse(result.ok)
            self.assertIn("未完成证明", result.diagnostics)

    def test_real_lean_tail_only_rejected_but_complete_region_passes(self):
        source = (ROOT / "benchmarks/repair24/tasks/exists_and.lean").read_text(encoding="utf-8")
        source = source.replace("exists_and", "target").replace("namespace Repair24", "").replace("end Repair24", "")
        full = "by\n  constructor\n  · rintro ⟨x, hp, hq⟩\n    exact ⟨⟨x, hp⟩, hq⟩\n  · rintro ⟨⟨x, hp⟩, hq⟩\n    exact ⟨x, hp, hq⟩"
        for proof, expected in [("rcases h with ⟨⟨x, hp⟩, hq⟩; exact ⟨x, hp, hq⟩", False), (full, True)]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                result = self.solve(Path(directory), MockProvider(proof), source=source)
                self.assertEqual(result["compile_ok"], expected, result)
                self.assertEqual(result["candidate"], proof)

    def make_trace(self, base, current=False):
        config = load_config(ROOT / "experiments/research.example.json")
        config.update(models=config["models"][:1], arms=["B"], repeats=1, max_rounds=1)
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        benchmark["problems"] = benchmark["problems"][:1]
        tasks = build_plan(config, benchmark)
        plan = {"experiment_id": "test", "config": config, "benchmark_version": benchmark["version"], "tasks": tasks}
        if current:
            plan["proof_protocol"] = dict(PROOF_PROTOCOL)
        write_json(base / "plan.json", plan)
        write_json(base / "benchmark.json", benchmark)
        task, model = tasks[0], config["models"][0]
        dest = trial_path(base, task)
        write_json(dest / "trial.json", {**task, "experiment_id": "test", "compile_ok": False, "error": None, "elapsed_ms": 10})
        row = {"run_id": "run", "experiment_id": "test", "problem_id": task["problem_id"], "condition": "B",
               "round": 1, "compile_ok": False, "cache_hit": False, "provider": "openai_compatible",
               "retrieval_strategy": "static", "usage": {"total_tokens": 12}, "estimated_cost_usd": None,
               "candidate": "", "provider_response": {"finish_reason": "length"},
               "diagnostic": {"category": "generation_truncated" if current else "invalid_candidate"},
               "provider_config": {"url": model["api_url"], **{k: model[k] for k in ("model", "temperature", "max_tokens")}}}
        if current:
            row.update(proof_protocol=dict(PROOF_PROTOCOL), generation_status="truncated", compile_invoked=False,
                       kernel_pass=None, compile_has_warnings=None, warning_free=None)
        (dest / "runs.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        return dest, row

    def test_legacy_report_keeps_strict_outcome_and_unknown_warning_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dest, row = self.make_trace(base)
            before = (dest / "runs.jsonl").read_bytes()
            result = summarize(base)
            self.assertEqual(result["protocol_version"], LEGACY_PROTOCOL_VERSION)
            self.assertEqual(result["summary"][0]["success"], 0)
            self.assertIsNone(result["summary"][0]["warning_free_success"])
            self.assertEqual(result["summary"][0]["generation_truncated_calls"], 1)
            self.assertEqual((dest / "runs.jsonl").read_bytes(), before)

    def test_current_report_counts_truncation_and_rejects_policy_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.make_trace(base, current=True)
            result = summarize(base)
            self.assertTrue(result["trajectory_valid"])
            self.assertEqual(result["summary"][0]["failed_attempt_categories"], {"generation_truncated": 1})
            plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
            del plan["proof_protocol"]
            write_json(base / "plan.json", plan)
            self.assertTrue(load_trials(base)[2])

    def test_unknown_protocol_and_inconsistent_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dest, row = self.make_trace(base, current=True)
            bad = copy.deepcopy(row)
            bad["compile_ok"] = True
            self.assertFalse(valid_protocol_record(bad))
            bad = copy.deepcopy(row)
            bad["generation_status"] = "complete"
            self.assertFalse(valid_protocol_record(bad))
            plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
            plan["proof_protocol"]["version"] = "unknown"
            write_json(base / "plan.json", plan)
            self.assertTrue(load_trials(base)[2])
