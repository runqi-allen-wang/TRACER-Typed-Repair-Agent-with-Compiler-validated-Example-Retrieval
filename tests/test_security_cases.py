import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import solve_problem  # noqa: E402
from compiler import (  # noqa: E402
    CANDIDATE_POLICY,
    candidate_safety_violation,
    source_meta_execution_violation,
)
from provider import MockProvider  # noqa: E402


class SecurityTypeDTest(unittest.TestCase):
    def setUp(self):
        manifest_path = ROOT / "benchmarks" / "security" / "manifest.json"
        self.cases = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_type_d_manifest_is_well_formed(self):
        self.assertTrue(self.cases)
        self.assertEqual(len({case["id"] for case in self.cases}), len(self.cases))
        for case in self.cases:
            self.assertRegex(case["id"], r"^D\d{2}$")
            self.assertEqual(case["type"], "D")
            self.assertEqual(case["expected_category"], "unsafe_candidate")
            self.assertEqual(case["expected_policy"], "reject_before_compile")
            self.assertTrue((ROOT / case["file"]).is_file())

    def test_type_d_cases_are_rejected_before_lean_compilation(self):
        source_path = ROOT / "lean_project" / "Benchmarks" / "Evaluation18.lean"
        for case in self.cases:
            with self.subTest(case=case["id"]):
                candidate = (ROOT / case["file"]).read_text(encoding="utf-8")
                self.assertIsNotNone(candidate_safety_violation(candidate))
                self.assertTrue(source_meta_execution_violation(candidate))

                with tempfile.TemporaryDirectory() as temp, patch("agent.compile_candidate") as compile_mock:
                    base = Path(temp)
                    result = solve_problem(
                        source_path,
                        "Eval18.and_swap_eval",
                        "A",
                        MockProvider(candidate),
                        1,
                        20,
                        ROOT / "examples",
                        base / "cache.sqlite3",
                        base / "solutions",
                        base / "runs.jsonl",
                    )

                compile_mock.assert_not_called()
                self.assertFalse(result["compile_ok"])
                self.assertEqual(result["diagnostic"]["category"], case["expected_category"])
                self.assertIn("unsafe", result["diagnostic"]["summary"])
                self.assertEqual(result["candidate_policy"], CANDIDATE_POLICY)

    def test_type_d_rule_covers_declaration_modifiers(self):
        for source in (
            "private unsafe inductive Bad\n  | mk : (Bad → False) → Bad\n",
            "private /- split modifier -/ unsafe inductive Bad\n  | mk : (Bad → False) → Bad\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(source_meta_execution_violation(source))
                self.assertIsNotNone(candidate_safety_violation(source))
        self.assertFalse(
            source_meta_execution_violation(
                "/- documentation mentions\nunsafe inductive Bad\n-/\nexample : True := by trivial\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
