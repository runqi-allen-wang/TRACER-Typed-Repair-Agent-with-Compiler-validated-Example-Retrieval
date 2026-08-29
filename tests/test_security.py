import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compiler import compile_candidate, declaration_scope, lean_subprocess_environment, validate_candidate_safety
from leancapsule.audit import audit_directory
from retriever import Example, retrieve


class SecurityBoundaryTest(unittest.TestCase):
    def test_explicit_metaprogramming_candidate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "禁止的本机执行构造"):
            validate_candidate_safety("by\n  run_tac Lean.Elab.Tactic.closeUsingOrAdmit")

    def test_compiler_environment_does_not_inherit_api_key(self):
        with patch.dict(os.environ, {"LEAN_PROOF_API_KEY": "secret-value", "UNRELATED_TOKEN": "hidden"}, clear=False):
            environment = lean_subprocess_environment(ROOT)
        self.assertNotIn("LEAN_PROOF_API_KEY", environment)
        self.assertNotIn("UNRELATED_TOKEN", environment)
        self.assertEqual(environment["TRACER_LEAN_CHILD"], "1")

    def test_sorry_axiom_is_not_a_success(self):
        source_path = ROOT / "lean_project" / "Benchmarks" / "Evaluation18.lean"
        source = source_path.read_text(encoding="utf-8")
        result = compile_candidate(source_path, source, "by exact sorryAx _ true", "Eval18.and_swap_eval")
        self.assertFalse(result.ok)
        self.assertIn("未完成证明", result.diagnostics)

    def test_fully_qualified_theorem_must_match_namespace(self):
        source = "namespace A\ntheorem target : True := by trivial\nend A\nnamespace B\ntheorem target : True := by trivial\nend B\n"
        with self.assertRaises(ValueError):
            declaration_scope(source, "target")
        with self.assertRaises(ValueError):
            declaration_scope(source, "C.target")

    def test_retrieval_excludes_exact_statement(self):
        example = Example("same.lean", ("logic",), "example (p q : Prop) : p ∧ q → q ∧ p := by exact sorry")
        result = retrieve("theorem target (p q : Prop) : p ∧ q → q ∧ p := sorry", [example], top_k=3)
        self.assertEqual(result, [])

    def test_audit_scans_orphan_auth_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "abcdefghijklmnop"}), encoding="utf-8")
            result = audit_directory(root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("敏感凭据" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
