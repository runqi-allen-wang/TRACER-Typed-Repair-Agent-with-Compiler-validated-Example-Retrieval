import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compiler_feedback import (  # noqa: E402
    FeedbackProtocolError,
    build_feedback_record,
    summarize_transitions,
    validate_feedback_record,
)
from scripts.verify_compiler_feedback_v1 import load_frozen_manifest  # noqa: E402


class CompilerFeedbackV1Test(unittest.TestCase):
    def test_frozen_manifest_has_exact_family_coverage_and_readable_snapshots(self):
        manifest, protocol = load_frozen_manifest()
        self.assertEqual(len(manifest["cases"]), 15)
        self.assertEqual(protocol["version"], "tracer-compiler-feedback-v1")
        self.assertEqual(
            {case["family"] for case in manifest["cases"]},
            {
                "unknown_identifier",
                "type_mismatch",
                "unsolved_goals",
                "syntax",
                "typeclass",
                "elaboration",
                "infrastructure",
            },
        )

    def test_unknown_identifier_keeps_three_layers_and_raw_evidence(self):
        raw = "C:/tmp/task.lean:3:12: error: unknown identifier 'misspelledName'"
        record = build_feedback_record(
            case_id="unit-unknown",
            diagnostic_text=raw,
            compile_ok=False,
            returncode=1,
            roots=(Path("C:/tmp"),),
        )
        self.assertEqual(record["structured"]["category"], "unknown_identifier")
        self.assertEqual(record["structured"]["category_source"], "diagnostic_text")
        self.assertIn("<path>:<loc>:", record["normalized"]["diagnostic_text"])
        for signal in record["structured"]["signals"]:
            self.assertIn(signal["evidence_excerpt"], record["raw"]["text"])

    def test_type_mismatch_extracts_actual_and_expected_types(self):
        raw = (
            "task.lean:4:2: error: application type mismatch\n"
            "  value\n"
            "has type\n"
            "  Nat\n"
            "but is expected to have type\n"
            "  Bool"
        )
        record = build_feedback_record(
            case_id="unit-type",
            diagnostic_text=raw,
            compile_ok=False,
            returncode=1,
        )
        signals = {item["kind"]: item["value"] for item in record["structured"]["signals"]}
        self.assertEqual(signals["actual_type"], "Nat")
        self.assertEqual(signals["expected_type"], "Bool")

    def test_raw_layer_redacts_credentials_and_local_paths(self):
        fake_secret = "sk-" + "example-not-a-real-secret-123456"
        raw = f"C:/Users/example/task.lean:1:1: provider API key={fake_secret}"
        record = build_feedback_record(
            case_id="unit-provider",
            diagnostic_text=raw,
            compile_ok=False,
            returncode=None,
            origin="provider",
            category_hint="provider_error",
        )
        self.assertNotIn(fake_secret, record["raw"]["text"])
        self.assertNotIn("C:/Users/example", record["raw"]["text"])
        self.assertIn("<local-path>", record["raw"]["text"])

    def test_raw_layer_preserves_outer_text_and_normalizes_only_line_endings(self):
        raw = "  error: unknown identifier 'x'\r\n\r\n"
        record = build_feedback_record(
            case_id="unit-raw-preservation",
            diagnostic_text=raw,
            compile_ok=False,
            returncode=1,
        )
        self.assertEqual(record["raw"]["text"], "  error: unknown identifier 'x'\n\n")

    def test_category_hint_is_limited_to_infrastructure_metadata(self):
        with self.assertRaisesRegex(FeedbackProtocolError, "不得用 category_hint"):
            build_feedback_record(
                case_id="unit-hint-lean",
                diagnostic_text="error: unknown identifier 'x'",
                compile_ok=False,
                returncode=1,
                origin="lean_compiler",
                category_hint="unknown_identifier",
            )
        with self.assertRaisesRegex(FeedbackProtocolError, "只允许标记基础设施错误"):
            build_feedback_record(
                case_id="unit-hint-provider",
                diagnostic_text="provider rejected request",
                compile_ok=False,
                returncode=None,
                origin="provider",
                category_hint="type_mismatch",
            )
        with self.assertRaisesRegex(FeedbackProtocolError, "来源与类别提示不一致"):
            build_feedback_record(
                case_id="unit-hint-origin",
                diagnostic_text="provider rejected request",
                compile_ok=False,
                returncode=None,
                origin="provider",
                category_hint="timeout",
            )
        with self.assertRaisesRegex(FeedbackProtocolError, "timed_out 只能"):
            build_feedback_record(
                case_id="unit-timeout-origin",
                diagnostic_text="Lean 编译超时（2s）",
                compile_ok=False,
                returncode=None,
                origin="compiler_process",
                category_hint="compiler_unavailable",
                timed_out=True,
            )

    def test_tampered_evidence_is_rejected(self):
        record = build_feedback_record(
            case_id="unit-evidence",
            diagnostic_text="task.lean:1:1: error: unknown identifier 'x'",
            compile_ok=False,
            returncode=1,
        )
        tampered = copy.deepcopy(record)
        tampered["structured"]["signals"][0]["evidence_excerpt"] = "不存在的片段"
        with self.assertRaisesRegex(FeedbackProtocolError, "缺少原始诊断片段"):
            validate_feedback_record(tampered)

    def test_transition_summary_separates_infrastructure_failures(self):
        first = build_feedback_record(
            case_id="unit-transition",
            diagnostic_text="error: unknown identifier 'x'",
            compile_ok=False,
            returncode=1,
            round_no=1,
        )
        second = build_feedback_record(
            case_id="unit-transition",
            diagnostic_text="error: unsolved goals\n⊢ True",
            compile_ok=False,
            returncode=1,
            round_no=2,
        )
        infrastructure = build_feedback_record(
            case_id="unit-infrastructure",
            diagnostic_text="Lean compiler unavailable: executable not found",
            compile_ok=False,
            returncode=None,
            origin="compiler_process",
            category_hint="compiler_unavailable",
        )
        summary = summarize_transitions([second, infrastructure, first])
        self.assertEqual(summary["proof_failure_records"], 2)
        self.assertEqual(summary["infrastructure_error_records"], 1)
        self.assertEqual(
            summary["adjacent_transitions"],
            {"unknown_identifier -> unsolved_goals": 1},
        )


if __name__ == "__main__":
    unittest.main()
