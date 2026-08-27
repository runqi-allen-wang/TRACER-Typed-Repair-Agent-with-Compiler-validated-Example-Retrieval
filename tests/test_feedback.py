import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.feedback import (  # noqa: E402
    AXPROVERBASE_COMMIT,
    AXPROVER_DEEPSEEK_FLASH_MODEL,
    CapsuleFeedback,
    DEEPSEEK_BASE_URL,
    stable_feedback_fingerprint,
)


class CapsuleFeedbackTest(unittest.TestCase):
    def test_fingerprint_ignores_path_location_and_metavariable_noise(self):
        left = "C:\\tmp\\tmp_Demo_ab12.lean:2:4: error: type mismatch for ?m.123"
        right = "/tmp/tmp_Demo_cd34.lean:20:8: error: type mismatch for ?m.987"
        self.assertEqual(
            stable_feedback_fingerprint("type_mismatch", left),
            stable_feedback_fingerprint("type_mismatch", right),
        )

    def test_repeats_and_drift_are_tracked(self):
        formatter = CapsuleFeedback(history_limit=3)
        first = formatter.observe_ax((False, "Demo.lean:2:4: error: type mismatch"), round_no=1)
        second = formatter.observe_ax((False, "Other.lean:9:8: error: type mismatch"), round_no=2)
        third = formatter.observe_ax((False, "Demo.lean:4:2: error: unknown identifier `x`"), round_no=3)

        self.assertEqual(first["drift_kind"], "initial")
        self.assertEqual(second["repeat_count"], 2)
        self.assertEqual(second["consecutive_repeat_count"], 2)
        self.assertEqual(second["drift_kind"], "none")
        self.assertTrue(third["diagnostic_drift"])
        self.assertEqual(third["drift_kind"], "category_changed")

    def test_ax_box_drawing_output_is_classified(self):
        formatter = CapsuleFeedback()
        result = formatter.observe_ax(
            (False, "╭─ Error at line 12:7\n│ bad code\n╰─ application type mismatch")
        )
        self.assertEqual(result["category"], "type_mismatch")

    def test_sorry_goal_feedback_uses_goal_context(self):
        formatter = CapsuleFeedback()
        result = formatter.observe_ax(
            {
                "feedback_type": "sorries_goal_state",
                "sorry_count": 1,
                "goal_state_at_sorries": "x : Nat\n⊢ x = x",
            }
        )
        self.assertEqual(result["category"], "unsolved_goals")
        self.assertIn("x : Nat", result["goal_state"])

    def test_formatter_never_spawns_a_compiler_or_model(self):
        formatter = CapsuleFeedback()
        with patch("subprocess.run") as run:
            formatter.observe_ax((False, "Demo.lean:1:1: error: unknown identifier `x`"))
        run.assert_not_called()

    def test_state_and_prompt_are_bounded(self):
        formatter = CapsuleFeedback(history_limit=2, max_feedback_chars=400, fingerprint_limit=8)
        for round_no in range(1, 101):
            formatter.observe_ax((False, f"Demo.lean:{round_no}:1: error: unknown identifier `x{round_no}`"))
        state = formatter.export_state()
        self.assertEqual(len(state["history"]), 2)
        self.assertLessEqual(len(state["fingerprint_counts"]), 8)
        self.assertLess(len(json.dumps(state)), 5000)
        restored = CapsuleFeedback.from_state(
            state, history_limit=2, max_feedback_chars=400, fingerprint_limit=8
        )
        result = restored.observe_ax((True, "Build successful"), round_no=101)
        self.assertLessEqual(len(result["prompt_feedback"]), 400)
        self.assertEqual(result["drift_kind"], "resolved")

    def test_unknown_state_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported CapsuleFeedback state schema"):
            CapsuleFeedback(state={"schema_version": "capsule-feedback.v999"})

    def test_string_false_is_not_treated_as_success(self):
        result = CapsuleFeedback().observe_ax(
            {"compile_ok": "false", "diagnostics": "error: unknown identifier `x`"}
        )
        self.assertFalse(result["compile_ok"])

    def test_sensitive_tokens_are_not_returned(self):
        formatter = CapsuleFeedback()
        result = formatter.observe_ax(
            (
                False,
                "error: Authorization: Bearer secret-token-123 and sk-abc123456789 "
                "api_key=opaque-secret-value",
            )
        )
        serialized = json.dumps(result)
        self.assertNotIn("secret-token-123", serialized)
        self.assertNotIn("sk-abc123456789", serialized)
        self.assertNotIn("opaque-secret-value", serialized)

    def test_ax_and_model_contract_is_frozen(self):
        self.assertEqual(AXPROVERBASE_COMMIT, "06dfadc9ab439755af5efcfe0add95bfef2733c7")
        self.assertEqual(AXPROVER_DEEPSEEK_FLASH_MODEL, "openai:deepseek-v4-flash")
        self.assertEqual(DEEPSEEK_BASE_URL, "https://api.deepseek.com")

    def test_cli_updates_state_without_lean(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            input_path = base / "compile.json"
            state_path = base / "state.json"
            input_path.write_text(
                json.dumps(
                    {
                        "compile_ok": False,
                        "returncode": 1,
                        "diagnostics": "Demo.lean:2:4: error: type mismatch",
                        "round": 1,
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "leancapsule",
                    "feedback",
                    "--input",
                    str(input_path),
                    "--state",
                    str(state_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(output["source"], "existing_axprover_compile_result")
            self.assertEqual(output["category"], "type_mismatch")
            self.assertEqual(state["attempt_count"], 1)


if __name__ == "__main__":
    unittest.main()
