import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_research_run import canonical_nonproof, leakage_findings, proof_parts, review_success


class ResearchReviewTest(unittest.TestCase):
    def test_proof_parts_preserve_nonproof_source(self):
        source = "import Std\ntheorem t : True :=\n  -- PROOF_START\n  by trivial\n  -- PROOF_END\n"
        changed = source.replace("by trivial", "by\n    exact True.intro")
        before, proof, after = proof_parts(changed)
        self.assertEqual(before, proof_parts(source)[0])
        self.assertEqual(after, proof_parts(source)[2])
        self.assertEqual(proof.strip(), "by\n    exact True.intro")

    def test_nonproof_comparison_ignores_blank_lines_but_preserves_indentation(self):
        self.assertEqual(
            canonical_nonproof("import Std\n\ntheorem x : True :=\n"),
            canonical_nonproof("import Std\n\n\ntheorem x : True :=  \n"),
        )
        self.assertNotEqual(
            canonical_nonproof("  theorem x : True :=\n"),
            canonical_nonproof("theorem x : True :=\n"),
        )

    def test_leakage_finds_target_and_exact_candidate(self):
        problem = {"id": "target_case", "theorem": "N.target_case"}
        attempts = [{"retrieved_examples": [{"path": "target_case.lean", "snippet": "by trivial"}]}]
        self.assertEqual(len(leakage_findings(problem, attempts, "by trivial")), 2)

    def test_review_success_rejects_source_drift_and_forbidden_candidate(self):
        source = "import Std\ntheorem t : True :=\n  -- PROOF_START\n  by trivial\n  -- PROOF_END\n"
        solution = source.replace("import Std", "import Mathlib").replace("by trivial", "by sorry")
        attempts = [{"candidate": "by sorry", "compile_ok": True, "kernel_pass": True,
                     "diagnostic": {"warning_count": 0}, "retrieved_examples": []}]
        result = review_success(source, solution, {"compile_ok": True, "independent_compile_ok": True, "error": None},
                                attempts, {"id": "t", "theorem": "t"})
        self.assertTrue(any("源码发生漂移" in item for item in result["errors"]))
        self.assertTrue(any("不允许的构造" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
