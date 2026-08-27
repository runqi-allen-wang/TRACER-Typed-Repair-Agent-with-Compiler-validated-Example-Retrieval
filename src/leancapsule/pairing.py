"""Strict pairing checks for Part 1 baseline and Part 2 Capsule runs."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from .feedback import AXPROVER_DEEPSEEK_FLASH_MODEL, DEEPSEEK_BASE_URL


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
        if left_model != AXPROVER_DEEPSEEK_FLASH_MODEL or right_model != left_model:
            errors.append(
                f"{task_id}: model mismatch; both conditions must use {AXPROVER_DEEPSEEK_FLASH_MODEL}"
            )

        left_url = _base_url(left)
        right_url = _base_url(right)
        expected_url = DEEPSEEK_BASE_URL.rstrip("/")
        if left_url != expected_url or right_url != left_url:
            errors.append(f"{task_id}: base_url mismatch; both conditions must use {expected_url}")

        left_budget = left.get("budget")
        right_budget = right.get("budget")
        if not isinstance(left_budget, Mapping) or not left_budget:
            errors.append(f"{task_id}: baseline budget is missing")
        elif not isinstance(right_budget, Mapping) or dict(right_budget) != dict(left_budget):
            errors.append(f"{task_id}: paired budgets do not match")

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
                "budget": dict(left_budget) if isinstance(left_budget, Mapping) else None,
            }
        )

    return {
        "ok": not errors,
        "pair_count": len(pairs),
        "expected_model": AXPROVER_DEEPSEEK_FLASH_MODEL,
        "expected_base_url": DEEPSEEK_BASE_URL,
        "pairs": pairs,
        "errors": errors,
    }


__all__ = ["candidate_digest", "validate_paired_runs"]
