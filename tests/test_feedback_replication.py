import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from feedback_study import (  # noqa: E402
    REPLICATION_PROTOCOL_VERSION,
    apply_direct_model_config,
    validate_config,
    validate_replication_reference,
)
from audit_feedback_comparison import audit_comparison  # noqa: E402
from compare_feedback_models import (  # noqa: E402
    FORMAT,
    _write_report,
    compare_outcomes,
    compare_releases,
)
from research import load_benchmark  # noqa: E402


BASELINE = ROOT / "published" / "feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248"


class FeedbackReplicationTest(unittest.TestCase):
    def matching_config(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        return apply_direct_model_config(
            config,
            api_url="https://api.openai.com/v1/chat/completions",
            model="second-model-test",
            model_id="second_model",
            temperature=0,
            max_tokens=12000,
        )

    def test_reference_contract_accepts_matching_second_model_without_network(self):
        config = self.matching_config()
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        contract = validate_replication_reference(config, benchmark, BASELINE)
        self.assertEqual(contract["version"], REPLICATION_PROTOCOL_VERSION)
        self.assertEqual(contract["status"], "reference-validated")
        self.assertEqual(contract["reference_model"]["id"], "deepseek")
        self.assertEqual(contract["replication_model"]["id"], "second_model")
        self.assertNotIn("api_key_env", contract["replication_model"])

    def test_reference_contract_rejects_public_control_drift_and_same_model(self):
        benchmark = load_benchmark(ROOT / "benchmarks/repair24/manifest.json")
        drifted = self.matching_config()
        drifted["models"][0]["max_tokens"] = 8000
        with self.assertRaisesRegex(ValueError, "max_tokens"):
            validate_replication_reference(drifted, benchmark, BASELINE)

        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        same = apply_direct_model_config(
            config,
            api_url="https://api.deepseek.com/chat/completions",
            model="deepseek-v4-pro",
            model_id="deepseek_second",
            temperature=0,
            max_tokens=12000,
        )
        with self.assertRaisesRegex(ValueError, "相同端点和模型名称"):
            validate_replication_reference(same, benchmark, BASELINE)

    def test_model_id_is_validated(self):
        config = validate_config(ROOT / "experiments/feedback_study.example.json")
        with self.assertRaisesRegex(ValueError, "model-id"):
            apply_direct_model_config(
                config,
                api_url="https://example.test/v1/chat/completions",
                model="model",
                model_id="bad/model",
            )

    def test_outcome_comparison_aligns_all_216_tasks(self):
        baseline_trials = []
        replication_trials = []
        baseline_attempts = []
        replication_attempts = []
        for repeat in range(1, 4):
            for representation in ("raw", "normalized", "structured"):
                for index in range(24):
                    row = {
                        "repeat": repeat,
                        "representation": representation,
                        "problem_id": f"p{index:02d}",
                        "compile_ok": True,
                    }
                    baseline_trials.append(dict(row))
                    replication_trials.append(dict(row))
                    baseline_attempts.append(dict(row, round=1))
                    replication_attempts.append(dict(row, round=1))
        for row in replication_trials:
            if row["repeat"] == 1 and row["representation"] == "structured" and row["problem_id"] == "p00":
                row["compile_ok"] = False
        for row in replication_attempts:
            if row["repeat"] == 1 and row["representation"] == "structured" and row["problem_id"] == "p00":
                row["compile_ok"] = False

        by_representation, contrasts = compare_outcomes(
            baseline_trials, baseline_attempts, replication_trials, replication_attempts,
        )
        structured = next(row for row in by_representation if row["representation"] == "structured")
        self.assertEqual(structured["matched_tasks"], 72)
        self.assertEqual(structured["success_delta"], -1)
        self.assertEqual(structured["replication_only_success"], 0)
        self.assertEqual(structured["baseline_only_success"], 1)
        structured_raw = next(row for row in contrasts if row["comparison"] == "structured - raw")
        self.assertEqual(structured_raw["one_model_only_nonzero"], 1)
        self.assertEqual(structured_raw["opposite_direction"], 0)

    def test_cross_model_report_has_a_sanitized_auditable_inventory(self):
        row = {
            "matched_tasks": 72,
            "baseline_pass_at_1": 56,
            "replication_pass_at_1": 55,
            "pass_at_1_agreement_rate": 0.8,
            "baseline_pass_within_budget": 67,
            "replication_pass_within_budget": 66,
            "success_delta": -1,
            "final_outcome_agreement_rate": 0.9,
            "both_success": 64,
            "baseline_only_success": 3,
            "replication_only_success": 2,
            "both_failed": 3,
            "baseline_avg_rounds": 1.3,
            "replication_avg_rounds": 1.4,
        }
        report = {
            "format": FORMAT,
            "ok": True,
            "baseline": {
                "release": "feedback-study-baseline",
                "experiment_id": "baseline",
                "model": {"model": "model-a", "api_url": "https://a.example/v1"},
            },
            "replication": {
                "release": "feedback-study-replication",
                "experiment_id": "replication",
                "model": {"model": "model-b", "api_url": "https://b.example/v1"},
            },
            "matched_tasks": 216,
            "by_representation": [dict(row, representation=name) for name in ("raw", "normalized", "structured")],
            "contrast_direction_consistency": [
                {
                    "comparison": name,
                    "matched_problem_repeats": 72,
                    "baseline_mean_success_delta": 0,
                    "replication_mean_success_delta": 0,
                    "same_direction_rate": 1,
                    "both_zero": 72,
                    "concordant_nonzero": 0,
                    "opposite_direction": 0,
                    "one_model_only_nonzero": 0,
                }
                for name in ("normalized - raw", "structured - raw", "structured - normalized")
            ],
            "errors": [],
            "interpretation": "描述性配对，不声称显著性。",
        }
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "comparison"
            _write_report(out, report)
            audited = audit_comparison(out)
        self.assertTrue(audited["ok"], audited["errors"])
        self.assertEqual(audited["matched_tasks"], 216)

    def test_missing_protocol_is_reported_as_a_gate_error(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty"
            empty.mkdir()
            report = compare_releases(BASELINE, empty)
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_full_baseline_shape_can_be_paired_with_a_second_model_release(self):
        with tempfile.TemporaryDirectory() as directory:
            replication = Path(directory) / "second-release"
            (replication / "protocol").mkdir(parents=True)
            for name in ("benchmark.json", "trials.jsonl", "attempts.sanitized.jsonl"):
                shutil.copy2(BASELINE / name, replication / name)
            for name in ("feedback_study.protocol.json", "feedback.txt", "proof_contract.txt"):
                shutil.copy2(BASELINE / "protocol" / name, replication / "protocol" / name)

            plan = json.loads((BASELINE / "plan.sanitized.json").read_text(encoding="utf-8"))
            plan["experiment_id"] = "second-model-experiment"
            plan["config"]["models"][0].update({
                "id": "second_model",
                "api_url": "https://second.example/v1/chat/completions",
                "model": "second-model",
            })
            for task in plan["tasks"]:
                task["model_id"] = "second_model"
            plan["replication_contract"] = {
                "version": REPLICATION_PROTOCOL_VERSION,
                "status": "reference-validated",
                "reference_release": BASELINE.name,
                "reference_experiment_id": "feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248",
            }
            (replication / "plan.sanitized.json").write_text(
                json.dumps(plan, ensure_ascii=False), encoding="utf-8"
            )
            for name in ("trials.jsonl", "attempts.sanitized.jsonl"):
                path = replication / name
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                for row in rows:
                    row["model_id"] = "second_model"
                    row["experiment_id"] = "second-model-experiment"
                path.write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8",
                )

            report = compare_releases(BASELINE, replication, run_audit=False)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["matched_tasks"], 216)
        self.assertEqual(len(report["by_representation"]), 3)


if __name__ == "__main__":
    unittest.main()
