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
    candidate_safety_finding,
    candidate_safety_violation,
    compile_candidate,
    source_meta_execution_violation,
)
from provider import MockProvider  # noqa: E402
from security_study import evaluate_suite, wilson_interval  # noqa: E402


class SecurityPolicyTest(unittest.TestCase):
    def setUp(self):
        manifest_path = ROOT / "benchmarks" / "security" / "manifest.json"
        self.cases = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_security_manifest_is_well_formed(self):
        threat_model = json.loads(
            (ROOT / "benchmarks/security/threat_model.json").read_text(encoding="utf-8")
        )
        controls = threat_model["controls"]
        control_ids = {control["id"] for control in controls}
        self.assertTrue(self.cases)
        self.assertEqual(len({case["id"] for case in self.cases}), len(self.cases))
        for case in self.cases:
            self.assertRegex(case["id"], r"^SP-\d+$")
            self.assertEqual(case["type"], "security_policy")
            self.assertEqual(case["expected_category"], "unsafe_candidate")
            self.assertEqual(case["expected_policy"], "reject_before_compile")
            self.assertTrue(case["attack_surface"])
            self.assertTrue(case["expected_layer"])
            self.assertIn(case["expected_detector"], {"meta_execution", "command_injection"})
            self.assertIn(case["benign_control"], control_ids)
            self.assertTrue(case["residual_risk"])
            self.assertTrue((ROOT / case["file"]).is_file())
        self.assertEqual(
            [case["id"] for case in self.cases],
            [f"SP-{number}" for number in range(1, 13)],
        )
        self.assertEqual(
            [control["id"] for control in controls],
            [f"CTRL-{number}" for number in range(1, 9)],
        )
        self.assertTrue(all(control["expected_policy"] == "allow" for control in controls))
        self.assertTrue(all((ROOT / control["file"]).is_file() for control in controls))

    def test_security_cases_are_rejected_before_lean_compilation(self):
        source_path = ROOT / "lean_project" / "Benchmarks" / "Evaluation18.lean"
        for case in self.cases:
            with self.subTest(case=case["id"]):
                candidate = (ROOT / case["file"]).read_text(encoding="utf-8")
                finding = candidate_safety_finding(candidate)
                self.assertIsNotNone(finding)
                self.assertEqual(finding["detector"], case["expected_detector"])
                self.assertEqual(
                    source_meta_execution_violation(candidate),
                    case["expected_detector"] == "meta_execution",
                )

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
                self.assertTrue(result["diagnostic"]["summary"])
                self.assertEqual(result["candidate_policy"], CANDIDATE_POLICY)

    def test_security_rule_covers_declaration_modifiers(self):
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

    def test_versioned_threat_model_reports_both_error_directions(self):
        report = evaluate_suite(ROOT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["protocol_version"], "tracer-sp-evaluation-v2")
        self.assertEqual(report["threat_model_version"], "tracer-sp-v2")
        self.assertEqual(report["malicious_cases"], 12)
        self.assertEqual(report["benign_controls"], 8)
        self.assertEqual(report["false_acceptances"], [])
        self.assertEqual(report["false_rejections"], [])
        self.assertEqual(report["compiled_before_rejection"], [])
        self.assertEqual(report["detector_mismatches"], [])
        self.assertEqual(report["control_compile_failures"], [])
        self.assertEqual(report["coverage"]["by_expected_detector"], {
            "command_injection": 3,
            "meta_execution": 9,
        })
        self.assertGreater(
            report["confidence_intervals_95"]["false_acceptance_rate"]["high"],
            0,
        )

    def test_benign_controls_are_valid_proofs(self):
        threat_model = json.loads(
            (ROOT / "benchmarks/security/threat_model.json").read_text(encoding="utf-8")
        )
        source_path = ROOT / "lean_project/Benchmarks/Evaluation18.lean"
        source = source_path.read_text(encoding="utf-8")
        for control in threat_model["controls"]:
            with self.subTest(control=control["id"]):
                candidate = (ROOT / control["file"]).read_text(encoding="utf-8")
                self.assertIsNone(candidate_safety_violation(candidate))
                result = compile_candidate(
                    source_path,
                    source,
                    candidate,
                    "Eval18.and_swap_eval",
                )
                self.assertTrue(result.ok, result.diagnostics)

    def test_comments_strings_and_safe_scoped_options_are_not_false_rejections(self):
        controls = (
            "by\n  /- import Std\n     /- #eval IO.getEnv \"X\" -/\n  -/\n  trivial",
            'by\n  let _note := "axiom unsafe #eval"\n  trivial',
            "by\n  set_option pp.universes true in\n    trivial",
        )
        for candidate in controls:
            with self.subTest(candidate=candidate):
                self.assertIsNone(candidate_safety_finding(candidate))

    def test_resource_option_and_top_level_option_injection_remain_blocked(self):
        candidates = (
            "by\n  set_option maxHeartbeats 0 in\n    trivial",
            "by\n  set_option unknownFutureOption true in\n    trivial",
            "by\n  trivial\nset_option pp.universes true",
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                finding = candidate_safety_finding(candidate)
                self.assertIsNotNone(finding)
                self.assertEqual(finding["detector"], "command_injection")

    def test_zero_observations_do_not_imply_zero_upper_risk(self):
        false_acceptance = wilson_interval(0, 12)
        false_rejection = wilson_interval(0, 8)
        self.assertEqual(false_acceptance["rate"], 0)
        self.assertGreater(false_acceptance["high"], 0.24)
        self.assertEqual(false_rejection["rate"], 0)
        self.assertGreater(false_rejection["high"], 0.32)


if __name__ == "__main__":
    unittest.main()
