import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.ax_integration import (  # noqa: E402
    AX_INTEGRATION_VERSION,
    RawFeedbackTracker,
    install_axproverbase_capsule_feedback,
)
from leancapsule.feedback import (  # noqa: E402
    AXPROVERBASE_COMMIT,
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
)
from leancapsule.part3 import build_summary, validate_part3_runs  # noqa: E402
from baseline.run_part2 import extract_record  # noqa: E402
from scripts.compare_part3 import _export_errors  # noqa: E402
from scripts.prepare_part2_first_round_cache import prepare_cache  # noqa: E402


class FakeBuildFailedFeedback:
    feedback_type = "build_failed"
    is_success = False

    def __init__(self, error_output: str):
        self.error_output = error_output


class FakeProposalMessage:
    type = "proposal"

    def __init__(self, *, reasoning, code, location, imports, opens):
        self.reasoning = reasoning
        self.code = code
        self.location = location
        self.imports = imports
        self.opens = opens


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        prover_llm=SimpleNamespace(
            model="old:model",
            provider_config={"base_url": "https://old.invalid"},
        ),
        memory_config=SimpleNamespace(class_name="OldMemory", init_args={"old": True}),
        summarize_output=SimpleNamespace(enabled=True, llm=None),
    )


def _state(theorem: str, feedback: object, iteration: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        item=SimpleNamespace(
            location=SimpleNamespace(path=Path("FATEM/1.lean"), name=theorem),
            original_source=f"theorem {theorem} : True := by trivial",
        ),
        iteration_count=iteration,
        fake_feedback=feedback,
    )


class Part3IntegrationTest(unittest.TestCase):
    def test_raw_preserves_ax_feedback_and_records_no_capsule_work(self):
        class RawAgent:
            def __init__(self, config, runtime):
                self.builder_calls = 0

            async def _builder_node(self, state):
                self.builder_calls += 1
                return {"messages": [state.fake_feedback], "sentinel": "kept"}

        with tempfile.TemporaryDirectory() as temp:
            metrics = Path(temp) / "raw.jsonl"
            install_axproverbase_capsule_feedback(
                agent_class=RawAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                feedback_mode="raw",
                telemetry_path=metrics,
            )
            agent = RawAgent(_config(), object())
            original = FakeBuildFailedFeedback("error: unknown identifier `x`")
            result = asyncio.run(agent._builder_node(_state("target", original)))

            self.assertIs(result["messages"][0], original)
            self.assertEqual(result["messages"][0].error_output, original.error_output)
            self.assertEqual(result["sentinel"], "kept")
            self.assertIsNone(agent._capsule_feedback_sessions)
            self.assertEqual(agent._capsule_node_counts["memory"], 0)
            self.assertEqual(agent._capsule_node_counts["builder"], 1)
            self.assertEqual(len(agent._feedback_events), 1)
            event = agent._feedback_events[0]
            self.assertEqual(event["feedback_mode"], "raw")
            self.assertFalse(event["builder_result_reused"])
            self.assertEqual(event["capsule_llm_calls"], 0)
            self.assertEqual(event["capsule_compiler_calls"], 0)
            self.assertEqual(event["memory_llm_calls"], 0)
            self.assertNotIn(original.error_output, metrics.read_text(encoding="utf-8"))

    def test_raw_tracker_counts_repeats_without_formatting_feedback(self):
        tracker = RawFeedbackTracker()
        first = tracker.observe(
            "FATEM/1.lean:target",
            FakeBuildFailedFeedback("FATEM/1.lean:2:4: error: unknown identifier `x`"),
            round_no=1,
        )
        second = tracker.observe(
            "FATEM/1.lean:target",
            FakeBuildFailedFeedback("FATEM/1.lean:20:4: error: unknown identifier `x`"),
            round_no=2,
        )
        self.assertEqual(first["repeat_count"], 1)
        self.assertEqual(second["repeat_count"], 2)
        self.assertEqual(second["consecutive_repeat_count"], 2)
        self.assertEqual(second["drift_kind"], "none")
        self.assertNotIn("prompt_feedback", first)

    def test_record_counts_repeated_events_once(self):
        state = SimpleNamespace(
            item=SimpleNamespace(
                location=SimpleNamespace(
                    path="FATEM/1.lean",
                    name="target",
                )
            ),
            approved=False,
            iteration_count=3,
            messages=[],
        )
        prover = SimpleNamespace(
            _capsule_node_counts={},
            _capsule_llm_calls={},
            _capsule_usage={},
            _capsule_tool_calls=0,
            _feedback_events=[
                {"repeat_count": 1},
                {"repeat_count": 2},
                {"repeat_count": 3},
            ],
        )
        contract = {
            "model": AXPROVER_YXAI_MODEL,
            "provider_config": _contract(),
            "budget": {
                "max_iterations": 4,
                "max_input_tokens": 65536,
                "max_tool_calling_iterations": 1,
            },
        }
        record = extract_record(
            "FATEM/1.lean:target",
            state,
            prover,
            contract,
            feedback_mode="raw",
            task_metadata={"id": "target", "module": "FATEM/1.lean", "theorem": "target"},
        )
        self.assertEqual(record["repeated_diagnostic_count"], 2)

    def test_raw_and_capsule_use_the_same_complete_cached_proposal(self):
        class RawAgent:
            def __init__(self, config, runtime):
                self.original_calls = 0

            async def _builder_node(self, state):
                return {"messages": []}

            async def _proposer_node(self, state, config=None):
                self.original_calls += 1
                return {"messages": []}

        class CapsuleAgent:
            def __init__(self, config, runtime):
                self.original_calls = 0

            async def _builder_node(self, state):
                return {"messages": []}

            async def _proposer_node(self, state, config=None):
                self.original_calls += 1
                return {"messages": []}

        candidate = {
            "code": "theorem target : True := by trivial",
            "reasoning": "",
            "imports": ["Mathlib"],
            "opens": ["Set"],
        }
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "cache.json"
            cache.write_text(json.dumps({"FATEM.1:target": candidate}), encoding="utf-8")
            install_axproverbase_capsule_feedback(
                agent_class=RawAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                feedback_mode="raw",
                first_round_cache_path=cache,
            )
            raw_agent = RawAgent(_config(), object())
            raw_proposal = asyncio.run(
                raw_agent._proposer_node(_state("target", FakeBuildFailedFeedback("x"), 0), {})
            )["messages"][0]

            install_axproverbase_capsule_feedback(
                agent_class=CapsuleAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                feedback_mode="capsule",
                first_round_cache_path=cache,
            )
            capsule_agent = CapsuleAgent(_config(), object())
            capsule_proposal = asyncio.run(
                capsule_agent._proposer_node(
                    _state("target", FakeBuildFailedFeedback("x"), 0), {}
                )
            )["messages"][0]

            for field in ("code", "reasoning", "imports", "opens"):
                self.assertEqual(getattr(raw_proposal, field), getattr(capsule_proposal, field))
            self.assertEqual(raw_agent.original_calls, 0)
            self.assertEqual(capsule_agent.original_calls, 0)


def _contract() -> dict:
    return {
        "base_url": YXAI_BASE_URL,
        "wire_api": YXAI_WIRE_API,
        "use_responses_api": True,
        "store": YXAI_STORE_RESPONSES,
        "reasoning": {"effort": YXAI_REASONING_EFFORT},
        "output_version": "responses/v1",
        "max_tokens": None,
        "profile": {"max_input_tokens": 65536},
    }


def _part3_record(
    mode: str,
    task_id: str,
    *,
    baseline_success: bool,
    success: bool,
    rounds: int,
) -> dict:
    module = "FATEM/1.lean"
    theorem = f"target_{task_id}"
    event = {
        "integration_schema_version": AXPROVERBASE_COMMIT,
        "feedback_mode": mode,
        "fingerprint": "a" * 16,
        "category": "type_mismatch",
        "repeat_count": 1,
        "round": 1,
        "builder_result_reused": mode == "capsule",
        "capsule_llm_calls": 0,
        "capsule_compiler_calls": 0,
    }
    return {
        "task_id": task_id,
        "target": f"{module}:{theorem}",
        "module": module,
        "theorem": theorem,
        "path": module,
        "condition": mode,
        "feedback_mode": mode,
        "memory_mode": "raw_feedback" if mode == "raw" else "capsule_feedback",
        "memory_processor": "MemorylessProcessor",
        "integration_schema_version": "ax-capsule-feedback.v0.2",
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": AXPROVER_YXAI_MODEL,
        "base_url": YXAI_BASE_URL,
        "wire_api": YXAI_WIRE_API,
        "use_responses_api": True,
        "store": False,
        "reasoning_effort": YXAI_REASONING_EFFORT,
        "provider_config": _contract(),
        "budget": {
            "max_iterations": 4,
            "max_input_tokens": 65536,
            "max_tool_calling_iterations": 1,
        },
        "candidate_policy": {
            "version": "tracer-candidate-v2",
            "meta_execution": "blocked",
            "unsafe_declarations": "blocked",
            "environment": "minimal",
        },
        "compile_ok": success,
        "rounds": rounds,
        "calls": {
            "proposer_calls": rounds,
            "reviewer_calls": rounds,
            "memory_calls": 0,
            "capsule_llm_calls": 0,
            "capsule_compiler_calls": 0,
        },
        "call_count": rounds * 2,
        "usage": {"total_tokens": rounds * 10},
        "first_round_candidate": "theorem target : True := by trivial",
        "first_round_reasoning": "",
        "first_round_imports": [],
        "first_round_opens": [],
        "feedback_events": [] if baseline_success else [event],
        "repeated_diagnostic_count": 0,
        "api_error_count": 0,
    }


class Part3PairingTest(unittest.TestCase):
    def test_pairing_gate_and_summary_cover_failure_subset(self):
        baseline = [
            {
                **_part3_record(
                    "baseline",
                    "one",
                    baseline_success=True,
                    success=True,
                    rounds=1,
                ),
                "memory_mode": "self_managed",
            },
            {
                **_part3_record(
                    "baseline",
                    "two",
                    baseline_success=False,
                    success=False,
                    rounds=1,
                ),
                "memory_mode": "self_managed",
            },
        ]
        raw = [
            _part3_record("raw", "one", baseline_success=True, success=True, rounds=1),
            _part3_record("raw", "two", baseline_success=False, success=True, rounds=2),
        ]
        capsule = [
            _part3_record(
                "capsule", "one", baseline_success=True, success=True, rounds=1
            ),
            _part3_record(
                "capsule", "two", baseline_success=False, success=True, rounds=3
            ),
        ]
        report = validate_part3_runs(raw, capsule, baseline_rows=baseline, expected_count=2)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["pair_count"], 2)
        summary = build_summary(report)
        self.assertEqual(summary["first_round_success_count"], 1)
        self.assertEqual(summary["first_round_failure_count"], 1)
        self.assertEqual(summary["conditions"]["raw"]["final_repairs_after_first_failure"], 1)
        self.assertEqual(
            summary["conditions"]["capsule"]["second_round_repairs_after_first_failure"],
            0,
        )
        self.assertEqual(summary["capsule_minus_raw"]["total_rounds"], 1)

    def test_pairing_gate_rejects_candidate_drift_and_infrastructure_errors(self):
        baseline = [
            {
                **_part3_record(
                    "baseline",
                    "one",
                    baseline_success=True,
                    success=True,
                    rounds=1,
                ),
                "memory_mode": "self_managed",
            }
        ]
        raw = [_part3_record("raw", "one", baseline_success=True, success=True, rounds=1)]
        capsule = [_part3_record("capsule", "one", baseline_success=True, success=True, rounds=1)]
        capsule[0]["first_round_candidate"] = "by trivial"
        report = validate_part3_runs(
            raw,
            capsule,
            baseline_rows=baseline,
            expected_count=1,
            error_rows=[{"task_id": "one", "condition": "raw"}],
        )
        self.assertFalse(report["ok"])
        joined = "\n".join(report["errors"])
        self.assertIn("first_round_candidate mismatch", joined)
        self.assertIn("unreported infrastructure error", joined)


class Part3CacheTest(unittest.TestCase):
    def test_cache_builder_preserves_empty_reasoning_and_list_fields(self):
        rows = [
            {
                "condition": "baseline",
                "module": "FATEM/1.lean",
                "theorem": "target",
                "target": "FATEM/1.lean:target",
                "first_round_candidate": "theorem target : True := by trivial",
                "first_round_reasoning": "",
                "first_round_imports": [],
                "first_round_opens": [],
            }
        ]
        cache = prepare_cache(rows)
        self.assertEqual(cache["FATEM.1:target"]["reasoning"], "")
        self.assertEqual(cache["FATEM.1:target"]["imports"], [])
        self.assertEqual(cache["FATEM.1:target"]["opens"], [])

    def test_handoff_scan_distinguishes_urls_from_windows_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            safe = Path(temp) / "safe.md"
            unsafe = Path(temp) / "unsafe.md"
            safe.write_text("endpoint: https://yxai.chat/v1\n", encoding="utf-8")
            unsafe.write_text("source: C:/Users/demo/FATEM/1.lean\n", encoding="utf-8")
            self.assertEqual(_export_errors([safe]), [])
            self.assertEqual(_export_errors([unsafe]), ["unsafe.md: sensitive-looking content found"])


if __name__ == "__main__":
    unittest.main()
