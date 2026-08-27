"""Run one Part 1 AxProverBase target through the Python API.

The pinned Ax CLI only serializes ``success/error/summary``. This runner uses
``ProverAgentState`` directly so the first full theorem, Ax metrics and LLM
usage remain available for the Part 1/Part 2 paired experiment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compiler import CANDIDATE_POLICY  # noqa: E402
from leancapsule.ax_integration import validate_ax_proposal_safety  # noqa: E402
from leancapsule.feedback import (  # noqa: E402
    AXPROVERBASE_COMMIT,
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
)


_USAGE = {"prompt": 0, "completion": 0, "calls": 0}
_USAGE_PATCH_MARKER = "__tracer_part1_usage_tracking__"
_SAFETY_PATCH_MARKER = "__tracer_part1_safety_gate__"


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _response_usage(response: object) -> tuple[int, int]:
    usage = _read(response, "usage_metadata", {})
    if not isinstance(usage, Mapping) or not usage:
        metadata = _read(response, "response_metadata", {})
        usage = metadata.get("token_usage", {}) if isinstance(metadata, Mapping) else {}
    if not isinstance(usage, Mapping):
        return 0, 0
    prompt = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    completion = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    return prompt, completion


def _install_usage_tracking() -> None:
    """Patch the pinned Ax LLM client once, without importing Ax during unit tests."""

    from ax_prover.utils import llm as llm_module

    llm_client = llm_module.LLMClient
    if getattr(llm_client, _USAGE_PATCH_MARKER, False):
        return
    original = llm_client.ainvoke

    async def tracked(self: object, messages: object, **kwargs: object) -> object:
        response = await original(self, messages, **kwargs)
        prompt, completion = _response_usage(response)
        _USAGE["prompt"] += prompt
        _USAGE["completion"] += completion
        _USAGE["calls"] += 1
        return response

    llm_client.ainvoke = tracked
    setattr(llm_client, _USAGE_PATCH_MARKER, True)


def _install_safety_gate(agent_class: type) -> None:
    """Reject unsafe full-theorem proposals before Ax invokes Lean."""

    if getattr(agent_class, _SAFETY_PATCH_MARKER, False):
        return
    original_builder = agent_class._builder_node

    async def guarded_builder(self: object, state: object) -> dict:
        proposal = _read(state, "last_proposal")
        if proposal is not None:
            violation = validate_ax_proposal_safety(
                state,
                _read(proposal, "code", ""),
                imports=_read(proposal, "imports", []),
                opens=_read(proposal, "opens", []),
            )
            if violation:
                raise ValueError(f"Ax proposal rejected before Lean build: {violation}")

        started = time.perf_counter()
        try:
            return await original_builder(self, state)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self._tracer_part1_builder_calls = (
                int(getattr(self, "_tracer_part1_builder_calls", 0)) + 1
            )
            self._tracer_part1_builder_elapsed_ms = (
                float(getattr(self, "_tracer_part1_builder_elapsed_ms", 0.0)) + elapsed
            )

    agent_class._builder_node = guarded_builder
    setattr(agent_class, _SAFETY_PATCH_MARKER, True)


def _snap_usage() -> dict[str, int]:
    return dict(_USAGE)


def _usage_diff(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {key: int(after[key]) - int(before[key]) for key in before}


def _proposal_messages(state: object) -> list[object]:
    messages = list(_read(state, "messages", []) or [])
    return [message for message in messages if _read(message, "type") == "proposal"]


def _reviewer_call_count(state: object) -> int:
    messages = list(_read(state, "messages", []) or [])
    return sum(
        1
        for message in messages
        if _read(message, "feedback_type") in {"review_approved", "review_rejected"}
    )


def _contract_from_config(config: object) -> dict[str, Any]:
    prover = _read(config, "prover")
    llm = _read(prover, "prover_llm")
    provider = _read(llm, "provider_config", {})
    reasoning = _read(provider, "reasoning", {})
    profile = _read(provider, "profile", {})
    memory = _read(prover, "memory_config")
    summary = _read(prover, "summarize_output")
    runtime = _read(config, "runtime")

    contract = {
        "model": str(_read(llm, "model", "")),
        "provider_config": {
            "base_url": str(_read(provider, "base_url", "")).rstrip("/"),
            "wire_api": YXAI_WIRE_API,
            "use_responses_api": _read(provider, "use_responses_api"),
            "store": _read(provider, "store"),
            "reasoning": {"effort": str(_read(reasoning, "effort", ""))},
            "output_version": str(_read(provider, "output_version", "")),
            "max_tokens": _read(provider, "max_tokens"),
            "profile": {"max_input_tokens": _read(profile, "max_input_tokens")},
        },
        "budget": {
            "max_iterations": int(_read(prover, "max_iterations", 0)),
            "max_input_tokens": int(_read(profile, "max_input_tokens", 0)),
            "max_tool_calling_iterations": int(
                _read(runtime, "max_tool_calling_iterations", 0)
            ),
        },
        "memory_processor": str(_read(memory, "class_name", "")),
        "summary_enabled": bool(_read(summary, "enabled", True)),
    }
    errors: list[str] = []
    provider_contract = contract["provider_config"]
    if contract["model"] != AXPROVER_YXAI_MODEL:
        errors.append(f"model must be {AXPROVER_YXAI_MODEL}")
    if provider_contract["base_url"] != YXAI_BASE_URL:
        errors.append(f"base_url must be {YXAI_BASE_URL}")
    if provider_contract["use_responses_api"] is not True:
        errors.append("use_responses_api must be true")
    if provider_contract["store"] is not YXAI_STORE_RESPONSES:
        errors.append("store must be false")
    if provider_contract["reasoning"]["effort"] != YXAI_REASONING_EFFORT:
        errors.append(f"reasoning effort must be {YXAI_REASONING_EFFORT}")
    if provider_contract["output_version"] != "responses/v1":
        errors.append("output_version must be responses/v1")
    if contract["memory_processor"] != "ExperienceProcessor":
        errors.append("Part 1 memory must be ExperienceProcessor")
    if contract["summary_enabled"]:
        errors.append("final LLM summary must be disabled")
    if contract["budget"]["max_iterations"] <= 0:
        errors.append("max_iterations must be positive")
    if errors:
        raise ValueError("invalid Part 1 experiment config: " + "; ".join(errors))
    return contract


def extract_record(
    target: str,
    state: object,
    usage: Mapping[str, int],
    price: Mapping[str, float | None],
    contract: Mapping[str, Any],
    *,
    task_metadata: Mapping[str, Any] | None = None,
    run_elapsed_ms: int = 0,
    builder_elapsed_ms: int = 0,
    builder_calls: int = 0,
) -> dict[str, Any]:
    """Extract a pairing-ready Part 1 record from ``ProverAgentState``."""

    metadata = dict(task_metadata or {})
    proposals = _proposal_messages(state)
    first = proposals[0] if proposals else None
    metrics_obj = _read(state, "metrics")
    metrics = metrics_obj.model_dump() if hasattr(metrics_obj, "model_dump") else {}
    prompt = int(usage.get("prompt", 0))
    completion = int(usage.get("completion", 0))
    total = prompt + completion
    price_in = price.get("input_usd_per_1k")
    price_out = price.get("output_usd_per_1k")
    cost = (
        (prompt / 1000 * price_in) + (completion / 1000 * price_out)
        if isinstance(price_in, (int, float)) and isinstance(price_out, (int, float))
        else None
    )
    rounds = int(_read(state, "iteration_count", len(proposals)) or len(proposals))
    state_item = _read(state, "item")
    location = _read(state_item, "location")
    theorem = str(metadata.get("theorem") or _read(location, "name", ""))
    module = str(metadata.get("module") or "")
    is_proven = bool(_read(state_item, "is_proven", _read(state, "approved", False)))
    reviewer_calls = _reviewer_call_count(state)
    proposer_calls = len(proposals)
    total_llm_calls = int(usage.get("calls", 0))
    memory_calls = max(0, total_llm_calls - proposer_calls - reviewer_calls)
    provider_contract = dict(contract["provider_config"])

    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_id": str(metadata.get("id") or target),
        "target": target,
        "module": module,
        "theorem": theorem,
        "path": str(_read(location, "path", "")),
        "condition": "baseline",
        "memory_mode": "self_managed",
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": contract["model"],
        "base_url": provider_contract["base_url"],
        "wire_api": provider_contract["wire_api"],
        "use_responses_api": provider_contract["use_responses_api"],
        "store": provider_contract["store"],
        "reasoning_effort": provider_contract["reasoning"]["effort"],
        "provider_config": provider_contract,
        "budget": dict(contract["budget"]),
        "candidate_policy": dict(CANDIDATE_POLICY),
        "compile_ok": is_proven,
        "success_node": rounds if is_proven else None,
        "rounds": rounds,
        "iteration_count": metrics.get("number_of_iterations", rounds),
        "compilation_error_count": metrics.get("compilation_error_count", 0),
        "build_timeout_count": metrics.get("build_timeout_count", 0),
        "reviewer_rejections": metrics.get("reviewer_rejections", 0),
        "max_iterations_reached": metrics.get("max_iterations_reached", False),
        "run_elapsed_ms": run_elapsed_ms,
        "compile_elapsed_ms": builder_elapsed_ms,
        "calls": {
            "proposer_calls": proposer_calls,
            "memory_calls": memory_calls,
            "reviewer_calls": reviewer_calls,
            "tool_calls": 0,
            "compiler_calls": builder_calls,
        },
        "call_count": total_llm_calls,
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        },
        "estimated_cost_usd": round(cost, 6) if cost is not None else None,
        "first_round_candidate": str(_read(first, "code", "")) if first else "",
        "first_round_reasoning": str(_read(first, "reasoning", "")) if first else "",
        "first_round_imports": list(_read(first, "imports", []) or []) if first else [],
        "first_round_opens": list(_read(first, "opens", []) or []) if first else [],
        "candidate_count": len(proposals),
    }


async def run_target(
    target: str,
    folder: str,
    config_yaml: str,
    price: Mapping[str, float | None],
    task_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from ax_prover.config import Config
    from ax_prover.prover.agent import ProverAgent
    from ax_prover.runtime import Runtime
    from ax_prover.tools import create_tool_lifespans
    from ax_prover.utils import (
        load_env_secrets,
        merge_configs,
        parse_prove_target,
        prove_single_item,
    )

    _install_usage_tracking()
    _install_safety_gate(ProverAgent)
    load_env_secrets(folder)
    config = merge_configs([Config(), "default.yaml", config_yaml], folder=folder)
    contract = _contract_from_config(config)
    tool_lifespans = await create_tool_lifespans(config.prover.proposer_tools)
    records: list[dict[str, Any]] = []
    async with Runtime.open(config.runtime, folder, tool_lifespans) as runtime:
        items = await parse_prove_target(runtime.lean_interact_server, folder, target)
        for item in items:
            before = _snap_usage()
            prover = await ProverAgent.create(config=config.prover, runtime=runtime)
            thread_id = f"part1_{item.location.name}_{uuid.uuid4().hex[:6]}"
            started = time.perf_counter()
            state = await prove_single_item(prover, item, thread_id=thread_id)
            run_elapsed_ms = int((time.perf_counter() - started) * 1000)
            used = _usage_diff(before, _snap_usage())
            records.append(
                extract_record(
                    target,
                    state,
                    used,
                    price,
                    contract,
                    task_metadata=task_metadata,
                    run_elapsed_ms=run_elapsed_ms,
                    builder_elapsed_ms=int(
                        getattr(prover, "_tracer_part1_builder_elapsed_ms", 0.0)
                    ),
                    builder_calls=int(getattr(prover, "_tracer_part1_builder_calls", 0)),
                )
            )
    return records


def _cost_text(cost: object) -> str:
    return "unknown" if not isinstance(cost, (int, float)) else f"${cost:.6f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--price-out", type=float)
    parser.add_argument("--price-in", type=float)
    args = parser.parse_args()

    price = {"input_usd_per_1k": args.price_in, "output_usd_per_1k": args.price_out}
    records = asyncio.run(run_target(args.target, args.folder, args.config, price))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} record(s) -> {output}")
    for record in records:
        print(
            f"  {record['theorem']}: proven={record['compile_ok']} "
            f"rounds={record['rounds']} calls={record['call_count']} "
            f"tokens={record['usage']['total_tokens']} "
            f"cost={_cost_text(record['estimated_cost_usd'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
