import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pairing import validate_paired_runs  # noqa: E402
from baseline.run_part2 import (  # noqa: E402
    _contract_from_config,
    extract_record,
    main as run_part2_main,
    prepare_run_artifacts,
    validate_inputs,
)
from scripts.prepare_part2_first_round_cache import prepare_cache  # noqa: E402


def record(
    condition: str,
    task_id: str = "fate-001",
    candidate: str = "theorem target (h : True) : True := by exact h",
) -> dict:
    return {
        "condition": condition,
        "task_id": task_id,
        "target": "FATEM/1.lean:target",
        "module": "FATEM/1.lean",
        "theorem": "target",
        "path": str(Path("FATEM/1.lean")),
        "memory_mode": "capsule_feedback" if condition == "capsule" else "self_managed",
        "memory_processor": "MemorylessProcessor" if condition == "capsule" else None,
        "axproverbase_commit": "06dfadc9ab439755af5efcfe0add95bfef2733c7",
        "first_round_candidate": candidate,
        "first_round_reasoning": "paired",
        "first_round_imports": [],
        "first_round_opens": [],
        "model": "openai:gpt-5.6-sol",
        "provider_config": {
            "base_url": "https://yxai.chat/v1",
            "wire_api": "responses",
            "use_responses_api": True,
            "store": False,
            "reasoning": {"effort": "high"},
        },
        "budget": {"max_llm_calls": 50, "max_iterations": 50},
        "candidate_policy": {
            "version": "tracer-candidate-v2",
            "meta_execution": "blocked",
            "unsafe_declarations": "blocked",
            "environment": "minimal",
        },
        "calls": {
            "memory_calls": 0 if condition == "capsule" else 1,
            "capsule_llm_calls": 0,
            "capsule_compiler_calls": 0,
        },
    }


class Part2PairingTest(unittest.TestCase):
    def test_part2_rejects_inherited_provider_specific_keys(self):
        provider = {
            "base_url": "https://yxai.chat/v1",
            "use_responses_api": True,
            "store": False,
            "reasoning": {"effort": "high"},
            "output_version": "responses/v1",
            "max_tokens": None,
            "profile": {"max_input_tokens": 65536},
            "betas": ["claude-only"],
            "thinking": {"type": "enabled"},
        }
        config = SimpleNamespace(
            prover=SimpleNamespace(
                prover_llm=SimpleNamespace(
                    model="openai:gpt-5.6-sol", provider_config=provider
                ),
                memory_config=SimpleNamespace(class_name="MemorylessProcessor"),
                summarize_output=SimpleNamespace(enabled=False),
                max_iterations=4,
            ),
            runtime=SimpleNamespace(max_tool_calling_iterations=1),
        )
        with self.assertRaisesRegex(ValueError, "unsupported keys: betas, thinking"):
            _contract_from_config(config)

    def test_real_part2_record_is_pairing_ready(self):
        class Metrics:
            def model_dump(self):
                return {
                    "number_of_iterations": 2,
                    "compilation_error_count": 1,
                    "build_timeout_count": 0,
                    "reviewer_rejections": 0,
                    "max_iterations_reached": False,
                }

        candidate = "theorem target (h : True) : True := by exact h"
        proposal = SimpleNamespace(
            type="proposal",
            code=candidate,
            reasoning="paired",
            imports=[],
            opens=[],
        )
        state = SimpleNamespace(
            messages=[proposal],
            item=SimpleNamespace(
                location=SimpleNamespace(name="target", path=Path("FATEM/1.lean")),
                is_proven=True,
            ),
            metrics=Metrics(),
            iteration_count=1,
            approved=True,
        )
        prover = SimpleNamespace(
            _capsule_node_counts={"builder": 1, "shared_first_round": 1},
            _capsule_llm_calls={"proposer": 0, "reviewer": 1, "other": 0},
            _capsule_usage={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
            _capsule_tool_calls=0,
        )
        contract = {
            "model": "openai:gpt-5.6-sol",
            "provider_config": {
                "base_url": "https://yxai.chat/v1",
                "wire_api": "responses",
                "use_responses_api": True,
                "store": False,
                "reasoning": {"effort": "high"},
                "output_version": "responses/v1",
                "max_tokens": None,
                "profile": {"max_input_tokens": 65536},
            },
            "budget": {
                "max_iterations": 4,
                "max_input_tokens": 65536,
                "max_tool_calling_iterations": 1,
            },
        }
        capsule = extract_record(
            "FATEM/1.lean:target",
            state,
            prover,
            contract,
            task_metadata={"id": "fate-001", "module": "FATEM/1.lean", "theorem": "target"},
        )
        baseline = record("baseline", candidate=candidate)
        baseline["budget"] = dict(contract["budget"])
        self.assertTrue(validate_paired_runs([baseline], [capsule])["ok"])
        self.assertEqual(capsule["calls"]["compiler_calls"], 1)
        self.assertTrue(capsule["compile_ok"])
        self.assertEqual(capsule["calls"]["memory_calls"], 0)
        self.assertEqual(capsule["calls"]["capsule_llm_calls"], 0)

        state.approved = False
        failed = extract_record(
            "FATEM/1.lean:target",
            state,
            prover,
            contract,
            task_metadata={"id": "fate-001", "module": "FATEM/1.lean", "theorem": "target"},
        )
        self.assertFalse(failed["compile_ok"])
        self.assertIsNone(failed["success_node"])

    def test_part2_preflight_rejects_cache_drift_before_live_run(self):
        baseline = record("baseline")
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "cache.json"
            cache.write_text(
                json.dumps(
                    {
                        "FATEM/1.lean:target": {
                            "code": "theorem target : True := by trivial",
                            "reasoning": "different",
                            "imports": [],
                            "opens": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "cache mismatch"):
                validate_inputs([baseline], cache)

    def test_part2_preflight_rejects_full_proposal_context_drift(self):
        baseline = record("baseline")
        original = {
            "code": baseline["first_round_candidate"],
            "reasoning": baseline["first_round_reasoning"],
            "imports": baseline["first_round_imports"],
            "opens": baseline["first_round_opens"],
        }
        for field, changed in (
            ("reasoning", "different"),
            ("imports", ["Mathlib"]),
            ("opens", ["Classical"]),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                payload = dict(original)
                payload[field] = changed
                cache = Path(temp) / "cache.json"
                cache.write_text(
                    json.dumps({baseline["target"]: payload}), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, f"{field} cache mismatch"):
                    validate_inputs([baseline], cache)

    def test_part2_runner_refuses_nonempty_output_before_live_run(self):
        baseline = record("baseline")
        baseline.update(
            {
                "target": "FATEM/1.lean:target",
                "module": "FATEM/1.lean",
                "theorem": "target",
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            baseline_path = base / "baseline.jsonl"
            cache_path = base / "cache.json"
            output_path = base / "capsule.jsonl"
            baseline_path.write_text(json.dumps(baseline) + "\n", encoding="utf-8")
            cache_path.write_text(
                json.dumps(
                    {
                        baseline["target"]: {
                            "code": baseline["first_round_candidate"],
                            "reasoning": "paired",
                            "imports": [],
                            "opens": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            output_path.write_text("existing\n", encoding="utf-8")
            with patch.dict(
                "os.environ", {"CAPSULE_FIRST_ROUND_CACHE": str(cache_path)}, clear=False
            ):
                code = run_part2_main(
                    [
                        "--baseline",
                        str(baseline_path),
                        "--folder",
                        str(base),
                        "--config",
                        "unused.yaml",
                        "--out",
                        str(output_path),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing\n")

    def test_part1_metrics_are_converted_to_exact_ax_target_cache(self):
        cache = prepare_cache(
            [
                {
                    **record("baseline"),
                    "target": "FATEM/Basic.lean:target",
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

    def test_empty_first_round_reasoning_is_preserved_exactly(self):
        baseline = record("baseline")
        baseline["first_round_reasoning"] = ""
        cache = prepare_cache([baseline])
        self.assertEqual(cache["FATEM.1:target"]["reasoning"], "")

    def test_strict_pairing_accepts_identical_first_candidate_and_contract(self):
        report = validate_paired_runs([record("baseline")], [record("capsule")])
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["pair_count"], 1)
        self.assertEqual(len(report["pairs"][0]["candidate_sha256"]), 64)

    def test_strict_pairing_rejects_candidate_model_budget_and_memory_drift(self):
        baseline = record("baseline")
        capsule = record("capsule", candidate="by trivial")
        capsule["target"] = "FATEM/2.lean:other"
        capsule["module"] = "FATEM/2.lean"
        capsule["theorem"] = "other"
        capsule["path"] = str(Path("FATEM/2.lean"))
        capsule["axproverbase_commit"] = "wrong"
        capsule["first_round_reasoning"] = "different"
        capsule["first_round_imports"] = ["Mathlib"]
        capsule["model"] = "openai:other"
        capsule["budget"] = {"max_llm_calls": 51}
        capsule["candidate_policy"] = {"version": "tracer-candidate-v1"}
        capsule["provider_config"]["wire_api"] = "chat_completions"
        capsule["provider_config"]["store"] = True
        capsule["provider_config"]["reasoning"] = {"effort": "low"}
        capsule["calls"]["memory_calls"] = 1
        report = validate_paired_runs([baseline], [capsule])
        self.assertFalse(report["ok"])
        joined = "\n".join(report["errors"])
        self.assertIn("first_round_candidate mismatch", joined)
        self.assertIn("paired target mismatch", joined)
        self.assertIn("paired module mismatch", joined)
        self.assertIn("paired theorem mismatch", joined)
        self.assertIn("first_round_reasoning mismatch", joined)
        self.assertIn("first_round_imports mismatch", joined)
        self.assertIn("both conditions must use AxProverBase", joined)
        self.assertIn("model mismatch", joined)
        self.assertIn("paired budgets do not match", joined)
        self.assertIn("candidate security policies do not match", joined)
        self.assertIn("must use the Responses API", joined)
        self.assertIn("disable response storage", joined)
        self.assertIn("reasoning effort high", joined)
        self.assertIn("memory_calls must be 0", joined)

    def test_formal_runner_requires_fresh_auxiliary_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            output = base / "capsule.jsonl"
            metrics = base / "metrics.jsonl"
            state = base / "state"
            state.mkdir()
            state_file = state / ("a" * 24 + ".json")
            output.write_text("old output\n", encoding="utf-8")
            metrics.write_text("old metrics\n", encoding="utf-8")
            state_file.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contaminate a fresh run"):
                prepare_run_artifacts(
                    output,
                    state_dir=state,
                    metrics_path=metrics,
                    overwrite=False,
                )

            prepare_run_artifacts(
                output,
                state_dir=state,
                metrics_path=metrics,
                overwrite=True,
            )
            self.assertEqual(output.read_text(encoding="utf-8"), "")
            self.assertEqual(metrics.read_text(encoding="utf-8"), "")
            self.assertFalse(state_file.exists())

    def test_formal_runner_never_removes_unknown_state_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            state = base / "state"
            state.mkdir()
            unknown = state / "notes.txt"
            unknown.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dedicated state directory"):
                prepare_run_artifacts(
                    base / "capsule.jsonl",
                    state_dir=state,
                    metrics_path=base / "metrics.jsonl",
                    overwrite=True,
                )
            self.assertEqual(unknown.read_text(encoding="utf-8"), "keep")

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
