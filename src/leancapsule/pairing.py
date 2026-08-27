"""Strict pairing checks for Part 1 baseline and Part 2 Capsule runs."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

try:
    from compiler import CANDIDATE_POLICY
except ModuleNotFoundError as exc:
    if exc.name != "compiler":
        raise
    from src.compiler import CANDIDATE_POLICY

from .feedback import (
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
)


def candidate_digest(candidate: object) -> str:
    return hashlib.sha256(str(candidate or "").encode("utf-8")).hexdigest()


def _task_id(row: Mapping[str, Any]) -> str:
    return str(row.get("task_id") or row.get("problem_id") or "")


def _base_url(row: Mapping[str, Any]) -> str:
    provider = row.get("provider_config")
    if isinstance(provider, Mapping):
        value = provider.get("base_url")
        if value:
            return str(value).rstrip("/")
    return str(row.get("base_url") or "").rstrip("/")


def _provider_value(row: Mapping[str, Any], name: str, default: object = None) -> object:
    provider = row.get("provider_config")
    if isinstance(provider, Mapping) and name in provider:
        return provider[name]
    return row.get(name, default)


def _reasoning_effort(row: Mapping[str, Any]) -> str:
    reasoning = _provider_value(row, "reasoning", {})
    if isinstance(reasoning, Mapping) and reasoning.get("effort"):
        return str(reasoning["effort"])
    return str(_provider_value(row, "reasoning_effort", ""))


def _index(rows: Iterable[Mapping[str, Any]], label: str, errors: list[str]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        task_id = _task_id(row)
        if not task_id:
            errors.append(f"{label} row is missing task_id/problem_id")
            continue
        if task_id in indexed:
            errors.append(f"{label} contains duplicate task_id: {task_id}")
            continue
        indexed[task_id] = row
    return indexed


def validate_paired_runs(
    baseline_rows: Iterable[Mapping[str, Any]],
    capsule_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require exact first-candidate, model, endpoint, and budget pairing."""

    errors: list[str] = []
    baseline = _index(baseline_rows, "baseline", errors)
    capsule = _index(capsule_rows, "capsule", errors)
    baseline_ids = set(baseline)
    capsule_ids = set(capsule)
    for missing in sorted(baseline_ids - capsule_ids):
        errors.append(f"capsule is missing task_id: {missing}")
    for missing in sorted(capsule_ids - baseline_ids):
        errors.append(f"baseline is missing task_id: {missing}")

    pairs: list[dict[str, Any]] = []
    for task_id in sorted(baseline_ids & capsule_ids):
        left = baseline[task_id]
        right = capsule[task_id]
        left_candidate = str(left.get("first_round_candidate") or "")
        right_candidate = str(right.get("first_round_candidate") or "")
        digest = candidate_digest(left_candidate)
        if not left_candidate or not right_candidate:
            errors.append(f"{task_id}: first_round_candidate is empty")
        elif left_candidate != right_candidate:
            errors.append(f"{task_id}: first_round_candidate mismatch")

        left_model = str(left.get("model") or "")
        right_model = str(right.get("model") or "")
        if left_model != AXPROVER_YXAI_MODEL or right_model != left_model:
            errors.append(
                f"{task_id}: model mismatch; both conditions must use {AXPROVER_YXAI_MODEL}"
            )

        left_url = _base_url(left)
        right_url = _base_url(right)
        expected_url = YXAI_BASE_URL.rstrip("/")
        if left_url != expected_url or right_url != left_url:
            errors.append(f"{task_id}: base_url mismatch; both conditions must use {expected_url}")

        left_wire_api = str(_provider_value(left, "wire_api", ""))
        right_wire_api = str(_provider_value(right, "wire_api", ""))
        left_responses = _provider_value(left, "use_responses_api")
        right_responses = _provider_value(right, "use_responses_api")
        if (
            left_wire_api != YXAI_WIRE_API
            or right_wire_api != left_wire_api
            or left_responses is not True
            or right_responses is not True
        ):
            errors.append(f"{task_id}: both conditions must use the Responses API")

        left_store = _provider_value(left, "store")
        right_store = _provider_value(right, "store")
        if left_store is not YXAI_STORE_RESPONSES or right_store is not left_store:
            errors.append(f"{task_id}: both conditions must disable response storage")

        left_effort = _reasoning_effort(left)
        right_effort = _reasoning_effort(right)
        if left_effort != YXAI_REASONING_EFFORT or right_effort != left_effort:
            errors.append(
                f"{task_id}: both conditions must use reasoning effort {YXAI_REASONING_EFFORT}"
            )

        left_budget = left.get("budget")
        right_budget = right.get("budget")
        if not isinstance(left_budget, Mapping) or not left_budget:
            errors.append(f"{task_id}: baseline budget is missing")
        elif not isinstance(right_budget, Mapping) or dict(right_budget) != dict(left_budget):
            errors.append(f"{task_id}: paired budgets do not match")

        left_policy = left.get("candidate_policy")
        right_policy = right.get("candidate_policy")
        if not isinstance(left_policy, Mapping) or dict(left_policy) != CANDIDATE_POLICY:
            errors.append(f"{task_id}: baseline candidate_policy is not tracer-candidate-v2")
        elif not isinstance(right_policy, Mapping) or dict(right_policy) != dict(left_policy):
            errors.append(f"{task_id}: paired candidate security policies do not match")

        calls = right.get("calls")
        if not isinstance(calls, Mapping):
            errors.append(f"{task_id}: capsule call counters are missing")
        else:
            if calls.get("memory_calls") != 0:
                errors.append(f"{task_id}: Capsule condition memory_calls must be 0")
            if calls.get("capsule_llm_calls", 0) != 0:
                errors.append(f"{task_id}: CapsuleFeedback made an LLM call")
            if calls.get("capsule_compiler_calls", 0) != 0:
                errors.append(f"{task_id}: CapsuleFeedback made an extra compiler call")

        pairs.append(
            {
                "task_id": task_id,
                "candidate_sha256": digest,
                "model": left_model,
                "base_url": left_url,
                "wire_api": left_wire_api,
                "store": left_store,
                "reasoning_effort": left_effort,
                "budget": dict(left_budget) if isinstance(left_budget, Mapping) else None,
                "candidate_policy": (
                    dict(left_policy) if isinstance(left_policy, Mapping) else None
                ),
            }
        )

    return {
        "ok": not errors,
        "pair_count": len(pairs),
        "expected_model": AXPROVER_YXAI_MODEL,
        "expected_base_url": YXAI_BASE_URL,
        "expected_wire_api": YXAI_WIRE_API,
        "expected_store": YXAI_STORE_RESPONSES,
        "expected_reasoning_effort": YXAI_REASONING_EFFORT,
        "expected_candidate_policy": dict(CANDIDATE_POLICY),
        "pairs": pairs,
        "errors": errors,
    }


__all__ = ["candidate_digest", "validate_paired_runs"]
