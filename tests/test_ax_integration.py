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
    CapsuleFeedbackSessions,
    FirstRoundCandidateCache,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
    validate_ax_proposal_safety,
)


class FakeBuildFailedFeedback:
    feedback_type = "build_failed"
    is_success = False

    def __init__(self, error_output: str):
        self.error_output = error_output
        self.content = f"BUILD FAILED:\n\n{error_output}"


class FakeSorriesFeedback:
    feedback_type = "sorries_goal_state"
    is_success = False

    def __init__(self, goal_state: str):
        self.sorry_count = 1
        self.goal_state_at_sorries = goal_state


class FakeBuildSuccessFeedback:
    feedback_type = "build_success"
    is_success = True


class FakeProposalMessage:
    type = "proposal"

    def __init__(self, *, reasoning, code, location, imports, opens):
        self.reasoning = reasoning
        self.code = code
        self.location = location
        self.imports = imports
        self.opens = opens


class FakeLLMResponse:
    usage_metadata = {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    tool_calls = [{"name": "search_lean"}]


class FakeLLMClient:
    async def ainvoke(self, *args, **kwargs):
        return FakeLLMResponse()


def make_config() -> SimpleNamespace:
    return SimpleNamespace(
        prover_llm=SimpleNamespace(
            model="anthropic:old-model",
            provider_config={"base_url": "https://old.invalid"},
        ),
        memory_config=SimpleNamespace(
            class_name="ExperienceProcessor", init_args={"llm_config": "old"}
        ),
        summarize_output=SimpleNamespace(enabled=True, llm=None),
    )


def make_state(
    theorem: str,
    feedback: object,
    iteration: int = 1,
    *,
    original_source: str | None = None,
    last_proposal: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        item=SimpleNamespace(
            location=SimpleNamespace(path=Path("Demo.lean"), name=theorem),
            original_source=original_source or f"theorem {theorem} : True := by trivial",
        ),
        iteration_count=iteration,
        fake_feedback=feedback,
        last_proposal=last_proposal,
    )


class AxIntegrationTest(unittest.TestCase):
    def test_first_round_cache_matches_path_and_module_target_spellings(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "first-round.json"
            cache.write_text(
                json.dumps(
                    {
                        "FATEM/1.lean:target": {
                            "code": "theorem target : True := by trivial",
                            "imports": [],
                            "opens": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            loaded = FirstRoundCandidateCache(cache)
            self.assertEqual(
                loaded.get("FATEM.1:target")["code"],
                "theorem target : True := by trivial",
            )

    def test_full_theorem_safety_gate_rejects_unsafe_and_statement_changes(self):
        state = make_state("A", FakeBuildSuccessFeedback())
        self.assertIsNone(
            validate_ax_proposal_safety(state, "theorem A : True := by trivial")
        )
        unsafe_source = (
            ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean"
        ).read_text(encoding="utf-8")
        self.assertIn("unsafe", validate_ax_proposal_safety(state, unsafe_source) or "")
        self.assertIn(
            "修改了目标定理陈述",
            validate_ax_proposal_safety(state, "theorem A : False := by trivial") or "",
        )
        self.assertIn(
            "只能包含一个顶层声明",
            validate_ax_proposal_safety(
                state,
                "theorem A : True := by trivial\naxiom injected : False",
            )
            or "",
        )
        self.assertIn(
            "非法 import",
            validate_ax_proposal_safety(
                state,
                "theorem A : True := by trivial",
                imports=["Std\nunsafe inductive Bad"],
            )
            or "",
        )

    def test_full_theorem_safety_gate_accepts_qualified_declaration_name(self):
        theorem = "MonoidHom.eq_id_of_card_gcd_eq_one"
        source = f"theorem {theorem} : True := by trivial"
        state = make_state(
            theorem,
            FakeBuildSuccessFeedback(),
            original_source=source,
        )
        self.assertIsNone(validate_ax_proposal_safety(state, source))

    def test_ax_wrapper_rejects_cached_generated_and_builder_unsafe_proposals(self):
        unsafe_source = (
            ROOT / "benchmarks" / "security" / "unsafe_inductive_false.lean"
        ).read_text(encoding="utf-8")

        class CachedAgent:
            def __init__(self, config, runtime):
                self.llm_client = None
                self.original_proposer_calls = 0

            async def _builder_node(self, state):
                raise AssertionError("unsafe cached proposal reached the builder")

            async def _proposer_node(self, state, config=None):
                self.original_proposer_calls += 1
                return {}

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cache = base / "first-round.json"
            metrics = base / "metrics.jsonl"
            cache.write_text(json.dumps({"Demo.lean:A": unsafe_source}), encoding="utf-8")
            install_axproverbase_capsule_feedback(
                agent_class=CachedAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                telemetry_path=metrics,
                first_round_cache_path=cache,
            )
            cached_agent = CachedAgent(make_config(), object())
            cached_state = make_state("A", FakeBuildSuccessFeedback(), 0)
            proposal_result = asyncio.run(
                cached_agent._proposer_node(cached_state, {})
            )
            cached_state.last_proposal = proposal_result["messages"][0]
            build_result = asyncio.run(cached_agent._builder_node(cached_state))
            self.assertEqual(
                build_result["messages"][0].feedback_type,
                "build_failed",
            )
            self.assertIn(
                "rejected before Lean build",
                build_result["messages"][0].error_output,
            )
            self.assertEqual(cached_agent.original_proposer_calls, 0)
            events = [
                json.loads(line)
                for line in metrics.read_text(encoding="utf-8").splitlines()
            ]
            rejection = next(
                event
                for event in events
                if event["event"] == "unsafe_proposal_rejected"
            )
            self.assertEqual(rejection["event"], "unsafe_proposal_rejected")
            self.assertEqual(rejection["stage"], "builder_precompile_gate")
            self.assertTrue(rejection["rejected_before_builder"])

        class GeneratedAgent:
            def __init__(self, config, runtime):
                self.llm_client = None
                self.builder_calls = 0

            async def _builder_node(self, state):
                self.builder_calls += 1
                return {"messages": []}

            async def _proposer_node(self, state, config=None):
                return {
                    "messages": [
                        FakeProposalMessage(
                            reasoning="unsafe",
                            code=unsafe_source,
                            location=state.item.location,
                            imports=[],
                            opens=[],
                        )
                    ]
                }

        install_axproverbase_capsule_feedback(
            agent_class=GeneratedAgent,
            build_failed_class=FakeBuildFailedFeedback,
            proposal_class=FakeProposalMessage,
        )
        generated_agent = GeneratedAgent(make_config(), object())
        state = make_state("A", FakeBuildSuccessFeedback())
        proposal_result = asyncio.run(generated_agent._proposer_node(state, {}))
        state.last_proposal = proposal_result["messages"][0]
        build_result = asyncio.run(generated_agent._builder_node(state))
        self.assertEqual(build_result["messages"][0].feedback_type, "build_failed")
        self.assertIn(
            "rejected before Lean build", build_result["messages"][0].error_output
        )
        self.assertEqual(generated_agent.builder_calls, 0)

        malicious = FakeProposalMessage(
            reasoning="unsafe",
            code=unsafe_source,
            location=state.item.location,
            imports=[],
            opens=[],
        )
        builder_state = make_state(
            "A", FakeBuildSuccessFeedback(), last_proposal=malicious
        )
        build_result = asyncio.run(generated_agent._builder_node(builder_state))
        self.assertEqual(build_result["messages"][0].feedback_type, "build_failed")
        self.assertEqual(generated_agent.builder_calls, 0)

    def test_config_is_frozen_to_yxai_responses_memoryless_and_no_summary(self):
        config = make_config()
        enforce_ax_part2_config(config)
        self.assertEqual(config.prover_llm.model, "openai:gpt-5.6-sol")
        self.assertEqual(config.prover_llm.provider_config["base_url"], "https://yxai.chat/v1")
        self.assertTrue(config.prover_llm.provider_config["use_responses_api"])
        self.assertFalse(config.prover_llm.provider_config["store"])
        self.assertEqual(config.prover_llm.provider_config["reasoning"], {"effort": "high"})
        self.assertEqual(config.prover_llm.provider_config["output_version"], "responses/v1")
        self.assertIsNone(config.prover_llm.provider_config["max_tokens"])
        self.assertEqual(config.prover_llm.provider_config["profile"]["max_input_tokens"], 65536)
        self.assertEqual(config.memory_config.class_name, "MemorylessProcessor")
        self.assertEqual(config.memory_config.init_args, {})
        self.assertFalse(config.summarize_output.enabled)
        self.assertIs(config.summarize_output.llm, config.prover_llm)

    def test_sessions_are_isolated_bounded_and_persisted_per_theorem(self):
        with tempfile.TemporaryDirectory() as temp:
            pool = CapsuleFeedbackSessions(max_sessions=2, state_dir=temp)
            a1 = pool.observe("Demo.lean:A", (False, "error: unknown identifier `x`"), round_no=1)
            a2 = pool.observe("Demo.lean:A", (False, "error: unknown identifier `x`"), round_no=2)
            b1 = pool.observe("Demo.lean:B", (False, "error: unknown identifier `x`"), round_no=1)
            pool.observe("Demo.lean:C", (False, "error: type mismatch"), round_no=1)

            self.assertEqual(a1["repeat_count"], 1)
            self.assertEqual(a2["repeat_count"], 2)
            self.assertEqual(b1["repeat_count"], 1)
            self.assertEqual(pool.active_session_count, 2)
            self.assertEqual(len(list(Path(temp).glob("*.json"))), 3)

    def test_wrapper_reuses_original_builder_and_emits_ax_feedback_and_metrics(self):
        class FakeAgent:
            def __init__(self, config, runtime):
                self.config = config
                self.runtime = runtime
                self.builder_calls = 0
                self.original_proposer_calls = 0
                self.llm_client = FakeLLMClient()

            async def _builder_node(self, state):
                self.builder_calls += 1
                return {"messages": [state.fake_feedback], "metrics": {"kept": True}}

            async def _memory_processor_node(self, state):
                return {"experience": ""}

            async def _proposer_node(self, state, config=None):
                self.original_proposer_calls += 1
                await self.llm_client.ainvoke([])
                return {}

            async def _reviewer_node(self, state, config=None):
                await self.llm_client.ainvoke([])
                return {}

            async def chat(self, initial_state, **kwargs):
                return initial_state

        with tempfile.TemporaryDirectory() as temp:
            metrics = Path(temp) / "metrics.jsonl"
            state_dir = Path(temp) / "state"
            cache = Path(temp) / "first-round.json"
            cache.write_text(
                json.dumps({"Demo.lean:A": {"code": "theorem A : True := by trivial"}}),
                encoding="utf-8",
            )
            install_axproverbase_capsule_feedback(
                agent_class=FakeAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                telemetry_path=metrics,
                state_dir=state_dir,
                first_round_cache_path=cache,
            )
            agent = FakeAgent(make_config(), object())
            first = asyncio.run(
                agent._builder_node(
                    make_state("A", FakeBuildFailedFeedback("error: unknown identifier `x`"), 1)
                )
            )
            second = asyncio.run(
                agent._builder_node(
                    make_state("A", FakeBuildFailedFeedback("error: unknown identifier `x`"), 2)
                )
            )
            other = asyncio.run(
                agent._builder_node(
                    make_state("B", FakeBuildFailedFeedback("error: unknown identifier `x`"), 1)
                )
            )
            sorry = asyncio.run(
                agent._builder_node(make_state("A", FakeSorriesFeedback("x : Nat\n⊢ x = x"), 3))
            )
            success_message = FakeBuildSuccessFeedback()
            success = asyncio.run(agent._builder_node(make_state("A", success_message, 4)))
            shared = asyncio.run(
                agent._proposer_node(make_state("A", success_message, 0), {})
            )
            asyncio.run(agent._proposer_node(make_state("A", success_message, 1), {}))
            asyncio.run(agent._reviewer_node(make_state("A", success_message, 1), {}))
            asyncio.run(agent.chat(make_state("A", success_message, 4)))

            self.assertEqual(agent.builder_calls, 5)
            self.assertIn("repeat_count=1", first["messages"][0].error_output)
            self.assertIn("repeat_count=2", second["messages"][0].error_output)
            self.assertIn("repeat_count=1", other["messages"][0].error_output)
            self.assertIn("category=unsolved_goals", sorry["messages"][0].error_output)
            self.assertIs(success["messages"][0], success_message)
            self.assertEqual(shared["messages"][0].code, "theorem A : True := by trivial")
            self.assertEqual(agent.original_proposer_calls, 1)
            self.assertTrue(first["metrics"]["kept"])

            rows = [json.loads(line) for line in metrics.read_text(encoding="utf-8").splitlines()]
            feedback_rows = [row for row in rows if "feedback_text" in row]
            self.assertEqual(len(feedback_rows), 4)
            self.assertTrue(all(row["builder_result_reused"] for row in feedback_rows))
            self.assertTrue(all(row["capsule_compiler_calls"] == 0 for row in feedback_rows))
            self.assertTrue(all(row["capsule_llm_calls"] == 0 for row in feedback_rows))
            self.assertEqual(rows[-1]["memory_llm_calls"], 0)
            self.assertEqual(rows[-1]["model"], "openai:gpt-5.6-sol")
            self.assertEqual(rows[-1]["base_url"], "https://yxai.chat/v1")
            self.assertEqual(rows[-1]["wire_api"], "responses")
            self.assertTrue(rows[-1]["use_responses_api"])
            self.assertFalse(rows[-1]["store"])
            self.assertEqual(rows[-1]["reasoning_effort"], "high")
            self.assertEqual(rows[-1]["node_calls"]["shared_first_round"], 1)
            self.assertEqual(rows[-1]["node_calls"]["proposer_uncached"], 1)
            self.assertEqual(rows[-1]["calls"]["proposer_calls"], 1)
            self.assertEqual(rows[-1]["calls"]["reviewer_calls"], 1)
            self.assertEqual(rows[-1]["calls"]["tool_calls"], 2)
            self.assertEqual(rows[-1]["usage"]["total_tokens"], 28)
            self.assertIsNone(rows[-1]["estimated_cost_usd"])

    def test_configured_first_round_cache_fails_closed_for_a_missing_target(self):
        class FakeAgent:
            def __init__(self, config, runtime):
                pass

            async def _builder_node(self, state):
                return {"messages": []}

            async def _proposer_node(self, state, config=None):
                return {"unexpected": True}

        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "first-round.json"
            cache.write_text(json.dumps({"Demo.lean:A": "theorem A : True := by trivial"}))
            install_axproverbase_capsule_feedback(
                agent_class=FakeAgent,
                build_failed_class=FakeBuildFailedFeedback,
                proposal_class=FakeProposalMessage,
                first_round_cache_path=cache,
            )
            agent = FakeAgent(make_config(), object())
            with self.assertRaisesRegex(KeyError, "no exact entry"):
                asyncio.run(
                    agent._proposer_node(make_state("B", FakeBuildSuccessFeedback(), 0), {})
                )


if __name__ == "__main__":
    unittest.main()
