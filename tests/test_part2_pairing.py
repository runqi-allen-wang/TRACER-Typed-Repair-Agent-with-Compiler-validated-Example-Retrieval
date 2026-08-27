import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pairing import validate_paired_runs  # noqa: E402
from scripts.prepare_part2_first_round_cache import prepare_cache  # noqa: E402


def record(
    condition: str,
    task_id: str = "fate-001",
    candidate: str = "theorem target (h : True) : True := by exact h",
) -> dict:
    return {
        "condition": condition,
        "task_id": task_id,
        "first_round_candidate": candidate,
        "model": "openai:deepseek-v4-flash",
        "provider_config": {"base_url": "https://api.deepseek.com"},
        "budget": {"max_llm_calls": 50, "max_iterations": 50},
        "calls": {
            "memory_calls": 0 if condition == "capsule" else 1,
            "capsule_llm_calls": 0,
            "capsule_compiler_calls": 0,
        },
    }


class Part2PairingTest(unittest.TestCase):
    def test_part1_metrics_are_converted_to_exact_ax_target_cache(self):
        cache = prepare_cache(
            [
                {
                    **record("baseline"),
                    "module": "FATEM/Basic.lean",
                    "theorem": "target",
                    "first_round_reasoning": "cached",
                }
            ]
        )
        self.assertEqual(
            cache["FATEM.Basic:target"]["code"],
            "theorem target (h : True) : True := by exact h",
        )

    def test_strict_pairing_accepts_identical_first_candidate_and_contract(self):
        report = validate_paired_runs([record("baseline")], [record("capsule")])
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["pair_count"], 1)
        self.assertEqual(len(report["pairs"][0]["candidate_sha256"]), 64)

    def test_strict_pairing_rejects_candidate_model_budget_and_memory_drift(self):
        baseline = record("baseline")
        capsule = record("capsule", candidate="by trivial")
        capsule["model"] = "openai:other"
        capsule["budget"] = {"max_llm_calls": 51}
        capsule["calls"]["memory_calls"] = 1
        report = validate_paired_runs([baseline], [capsule])
        self.assertFalse(report["ok"])
        joined = "\n".join(report["errors"])
        self.assertIn("first_round_candidate mismatch", joined)
        self.assertIn("model mismatch", joined)
        self.assertIn("paired budgets do not match", joined)
        self.assertIn("memory_calls must be 0", joined)

    def test_pairing_cli_writes_a_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            baseline = base / "baseline.jsonl"
            capsule = base / "capsule.jsonl"
            report_path = base / "report.json"
            baseline.write_text(json.dumps(record("baseline")) + "\n", encoding="utf-8")
            capsule.write_text(json.dumps(record("capsule")) + "\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate_part2_pairing.py"),
                    "--baseline",
                    str(baseline),
                    "--capsule",
                    str(capsule),
                    "--out",
                    str(report_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(json.loads(report_path.read_text(encoding="utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
