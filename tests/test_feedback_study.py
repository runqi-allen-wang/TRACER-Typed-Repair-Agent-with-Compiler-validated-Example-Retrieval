import json
import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import feedback_payload  # noqa: E402
from feedback_study import (  # noqa: E402
    REPRESENTATIONS, apply_direct_model_config, build_plan, is_retryable_transport_error,
    latest_infrastructure_error, run_matrix, summarize, validate_config,
)
from provider import Generation  # noqa: E402
from research import CallBudget, load_benchmark  # noqa: E402


class FeedbackStudyTest(unittest.TestCase):
    def test_example_plan_is_complete_and_offline(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        plan = build_plan(config, benchmark)
        self.assertEqual(len(plan), 216)
        self.assertEqual({task["representation"] for task in plan}, set(REPRESENTATIONS))

    def test_config_rejects_missing_representation(self):
        source = json.loads((ROOT / "experiments/feedback_study.example.json").read_text(encoding="utf-8"))
        source["representations"] = ["raw", "structured"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "冻结顺序"):
                validate_config(path)

    def test_feedback_representations_are_observably_distinct(self):
        diagnostic = {"category": "unknown_identifier", "summary": "unknown", "feedback": "legacy"}
        raw = "task.lean:1:1: error: unknown identifier 'misspelledName'"
        payloads = {
            name: feedback_payload(name, diagnostic, raw, case_id="case", round_no=2)
            for name in REPRESENTATIONS
        }
        self.assertEqual(len(set(payloads.values())), 3)
        self.assertIn("misspelledName", payloads["raw"])
        structured = json.loads(payloads["structured"])
        self.assertEqual(structured["category"], "unknown_identifier")
        self.assertEqual(structured["signals"][0]["kind"], "unknown_identifier")

    def test_direct_deepseek_cli_override_is_valid_and_does_not_contain_a_key(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        overridden = apply_direct_model_config(
            config,
            "https://api.deepseek.com/chat/completions",
            "deepseek-v4-pro",
            temperature=0,
            max_tokens=12000,
            thinking="enabled",
            reasoning_effort="high",
        )
        self.assertEqual(len(overridden["models"]), 1)
        self.assertEqual(overridden["models"][0]["id"], "deepseek")
        self.assertEqual(overridden["models"][0]["model"], "deepseek-v4-pro")
        self.assertEqual(overridden["models"][0]["thinking"], "enabled")
        self.assertEqual(overridden["models"][0]["reasoning_effort"], "high")
        self.assertEqual(overridden["models"][0]["api_key_env"], "TRACER_FEEDBACK_MODEL_KEY")
        self.assertFalse(any(name in overridden["models"][0] for name in ("api_key", "authorization", "secret")))

    def test_direct_cli_rejects_partial_or_unsafe_endpoint(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        with self.assertRaisesRegex(ValueError, "必须同时"):
            apply_direct_model_config(config, api_url="https://api.deepseek.com/chat/completions")
        with self.assertRaisesRegex(ValueError, "HTTPS URL"):
            apply_direct_model_config(config, "http://example.invalid/chat", "model")

    def test_three_representation_runner_works_without_network_under_mock(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        config.update(models=config["models"][:1], repeats=1)
        config["models"][0]["model"] = "offline-test-only"
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        benchmark["problems"] = [problem for problem in benchmark["problems"] if problem["id"] == "forall_and"]
        initial = [{
            "problem_id": "forall_and",
            "diagnostic": {"category": "unknown_identifier", "feedback": "unknown"},
            "raw_diagnostics": "error: unknown identifier 'offlineMissing'",
        }]

        class OfflineProvider:
            name = "openai_compatible"

            def __init__(self):
                self.fail_once = True

            def metadata(self):
                model = config["models"][0]
                return {"provider": self.name, "url": model["api_url"], **{
                    key: model.get(key) for key in (
                        "model", "temperature", "max_tokens", "thinking", "reasoning_effort",
                        "input_price_per_1k", "output_price_per_1k",
                    )
                }}

            def generate(self, prompt):
                if self.fail_once:
                    self.fail_once = False
                    raise http.client.IncompleteRead(b"", 1)
                return Generation(
                    "by\n  constructor\n  · intro h; exact ⟨fun x => (h x).1, fun x => (h x).2⟩\n  · intro h x; exact ⟨h.1 x, h.2 x⟩",
                    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    self.name,
                    {"finish_reason": "stop"},
                )

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "study"
            budget = CallBudget(9, None)
            provider = OfflineProvider()
            with patch.dict("os.environ", {config["models"][0]["api_key_env"]: "offline-test-only"}), \
                 patch("feedback_study.OpenAICompatibleProvider", return_value=provider), \
                 patch("feedback_study.load_benchmark", return_value=benchmark), \
                 patch("feedback_study.check_benchmark", return_value=initial):
                self.assertFalse(run_matrix(config, ROOT / "benchmarks/repair24/manifest.json", out, budget=budget))
                self.assertTrue(is_retryable_transport_error(latest_infrastructure_error(out)))
                self.assertTrue(is_retryable_transport_error("[WinError 10054] 远程主机强迫关闭了连接"))
                self.assertFalse(is_retryable_transport_error("HTTP 401: invalid API key"))
                self.assertFalse(is_retryable_transport_error("编译超时或工具链/补丁错误"))
                self.assertTrue(run_matrix(
                    config, ROOT / "benchmarks/repair24/manifest.json", out, budget=budget, resume=True,
                ))
            self.assertEqual(budget.calls, 4)
            self.assertIsNone(json.loads((out / "budget.json").read_text(encoding="utf-8"))["max_reserved_usd"])
            self.assertEqual(len(list((out / "retry_history").rglob("trial.json"))), 1)
            report = summarize(out)
            self.assertTrue(report["trajectory_valid"])
            self.assertFalse(report["release_ready"])
            self.assertEqual(report["review_mode"], "ai_assisted")
            self.assertFalse(report["review_complete"])
            self.assertFalse(report["ai_assisted_review_complete"])
            self.assertTrue((out / "ai_assisted_review.csv").is_file())
            self.assertFalse((out / "manual_review.csv").exists())
            self.assertEqual({item["representation"] for item in report["summary"]}, set(REPRESENTATIONS))
            self.assertEqual(len(list(out.glob("trials/**/solutions/B/*.lean"))), 3)


if __name__ == "__main__":
    unittest.main()
