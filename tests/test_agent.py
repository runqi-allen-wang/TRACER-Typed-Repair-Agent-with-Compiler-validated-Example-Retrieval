import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import prompt_for, solve_problem
from cache import RequestCache
from compiler import compile_candidate, lean_command
from provider import Generation, MockProvider


LEAN_TIMEOUT = float(os.environ.get("TRACER_TEST_LEAN_TIMEOUT", "60"))


class SequenceProvider:
    name = "sequence"

    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = 0

    def metadata(self):
        return {"provider": self.name, "test_case": "feedback_repair"}

    def generate(self, prompt):
        candidate = self.candidates[min(self.calls, len(self.candidates) - 1)]
        self.calls += 1
        return Generation(candidate, {"prompt_tokens": len(prompt), "total_tokens": len(prompt)}, self.name)


class BrokenProvider:
    name = "broken"

    def metadata(self):
        return {"provider": self.name, "test_case": "provider_error"}

    def generate(self, prompt):
        raise RuntimeError("simulated provider outage")


class AgentEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.source_path = ROOT / "lean_project" / "Benchmarks" / "Evaluation18.lean"

    def test_success_is_saved_and_original_is_unchanged(self):
        original = self.source_path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            result = solve_problem(
                self.source_path,
                "Eval18.and_swap_eval",
                "A",
                MockProvider("```lean\nby\n  intro h\n  exact And.intro h.right h.left\n```"),
                1,
                LEAN_TIMEOUT,
                ROOT / "examples",
                base / "cache.sqlite3",
                base / "solutions",
                base / "runs.jsonl",
            )
            self.assertTrue(result["compile_ok"], result)
            self.assertEqual(original, self.source_path.read_text(encoding="utf-8"))
            saved = list((base / "solutions" / "A").glob("*.lean"))
            self.assertEqual(len(saved), 1)
            self.assertNotRegex(saved[0].read_text(encoding="utf-8"), r"\b(sorry|admit)\b")

    def test_bad_candidate_is_retried_and_failure_is_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            result = solve_problem(
                self.source_path,
                "Eval18.and_swap_eval",
                "B",
                MockProvider("by exact rfl"),
                2,
                LEAN_TIMEOUT,
                ROOT / "examples",
                base / "cache.sqlite3",
                base / "solutions",
                base / "runs.jsonl",
            )
            self.assertFalse(result["compile_ok"])
            self.assertTrue((base / "solutions" / "failures").exists())

    def test_second_identical_run_hits_persistent_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            provider = MockProvider("by\n  intro h\n  exact And.intro h.right h.left")
            kwargs = dict(
                source_path=self.source_path,
                theorem_name="Eval18.and_swap_eval",
                condition="A",
                provider=provider,
                max_rounds=1,
                timeout=LEAN_TIMEOUT,
                examples_dir=ROOT / "examples",
                cache_path=base / "cache.sqlite3",
                output_dir=base / "solutions",
                log_path=base / "runs.jsonl",
            )
            self.assertTrue(solve_problem(**kwargs)["compile_ok"])
            self.assertTrue(solve_problem(**kwargs)["compile_ok"])
            rows = [json.loads(line) for line in (base / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(rows[-1]["cache_hit"])

    def test_feedback_failure_then_success_is_logged(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            provider = SequenceProvider(["by exact rfl", "by\n  intro h\n  exact And.intro h.right h.left"])
            result = solve_problem(
                self.source_path,
                "Eval18.and_swap_eval",
                "B",
                provider,
                3,
                LEAN_TIMEOUT,
                ROOT / "examples",
                base / "cache.sqlite3",
                base / "solutions",
                base / "runs.jsonl",
            )
            self.assertTrue(result["compile_ok"], result)
            self.assertEqual(result["round"], 2)
            rows = [json.loads(line) for line in (base / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["diagnostic"]["category"], "ok")
            self.assertTrue(rows[1]["compile_ok"])

    def test_provider_error_is_traceable(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            result = solve_problem(
                self.source_path,
                "Eval18.and_swap_eval",
                "A",
                BrokenProvider(),
                1,
                LEAN_TIMEOUT,
                ROOT / "examples",
                base / "cache.sqlite3",
                base / "solutions",
                base / "runs.jsonl",
            )
            self.assertFalse(result["compile_ok"])
            self.assertEqual(result["diagnostic"]["category"], "provider_error")
            self.assertIn("simulated provider outage", result["provider_error"])

    def test_unique_sorry_placeholder_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source_path = base / "input.lean"
            source_path.write_text("import Std\nnamespace Demo\ntheorem target (p : Prop) : p → p := sorry\nend Demo\n", encoding="utf-8")
            result = solve_problem(
                source_path,
                "Demo.target",
                "A",
                MockProvider("by\n  intro hp\n  exact hp"),
                1,
                LEAN_TIMEOUT,
                ROOT / "examples",
                base / "cache.sqlite3",
                base / "solutions",
                base / "runs.jsonl",
            )
            self.assertTrue(result["compile_ok"], result)

    def test_external_file_uses_repository_toolchain(self):
        with tempfile.TemporaryDirectory() as temp:
            source_path = Path(temp) / "input.lean"
            source_path.write_text("import Std\nexample : True := by trivial\n", encoding="utf-8")
            with patch("compiler.shutil.which", return_value="elan"):
                command = lean_command(source_path)
            expected_toolchain = (ROOT / "lean-toolchain").read_text(encoding="utf-8").strip()
            self.assertEqual(command[:4], ["elan", "run", expected_toolchain, "lean"])


class CacheTest(unittest.TestCase):
    def test_persistent_exact_request_hit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "requests.sqlite3"
            with RequestCache(path) as cache:
                cache.put("same request", Generation("by rfl", {"total_tokens": 3}, "mock"))
            with RequestCache(path) as cache:
                found = cache.get("same request")
            self.assertIsNotNone(found)
            self.assertEqual(found.candidate, "by rfl")

    def test_condition_b_prompt_contains_feedback(self):
        source = ROOT.joinpath("lean_project", "Benchmarks", "Evaluation18.lean").read_text(encoding="utf-8")
        prompt = prompt_for(source, "Eval18.and_swap_eval", "B", {"feedback": "类别=type_mismatch"}, [])
        self.assertIn("type_mismatch", prompt)

    def test_condition_c_prompt_contains_retrieved_text(self):
        source = ROOT.joinpath("lean_project", "Benchmarks", "Evaluation18.lean").read_text(encoding="utf-8")
        prompt = prompt_for(source, "Eval18.and_swap_eval", "C", {"feedback": "x"}, [{"snippet": "example proof"}])
        self.assertIn("example proof", prompt)
