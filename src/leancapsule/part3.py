"""Strict comparison and reporting helpers for the Part 3 Raw/Capsule pilot."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .feedback import (
    AXPROVERBASE_COMMIT,
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read JSONL and fail on malformed or non-object rows."""

    source = Path(path)
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{source}:{line_no} must be a JSON object")
        rows.append(value)
    return rows


def _index(
    rows: Iterable[Mapping[str, Any]], label: str, errors: list[str]
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row_no, row in enumerate(rows, 1):
        task_id = str(row.get("task_id") or "")
        if not task_id:
            errors.append(f"{label} row {row_no} is missing task_id")
            continue
        if task_id in indexed:
            errors.append(f"{label} contains duplicate task_id: {task_id}")
            continue
        indexed[task_id] = row
    return indexed


def _provider_value(row: Mapping[str, Any], name: str, default: object = None) -> object:
    provider = row.get("provider_config")
    if isinstance(provider, Mapping) and name in provider:
        return provider[name]
    return row.get(name, default)


def _reasoning_effort(row: Mapping[str, Any]) -> str:
    reasoning = _provider_value(row, "reasoning", {})
    if isinstance(reasoning, Mapping):
        return str(reasoning.get("effort") or "")
    return str(row.get("reasoning_effort") or "")


def _contract_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    provider = row.get("provider_config")
    provider = provider if isinstance(provider, Mapping) else {}
    reasoning = provider.get("reasoning")
    reasoning = reasoning if isinstance(reasoning, Mapping) else {}
    profile = provider.get("profile")
    profile = profile if isinstance(profile, Mapping) else {}
    return {
        "axproverbase_commit": str(row.get("axproverbase_commit") or ""),
        "model": str(row.get("model") or ""),
        "base_url": str(provider.get("base_url") or row.get("base_url") or "").rstrip("/"),
        "wire_api": str(provider.get("wire_api") or row.get("wire_api") or ""),
        "use_responses_api": provider.get(
            "use_responses_api", row.get("use_responses_api")
        ),
        "store": provider.get("store", row.get("store")),
        "reasoning_effort": str(
            reasoning.get("effort") or row.get("reasoning_effort") or ""
        ),
        "output_version": str(provider.get("output_version") or ""),
        "max_tokens": provider.get("max_tokens"),
        "max_input_tokens": profile.get("max_input_tokens"),
        "budget": dict(row.get("budget")) if isinstance(row.get("budget"), Mapping) else None,
        "candidate_policy": (
            dict(row.get("candidate_policy"))
            if isinstance(row.get("candidate_policy"), Mapping)
            else None
        ),
    }


def _first_round_success(row: Mapping[str, Any]) -> bool:
    try:
        rounds = int(row.get("rounds", 0) or 0)
    except (TypeError, ValueError):
        rounds = 0
    return bool(row.get("compile_ok")) and rounds == 1


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _events(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    events = row.get("feedback_events", [])
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, Mapping)]


def _validate_common_contract(
    task_id: str,
    raw: Mapping[str, Any],
    capsule: Mapping[str, Any],
    errors: list[str],
) -> None:
    raw_contract = _contract_signature(raw)
    capsule_contract = _contract_signature(capsule)
    expected = {
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": AXPROVER_YXAI_MODEL,
        "base_url": YXAI_BASE_URL,
        "wire_api": YXAI_WIRE_API,
        "use_responses_api": True,
        "store": YXAI_STORE_RESPONSES,
        "reasoning_effort": YXAI_REASONING_EFFORT,
        "output_version": "responses/v1",
        "max_input_tokens": 65536,
    }
    for field, expected_value in expected.items():
        if raw_contract.get(field) != expected_value:
            errors.append(f"{task_id}: raw {field} must be {expected_value!r}")
        if capsule_contract.get(field) != expected_value:
            errors.append(f"{task_id}: capsule {field} must be {expected_value!r}")
        if raw_contract.get(field) != capsule_contract.get(field):
            errors.append(f"{task_id}: paired {field} mismatch")
    if raw_contract["budget"] is None:
        errors.append(f"{task_id}: raw budget is missing")
    if capsule_contract["budget"] is None:
        errors.append(f"{task_id}: capsule budget is missing")
    if raw_contract["budget"] != capsule_contract["budget"]:
        errors.append(f"{task_id}: paired budgets do not match")
    if raw_contract["candidate_policy"] != {
        "version": "tracer-candidate-v2",
        "meta_execution": "blocked",
        "unsafe_declarations": "blocked",
        "environment": "minimal",
    }:
        errors.append(f"{task_id}: raw candidate policy is not tracer-candidate-v2")
    if capsule_contract["candidate_policy"] != raw_contract["candidate_policy"]:
        errors.append(f"{task_id}: paired candidate security policies do not match")


def _validate_events(task_id: str, row: Mapping[str, Any], mode: str, errors: list[str]) -> None:
    events = _events(row)
    for event in events:
        if event.get("feedback_mode") != mode:
            errors.append(f"{task_id}: {mode} feedback event has the wrong mode")
        if "feedback_text" not in event and "fingerprint" not in event:
            errors.append(f"{task_id}: {mode} feedback event lacks feedback_text")
        for field in ("category", "repeat_count", "round"):
            if field not in event:
                errors.append(f"{task_id}: {mode} feedback event lacks {field}")
        if event.get("capsule_llm_calls") != 0:
            errors.append(f"{task_id}: {mode} feedback event reports Capsule LLM work")
        if event.get("capsule_compiler_calls") != 0:
            errors.append(f"{task_id}: {mode} feedback event reports Capsule compiler work")
    if mode == "raw":
        if any(event.get("builder_result_reused") is not False for event in events):
            errors.append(f"{task_id}: Raw feedback is not marked as passthrough")
    else:
        if any(event.get("builder_result_reused") is not True for event in events):
            errors.append(f"{task_id}: Capsule feedback is not marked as builder-result reuse")


def validate_part3_runs(
    raw_rows: Iterable[Mapping[str, Any]],
    capsule_rows: Iterable[Mapping[str, Any]],
    *,
    baseline_rows: Iterable[Mapping[str, Any]] | None = None,
    expected_count: int = 25,
    error_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate a complete Raw/Capsule paired run and return per-task pairs."""

    errors: list[str] = []
    warnings: list[str] = []
    raw = _index(raw_rows, "raw", errors)
    capsule = _index(capsule_rows, "capsule", errors)
    baseline = _index(baseline_rows or [], "baseline", errors) if baseline_rows is not None else {}
    if expected_count <= 0:
        errors.append("expected_count must be positive")
    for label, indexed in (("raw", raw), ("capsule", capsule)):
        if len(indexed) != expected_count:
            errors.append(
                f"{label} must contain exactly {expected_count} unique tasks; got {len(indexed)}"
            )
    if baseline_rows is not None and len(baseline) != expected_count:
        errors.append(
            f"baseline must contain exactly {expected_count} unique tasks; got {len(baseline)}"
        )

    raw_ids = set(raw)
    capsule_ids = set(capsule)
    for task_id in sorted(raw_ids - capsule_ids):
        errors.append(f"capsule is missing task_id: {task_id}")
    for task_id in sorted(capsule_ids - raw_ids):
        errors.append(f"raw is missing task_id: {task_id}")
    if baseline_rows is not None:
        for task_id in sorted(set(baseline) - (raw_ids & capsule_ids)):
            errors.append(f"Part 3 conditions are missing baseline task_id: {task_id}")
        for task_id in sorted((raw_ids & capsule_ids) - set(baseline)):
            errors.append(f"baseline is missing Part 3 task_id: {task_id}")

    if error_rows is not None:
        for row in error_rows:
            task_id = str(row.get("task_id") or "")
            condition = str(row.get("condition") or "")
            errors.append(
                f"unreported infrastructure error: {condition or 'unknown'}:{task_id or 'unknown'}"
            )

    pairs: list[dict[str, Any]] = []
    for task_id in sorted(raw_ids & capsule_ids):
        left = raw[task_id]
        right = capsule[task_id]
        if str(left.get("condition") or "") != "raw":
            errors.append(f"{task_id}: raw condition must be raw")
        if str(right.get("condition") or "") != "capsule":
            errors.append(f"{task_id}: capsule condition must be capsule")
        if str(left.get("feedback_mode") or "") != "raw":
            errors.append(f"{task_id}: raw feedback_mode must be raw")
        if str(right.get("feedback_mode") or "") != "capsule":
            errors.append(f"{task_id}: capsule feedback_mode must be capsule")
        if str(left.get("memory_mode") or "") != "raw_feedback":
            errors.append(f"{task_id}: raw memory_mode must be raw_feedback")
        if str(right.get("memory_mode") or "") != "capsule_feedback":
            errors.append(f"{task_id}: capsule memory_mode must be capsule_feedback")
        for row, label in ((left, "raw"), (right, "capsule")):
            if str(row.get("memory_processor") or "") != "MemorylessProcessor":
                errors.append(f"{task_id}: {label} memory_processor must be MemorylessProcessor")
        for field in ("target", "module", "theorem", "path"):
            if str(left.get(field) or "") != str(right.get(field) or ""):
                errors.append(f"{task_id}: paired {field} mismatch")
            if not str(left.get(field) or ""):
                errors.append(f"{task_id}: paired {field} is missing")
        expected_target = f"{left.get('module', '')}:{left.get('theorem', '')}"
        if left.get("target") != expected_target or right.get("target") != expected_target:
            errors.append(f"{task_id}: target does not match module/theorem")

        _validate_common_contract(task_id, left, right, errors)
        for row, label in ((left, "raw"), (right, "capsule")):
            calls = row.get("calls")
            if not isinstance(calls, Mapping):
                errors.append(f"{task_id}: {label} call counters are missing")
            else:
                if calls.get("memory_calls") != 0:
                    errors.append(f"{task_id}: {label} memory_calls must be 0")
                if calls.get("capsule_llm_calls") != 0:
                    errors.append(f"{task_id}: {label} capsule_llm_calls must be 0")
                if calls.get("capsule_compiler_calls") != 0:
                    errors.append(f"{task_id}: {label} capsule_compiler_calls must be 0")
            if row.get("api_error_count", 0) not in (0, None):
                errors.append(f"{task_id}: {label} reports an API error")
            _validate_events(task_id, row, label, errors)

        candidate_fields = (
            "first_round_candidate",
            "first_round_reasoning",
            "first_round_imports",
            "first_round_opens",
        )
        for field in candidate_fields:
            if left.get(field) != right.get(field):
                errors.append(f"{task_id}: {field} mismatch")
        candidate = str(left.get("first_round_candidate") or "")
        if not candidate.strip():
            errors.append(f"{task_id}: first_round_candidate is empty")
        if baseline_rows is not None and task_id in baseline:
            reference = baseline[task_id]
            for field in candidate_fields:
                if left.get(field) != reference.get(field):
                    errors.append(f"{task_id}: {field} differs from shared baseline candidate")

        first_round_reference = (
            _first_round_success(baseline[task_id])
            if task_id in baseline
            else _first_round_success(left)
        )
        raw_success = bool(left.get("compile_ok"))
        capsule_success = bool(right.get("compile_ok"))
        raw_rounds = _safe_int(left.get("rounds"))
        capsule_rounds = _safe_int(right.get("rounds"))
        if first_round_reference and (raw_rounds != 1 or capsule_rounds != 1):
            warnings.append(f"{task_id}: conditions differ from the baseline first-round outcome")
        if not first_round_reference and (raw_rounds == 1 or capsule_rounds == 1):
            warnings.append(f"{task_id}: a Part 3 condition succeeded in round 1 after baseline failure")
        raw_calls = left.get("calls") if isinstance(left.get("calls"), Mapping) else {}
        capsule_calls = right.get("calls") if isinstance(right.get("calls"), Mapping) else {}
        raw_usage = left.get("usage") if isinstance(left.get("usage"), Mapping) else {}
        capsule_usage = right.get("usage") if isinstance(right.get("usage"), Mapping) else {}
        raw_repeated = _safe_int(left.get("repeated_diagnostic_count"))
        capsule_repeated = _safe_int(right.get("repeated_diagnostic_count"))
        pairs.append(
            {
                "task_id": task_id,
                "target": str(left.get("target") or ""),
                "module": str(left.get("module") or ""),
                "theorem": str(left.get("theorem") or ""),
                "path": str(left.get("path") or ""),
                "first_round_candidate_equal": bool(candidate)
                and candidate == str(right.get("first_round_candidate") or ""),
                "first_round_proposal_equal": all(
                    left.get(field) == right.get(field)
                    for field in (
                        "first_round_candidate",
                        "first_round_reasoning",
                        "first_round_imports",
                        "first_round_opens",
                    )
                ),
                "first_round_success_reference": first_round_reference,
                "raw_success": raw_success,
                "capsule_success": capsule_success,
                "raw_rounds": raw_rounds,
                "capsule_rounds": capsule_rounds,
                "raw_second_round_repair": (not first_round_reference and raw_success and raw_rounds == 2),
                "capsule_second_round_repair": (
                    not first_round_reference and capsule_success and capsule_rounds == 2
                ),
                "raw_final_repair": not first_round_reference and raw_success,
                "capsule_final_repair": not first_round_reference and capsule_success,
                "raw_compilation_errors": _safe_int(left.get("compilation_error_count")),
                "capsule_compilation_errors": _safe_int(right.get("compilation_error_count")),
                "raw_proposer_calls": _safe_int(raw_calls.get("proposer_calls")),
                "capsule_proposer_calls": _safe_int(capsule_calls.get("proposer_calls")),
                "raw_reviewer_calls": _safe_int(raw_calls.get("reviewer_calls")),
                "capsule_reviewer_calls": _safe_int(capsule_calls.get("reviewer_calls")),
                "raw_llm_calls": _safe_int(left.get("call_count")),
                "capsule_llm_calls": _safe_int(right.get("call_count")),
                "raw_total_tokens": _safe_int(raw_usage.get("total_tokens")),
                "capsule_total_tokens": _safe_int(capsule_usage.get("total_tokens")),
                "raw_repeated_diagnostics": raw_repeated,
                "capsule_repeated_diagnostics": capsule_repeated,
                "raw_api_errors": _safe_int(left.get("api_error_count")),
                "capsule_api_errors": _safe_int(right.get("api_error_count")),
            }
        )

    return {
        "ok": not errors and len(pairs) == expected_count,
        "expected_count": expected_count,
        "pair_count": len(pairs),
        "expected_model": AXPROVER_YXAI_MODEL,
        "expected_axproverbase_commit": AXPROVERBASE_COMMIT,
        "expected_base_url": YXAI_BASE_URL,
        "expected_wire_api": YXAI_WIRE_API,
        "expected_store": YXAI_STORE_RESPONSES,
        "expected_reasoning_effort": YXAI_REASONING_EFFORT,
        "raw_condition": "MemorylessProcessor + original Ax BuildFailedFeedback",
        "capsule_condition": "MemorylessProcessor + CapsuleFeedback",
        "pairs": pairs,
        "warnings": warnings,
        "errors": errors,
    }


def _aggregate(pairs: list[Mapping[str, Any]], prefix: str, first_round_failed: list[Mapping[str, Any]]) -> dict[str, Any]:
    success_key = f"{prefix}_success"
    return {
        "successful_tasks": sum(bool(row.get(success_key)) for row in pairs),
        "first_round_success_tasks": sum(
            bool(row.get("first_round_success_reference") and row.get(success_key)) for row in pairs
        ),
        "first_round_failure_tasks": len(first_round_failed),
        "second_round_repairs_after_first_failure": sum(
            bool(row.get(f"{prefix}_second_round_repair")) for row in first_round_failed
        ),
        "final_repairs_after_first_failure": sum(
            bool(row.get(f"{prefix}_final_repair")) for row in first_round_failed
        ),
        "total_rounds": sum(_safe_int(row.get(f"{prefix}_rounds")) for row in pairs),
        "compilation_errors": sum(_safe_int(row.get(f"{prefix}_compilation_errors")) for row in pairs),
        "proposer_calls": sum(_safe_int(row.get(f"{prefix}_proposer_calls")) for row in pairs),
        "reviewer_calls": sum(_safe_int(row.get(f"{prefix}_reviewer_calls")) for row in pairs),
        "llm_calls": sum(_safe_int(row.get(f"{prefix}_llm_calls")) for row in pairs),
        "total_tokens": sum(_safe_int(row.get(f"{prefix}_total_tokens")) for row in pairs),
        "repeated_diagnostics": sum(
            _safe_int(row.get(f"{prefix}_repeated_diagnostics")) for row in pairs
        ),
        "api_errors": sum(_safe_int(row.get(f"{prefix}_api_errors")) for row in pairs),
    }


def build_summary(pairing: Mapping[str, Any]) -> dict[str, Any]:
    pairs = [row for row in pairing.get("pairs", []) if isinstance(row, Mapping)]
    first_round_failed = [
        row for row in pairs if not bool(row.get("first_round_success_reference"))
    ]
    raw = _aggregate(pairs, "raw", first_round_failed)
    capsule = _aggregate(pairs, "capsule", first_round_failed)
    differences: dict[str, Any] = {}
    for key in raw:
        if isinstance(raw[key], (int, float)) and isinstance(capsule[key], (int, float)):
            differences[key] = capsule[key] - raw[key]
    return {
        "format": "tracer-part3-summary-v1",
        "pairing_ok": bool(pairing.get("ok")),
        "pair_count": len(pairs),
        "first_round_success_count": sum(
            bool(row.get("first_round_success_reference")) for row in pairs
        ),
        "first_round_failure_count": len(first_round_failed),
        "first_round_failure_task_ids": [str(row.get("task_id")) for row in first_round_failed],
        "conditions": {"raw": raw, "capsule": capsule},
        "capsule_minus_raw": differences,
        "warnings": list(pairing.get("warnings", [])),
        "errors": list(pairing.get("errors", [])),
    }


CSV_FIELDS = [
    "task_id",
    "module",
    "theorem",
    "first_round_success_reference",
    "raw_success",
    "capsule_success",
    "raw_rounds",
    "capsule_rounds",
    "raw_second_round_repair",
    "capsule_second_round_repair",
    "raw_final_repair",
    "capsule_final_repair",
    "raw_compilation_errors",
    "capsule_compilation_errors",
    "raw_proposer_calls",
    "capsule_proposer_calls",
    "raw_reviewer_calls",
    "capsule_reviewer_calls",
    "raw_llm_calls",
    "capsule_llm_calls",
    "raw_total_tokens",
    "capsule_total_tokens",
    "raw_repeated_diagnostics",
    "capsule_repeated_diagnostics",
    "raw_api_errors",
    "capsule_api_errors",
]


def write_part3_outputs(pairing: Mapping[str, Any], out_dir: str | Path) -> dict[str, Path]:
    """Write the six requested Part 3 handoff artifacts."""

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    pairing_path = output / "pairing.json"
    summary_path = output / "summary.json"
    csv_path = output / "per-task.csv"
    report_path = output / "REPORT.md"
    summary = build_summary(pairing)
    pairing_path.write_text(json.dumps(dict(pairing), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pairs = [row for row in pairing.get("pairs", []) if isinstance(row, Mapping)]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in pairs:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})

    report_path.write_text(_render_report(pairing, summary), encoding="utf-8")
    return {
        "pairing": pairing_path,
        "summary": summary_path,
        "per_task": csv_path,
        "report": report_path,
    }


def _render_report(pairing: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    raw = summary["conditions"]["raw"]
    capsule = summary["conditions"]["capsule"]
    lines = [
        "# Part 3 Minimal Raw/Capsule Pilot",
        "",
        "This is a small paired pilot on the frozen 25-problem FATE-M set.",
        "Raw and Capsule both use `MemorylessProcessor` and the same cached first-round Proposal.",
        "The comparison changes only the feedback delivered after a failed build:",
        "Raw passes Ax's original `BuildFailedFeedback`; Capsule passes deterministic `CapsuleFeedback`.",
        "",
        "## Scope",
        "",
        "- The shared first-round candidate is validated field by field (`code`, `reasoning`, `imports`, `opens`).",
        "- First-round candidate generation is excluded from Raw/Capsule repair cost.",
        "- Results are a single-model, single-batch pilot; they are not a significance test or a general capability claim.",
        "- Fixed model: `openai:gpt-5.6-sol`; endpoint: `https://yxai.chat/v1`; Responses API; `store=false`; reasoning `high`.",
        "- Fixed AxProverBase commit: `06dfadc9ab439755af5efcfe0add95bfef2733c7`; FATE-M/Lean environment is recorded by the runner contract.",
        "",
        "## Pairing",
        "",
        f"- Pairing gate: **{'PASS' if pairing.get('ok') else 'FAIL'}**",
        f"- Paired tasks: {pairing.get('pair_count', 0)} / {pairing.get('expected_count', 0)}",
        f"- First-round successes: {summary.get('first_round_success_count', 0)}",
        f"- First-round failures: {summary.get('first_round_failure_count', 0)}",
        "",
        "## Aggregate",
        "",
        "| Metric | Raw | Capsule | Capsule - Raw |",
        "|---|---:|---:|---:|",
    ]
    metric_labels = [
        ("successful_tasks", "Successful tasks"),
        ("second_round_repairs_after_first_failure", "Second-round repairs after first failure"),
        ("final_repairs_after_first_failure", "Final repairs after first failure"),
        ("total_rounds", "Total rounds"),
        ("compilation_errors", "Compilation errors"),
        ("proposer_calls", "Proposer calls"),
        ("reviewer_calls", "Reviewer calls"),
        ("llm_calls", "Total LLM calls"),
        ("total_tokens", "Total tokens"),
        ("repeated_diagnostics", "Repeated diagnostics"),
        ("api_errors", "API/infra errors"),
    ]
    differences = summary.get("capsule_minus_raw", {})
    for key, label in metric_labels:
        lines.append(f"| {label} | {raw.get(key, 0)} | {capsule.get(key, 0)} | {differences.get(key, 0)} |")
    lines.extend([
        "",
        "## Per-Task Differences",
        "",
        "| Task | First-round reference | Raw | Capsule | Raw rounds | Capsule rounds | Raw repair | Capsule repair |",
        "|---|---|---|---|---:|---:|---|---|",
    ])
    for row in pairing.get("pairs", []):
        if not isinstance(row, Mapping):
            continue
        first = "success" if row.get("first_round_success_reference") else "failure"
        lines.append(
            f"| `{row.get('task_id')}` | {first} | "
            f"{'pass' if row.get('raw_success') else 'fail'} | "
            f"{'pass' if row.get('capsule_success') else 'fail'} | "
            f"{row.get('raw_rounds', 0)} | {row.get('capsule_rounds', 0)} | "
            f"{'yes' if row.get('raw_final_repair') else 'no'} | "
            f"{'yes' if row.get('capsule_final_repair') else 'no'} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "The informative subset is the nine tasks whose shared first-round candidate failed to compile.",
        "Read the per-task table and `capsule_minus_raw` together: a positive repair difference means Capsule repaired more such tasks, while a negative round/token difference means less measured work.",
        "Any pairing error or infrastructure error makes the package unsuitable for a formal conclusion.",
        "",
    ])
    if pairing.get("warnings"):
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in pairing["warnings"])
        lines.append("")
    if pairing.get("errors"):
        lines.extend(["## Gate Errors", ""])
        lines.extend(f"- {error}" for error in pairing["errors"])
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "CSV_FIELDS",
    "build_summary",
    "read_jsonl",
    "validate_part3_runs",
    "write_part3_outputs",
]
