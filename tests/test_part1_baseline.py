import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from baseline.run_baseline import _parse_axp_output, _write_axp_config, load_config
from baseline.run_batch import completed_task_ids
from baseline.run_api import (
    _contract_from_config,
    _install_safety_gate,
    extract_record,
)
from scripts.prepare_part2_first_round_cache import prepare_cache


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline"


class Part1BaselineIntegrationTest(unittest.TestCase):
    def test_part1_uses_the_same_yxai_responses_contract_as_part2(self):
        config = load_config(BASELINE / "config.yaml")
        llm = config["prover"]["prover_llm"]
        provider = llm["provider_config"]
        self.assertEqual(llm["model"], "openai:gpt-5.6-sol")
        self.assertEqual(provider["base_url"], "https://yxai.chat/v1")
        self.assertIs(provider["use_responses_api"], True)
        self.assertIs(provider["store"], False)
        self.assertEqual(provider["reasoning"]["effort"], "high")
        self.assertEqual(provider["output_version"], "responses/v1")
        self.assertEqual(provider["profile"]["max_input_tokens"], 65536)
        self.assertIsNone(config["run"]["price"]["input_usd_per_1k"])
        self.assertIsNone(config["run"]["price"]["output_usd_per_1k"])
        self.assertEqual(config["environment"]["benchmark_ref"], "v4.28.0")
        self.assertEqual(config["environment"]["lean_toolchain"], "leanprover/lean4:v4.28.0")

        shared = load_config(ROOT / "configs" / "axprover_yxai_gpt56_sol.yaml")
        self.assertEqual(shared["prover"]["max_iterations"], 4)
        self.assertEqual(
            shared["prover"]["prover_llm"]["retry_config"]["stop_after_attempt"],
            3,
        )
        self.assertEqual(
            shared["prover"]["proposer_tools"],
            {"search_lean": None, "search_web": None},
        )
        self.assertEqual(shared["runtime"]["max_tool_calling_iterations"], 1)

    def test_part1_rejects_inherited_provider_specific_keys(self):
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
                memory_config=SimpleNamespace(class_name="ExperienceProcessor"),
                summarize_output=SimpleNamespace(enabled=False),
                max_iterations=4,
            ),
            runtime=SimpleNamespace(max_tool_calling_iterations=1),
        )
        with self.assertRaisesRegex(ValueError, "unsupported keys: betas, thinking"):
            _contract_from_config(config)

    def test_generated_ax_configs_freeze_memory_and_summary_modes(self):
        config = load_config(BASELINE / "config.yaml")
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            experience = yaml.safe_load(
                _write_axp_config(config, workdir, "self_managed").read_text(encoding="utf-8")
            )["prover"]
            self.assertEqual(experience["memory_config"]["class_name"], "ExperienceProcessor")
            self.assertEqual(
                experience["memory_config"]["init_args"]["llm_config"],
                "${prover.prover_llm}",
            )
            self.assertIs(experience["summarize_output"]["enabled"], False)

            memoryless = yaml.safe_load(
                _write_axp_config(config, workdir, "none").read_text(encoding="utf-8")
            )["prover"]
            self.assertEqual(memoryless["memory_config"]["class_name"], "MemorylessProcessor")
            self.assertEqual(memoryless["memory_config"]["init_args"], {})
            self.assertEqual(
                memoryless["prover_llm"]["provider_config"],
                experience["prover_llm"]["provider_config"],
            )

    def test_manifest_targets_the_pinned_fate_layout(self):
        manifest = json.loads((BASELINE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 25)
        for index, item in enumerate(manifest, start=1):
            expected = f"FATEM/{index}.lean"
            self.assertEqual(item["module"], expected)
            self.assertEqual(item["file"], expected)

    def test_part1_workflows_are_ubuntu_only_pinned_and_do_not_override_the_model(self):
        validation = (ROOT / ".github" / "workflows" / "part1.yml").read_text(encoding="utf-8")
        real_run = (ROOT / ".github" / "workflows" / "part1_run.yml").read_text(encoding="utf-8")
        for workflow in (validation, real_run):
            self.assertIn("ubuntu-latest", workflow)
            self.assertNotIn("windows-latest", workflow)
            self.assertNotIn("deepseek", workflow.lower())
            self.assertNotIn("spacetime", workflow.lower())
        self.assertIn("requirements-axprover-part2.txt", validation)
        self.assertIn("requirements-axprover-part2.txt", real_run)
        self.assertNotIn("llm['model']", real_run)
        self.assertNotIn("base_url']", real_run)
        self.assertIn("4eb33c8ccd0ff058b461cd763cc406509129743f", real_run)
        self.assertIn("baseline/run_batch.py", real_run)
        self.assertNotIn("baseline/run_baseline.py --limit", real_run)

    def test_ax_output_parser_accepts_boolean_status_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp) / "result.json"
            result.write_text(json.dumps({"ok": True, "usage": {}}), encoding="utf-8")
            self.assertIs(_parse_axp_output(result)["ok"], True)

    def test_python_api_record_is_pairing_ready(self):
        class Metrics:
            def model_dump(self):
                return {
                    "number_of_iterations": 1,
                    "compilation_error_count": 0,
                    "build_timeout_count": 0,
                    "reviewer_rejections": 0,
                    "max_iterations_reached": False,
                }

        proposal = SimpleNamespace(
            type="proposal",
            code="theorem target (h : True) : True := by exact h",
            reasoning="Use the hypothesis.",
            imports=["Mathlib"],
            opens=[],
        )
        approved = SimpleNamespace(type="feedback", feedback_type="review_approved")
        location = SimpleNamespace(name="target", path=Path("FATEM/1.lean"))
        state = SimpleNamespace(
            messages=[proposal, approved],
            item=SimpleNamespace(location=location, is_proven=True),
            metrics=Metrics(),
            iteration_count=1,
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
        record = extract_record(
            "FATEM/1.lean:target",
            state,
            {"prompt": 100, "completion": 20, "calls": 3},
            {"input_usd_per_1k": None, "output_usd_per_1k": None},
            contract,
            task_metadata={"id": "fate01", "module": "FATEM/1.lean", "theorem": "target"},
            run_elapsed_ms=1200,
            builder_elapsed_ms=400,
            builder_calls=1,
        )
        self.assertEqual(record["task_id"], "fate01")
        self.assertEqual(record["first_round_candidate"], proposal.code)
        self.assertEqual(record["first_round_imports"], ["Mathlib"])
        self.assertEqual(record["calls"]["proposer_calls"], 1)
        self.assertEqual(record["calls"]["reviewer_calls"], 1)
        self.assertEqual(record["calls"]["memory_calls"], 1)
        self.assertEqual(record["calls"]["compiler_calls"], 1)
        self.assertEqual(record["candidate_policy"]["version"], "tracer-candidate-v2")
        self.assertIsNone(record["estimated_cost_usd"])
        cache = prepare_cache([record])
        self.assertEqual(cache["FATEM.1:target"]["code"], proposal.code)

    def test_part1_safety_gate_rejects_d01_before_builder(self):
        class FakeBuildFailedFeedback:
            feedback_type = "build_failed"

            def __init__(self, error_output):
                self.error_output = error_output

        class FakeAgent:
            builder_calls = 0

            async def _builder_node(self, state):
                self.builder_calls += 1
                return {"messages": []}

        _install_safety_gate(FakeAgent, FakeBuildFailedFeedback)
        proposal = SimpleNamespace(
            code=(
                "unsafe inductive Bad\n"
                "  | mk : (Bad → False) → Bad\n\n"
                "theorem target : True := by trivial"
            ),
            imports=[],
            opens=[],
        )
        state = SimpleNamespace(
            item=SimpleNamespace(
                location=SimpleNamespace(name="target"),
                original_source="theorem target : True := by sorry",
            ),
            last_proposal=proposal,
        )
        agent = FakeAgent()
        result = asyncio.run(agent._builder_node(state))
        self.assertEqual(agent.builder_calls, 0)
        self.assertEqual(result["messages"][0].feedback_type, "build_failed")
        self.assertIn("rejected before Lean build", result["messages"][0].error_output)

    def test_batch_resume_validates_and_skips_completed_task_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "part1.jsonl"
            output.write_text(
                json.dumps({"task_id": "fate01"})
                + "\n"
                + json.dumps({"task_id": "fate02"})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(completed_task_ids(output), {"fate01", "fate02"})

            output.write_text(
                json.dumps({"task_id": "fate01"})
                + "\n"
                + json.dumps({"task_id": "fate01"})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate task_id"):
                completed_task_ids(output)


if __name__ == "__main__":
    unittest.main()
