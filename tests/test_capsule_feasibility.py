import importlib.util
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_capsule_feasibility.py"
SPEC = importlib.util.spec_from_file_location("run_capsule_feasibility", SCRIPT)
feasibility = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(feasibility)


class CapsuleFeasibilityTest(unittest.TestCase):
    def test_core_matrix_has_twelve_one_line_mutations(self):
        cases = feasibility.engine.discover_cases(ROOT / "gallery_sources" / "core")
        self.assertEqual(len(cases), 12)
        self.assertEqual(Counter(case["taxonomy"] for case in cases), {
            "Name / import": 3,
            "Type / application": 3,
            "Elaboration / instance": 3,
            "Goal / scope": 3,
        })
        self.assertEqual(Counter(feasibility._context(case["case_id"]) for case in cases), {
            "standalone": 4,
            "same-file": 4,
            "project-local": 4,
        })
        for case in cases:
            directory = Path(case["_directory"])
            correct = (directory / case["correct_file"]).read_text(encoding="utf-8").splitlines()
            error = (directory / case["error_file"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(correct), len(error), case["case_id"])
            self.assertEqual(sum(left != right for left, right in zip(correct, error)), 1, case["case_id"])
            self.assertEqual(case["evaluation_set"], "core")
            self.assertTrue((directory / "README.md").is_file())

    def test_core_gate_requires_every_replay_property(self):
        passing = {
            "correct_template_compile_ok": True,
            "error_version_failed_as_expected": True,
            "setup_ok": True,
            "pack_ok": True,
            "official_compile_status_preserved": True,
            "official_error_category_preserved": True,
            "official_diagnostic_key_preserved": True,
            "replay_success": True,
            "strict_ordered_diagnostics_preserved": True,
        }
        self.assertTrue(feasibility.core_case_passed(passing))
        for field in tuple(passing):
            failed = dict(passing)
            failed[field] = False
            self.assertFalse(feasibility.core_case_passed(failed), field)


if __name__ == "__main__":
    unittest.main()
