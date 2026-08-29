"""Validate the published B-arm handoff without calling model APIs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pairing import validate_experience_capsule_pair  # noqa: E402


EXPECTED = {
    "format": "tracer-b-arm-handoff-v1",
    "benchmark": "FATE-M",
    "paired_problems": 25,
    "condition": "capsule_experience",
    "feedback_mode": "capsule",
    "memory_mode": "experience_capsule_feedback",
    "memory_processor": "ExperienceProcessor",
    "integration_schema_version": "ax-capsule-feedback.readable.v0.3",
    "state_schema_version": "capsule-feedback.readable.v0.2",
    "ax_commit": "06dfadc9ab439755af5efcfe0add95bfef2733c7",
    "model": "openai:gpt-5.6-sol",
    "base_url": "https://yxai.chat/v1",
    "wire_api": "responses",
    "reasoning_effort": "high",
    "successes": 20,
    "rounds": 47,
    "llm_calls": 69,
    "memory_calls": 27,
    "proposer_calls": 22,
    "reviewer_calls": 20,
    "compilation_calls": 47,
    "compilation_errors": 27,
    "build_timeouts": 0,
    "api_errors": 0,
    "tokens": 659791,
    "telemetry_records": 77,
    "shared_events": 25,
    "summary_events": 25,
    "feedback_events": 27,
    "state_files": 9,
}

REQUIRED_TOP_LEVEL_FILES = {
    "capsule-experience.jsonl",
    "metrics.jsonl",
    "pairing.json",
    "part2-first-round-full.json",
    "REPORT.md",
}


def _fail(message: str) -> None:
    raise SystemExit(f"B handoff validation failed: {message}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"missing file: {path}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON in {path}: {exc}")
    raise AssertionError("unreachable")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        _fail(f"missing file: {path}")
    except UnicodeDecodeError as exc:
        _fail(f"invalid UTF-8 in {path}: {exc}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"invalid JSON at {path}:{line_no}: {exc}")
        if not isinstance(value, dict):
            _fail(f"{path}:{line_no} must contain a JSON object")
        rows.append(value)
    return rows


def _int(value: Any, label: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer")
    if nonnegative and value < 0:
        _fail(f"{label} must be non-negative")
    return value


def _sum(rows: list[dict[str, Any]], field: str) -> int:
    return sum(_int(row.get(field, 0) or 0, f"{field} in {row.get('task_id')}") for row in rows)


def _sum_nested(rows: list[dict[str, Any]], parent: str, field: str) -> int:
    total = 0
    for row in rows:
        value = row.get(parent)
        if not isinstance(value, dict):
            _fail(f"{row.get('task_id')}: {parent} is missing")
        total += _int(value.get(field, 0) or 0, f"{parent}.{field} in {row.get('task_id')}")
    return total


def _canonical_target(row: dict[str, Any]) -> str:
    module = str(row.get("module") or "").replace("\\", "/").strip()
    theorem = str(row.get("theorem") or "").strip()
    if module.endswith(".lean"):
        module = module[: -len(".lean")]
    module = module.replace("/", ".").strip(".")
    if not module or not theorem:
        _fail(f"{row.get('task_id')}: module/theorem is missing")
    return f"{module}:{theorem}"


def _safe_manifest_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        _fail("manifest file path must be a non-empty string")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        _fail(f"manifest path is not relative and safe: {value!r}")
    return path.as_posix()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_manifest(handoff: dict[str, Any], directory: Path) -> list[str]:
    for field, expected in (
        ("format", EXPECTED["format"]),
        ("benchmark", EXPECTED["benchmark"]),
        ("paired_problems", EXPECTED["paired_problems"]),
        ("condition", EXPECTED["condition"]),
        ("feedback_mode", EXPECTED["feedback_mode"]),
        ("memory_mode", EXPECTED["memory_mode"]),
        ("memory_processor", EXPECTED["memory_processor"]),
        ("pairing_ok", True),
        ("metadata_revision", "readable-manifest-v2"),
    ):
        if handoff.get(field) != expected:
            _fail(f"handoff.json {field}={handoff.get(field)!r}, expected {expected!r}")

    source_revision = handoff.get("source_revision")
    if not isinstance(source_revision, str) or len(source_revision) != 40 or any(
        char not in "0123456789abcdef" for char in source_revision.lower()
    ):
        _fail("handoff source_revision must be a 40-character commit id")

    entries = handoff.get("files")
    if not isinstance(entries, list):
        _fail("handoff files must be a list")
    listed: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            _fail("each handoff file entry must be an object")
        path = _safe_manifest_path(entry.get("path"))
        if path in listed:
            _fail(f"duplicate manifest path: {path}")
        listed.append(path)
        _int(entry.get("bytes"), f"manifest bytes for {path}")

    top_level = {path for path in listed if "/" not in path}
    state_paths = [path for path in listed if path.startswith("state/") and path.endswith(".json")]
    if top_level != REQUIRED_TOP_LEVEL_FILES:
        _fail(f"top-level manifest files mismatch: {sorted(top_level)}")
    if len(state_paths) != EXPECTED["state_files"]:
        _fail(f"expected {EXPECTED['state_files']} state files, found {len(state_paths)}")
    if len(listed) != len(REQUIRED_TOP_LEVEL_FILES) + EXPECTED["state_files"]:
        _fail("manifest contains an unexpected file type")

    for entry, relative in zip(entries, listed):
        path = directory / Path(*PurePosixPath(relative).parts)
        if not path.is_file():
            _fail(f"manifest-listed file missing: {path}")
        if path.stat().st_size != entry["bytes"]:
            _fail(f"byte count mismatch for {path}")

    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {"handoff.json", "README.md"}
    }
    if actual != set(listed):
        _fail(f"directory files and manifest differ: {sorted(actual ^ set(listed))}")

    reference = handoff.get("baseline_reference")
    if not isinstance(reference, str) or not reference:
        _fail("baseline_reference is missing")
    baseline_path = (directory / Path(*PurePosixPath(reference.replace("\\", "/")).parts)).resolve()
    if not _is_relative_to(baseline_path, ROOT / "results" / "handoff"):
        _fail("baseline_reference escapes the published handoff tree")
    if not baseline_path.is_file():
        _fail(f"baseline_reference is missing: {baseline_path}")
    return state_paths


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) != EXPECTED["paired_problems"]:
        _fail(f"result JSONL must contain {EXPECTED['paired_problems']} rows")
    task_ids = [str(row.get("task_id") or "") for row in rows]
    if any(not task_id for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
        _fail("result task_id values must be present and unique")

    for row in rows:
        task_id = row["task_id"]
        for field, expected in (
            ("condition", EXPECTED["condition"]),
            ("feedback_mode", EXPECTED["feedback_mode"]),
            ("memory_mode", EXPECTED["memory_mode"]),
            ("memory_processor", EXPECTED["memory_processor"]),
            ("integration_schema_version", EXPECTED["integration_schema_version"]),
            ("axproverbase_commit", EXPECTED["ax_commit"]),
            ("model", EXPECTED["model"]),
            ("base_url", EXPECTED["base_url"]),
            ("wire_api", EXPECTED["wire_api"]),
            ("reasoning_effort", EXPECTED["reasoning_effort"]),
        ):
            if row.get(field) != expected:
                _fail(f"{task_id}: {field}={row.get(field)!r}, expected {expected!r}")
        for field, expected in (("use_responses_api", True), ("store", False)):
            if row.get(field) is not expected:
                _fail(f"{task_id}: {field} must be {expected!r}")

        candidate = row.get("first_round_candidate")
        if not isinstance(candidate, str) or not candidate:
            _fail(f"{task_id}: first_round_candidate must be non-empty")
        if not isinstance(row.get("first_round_reasoning"), str):
            _fail(f"{task_id}: first_round_reasoning must be a string")
        for field in ("first_round_imports", "first_round_opens"):
            value = row.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                _fail(f"{task_id}: {field} must be a list of strings")

        for field in (
            "rounds",
            "compilation_error_count",
            "build_timeout_count",
            "call_count",
            "memory_llm_calls",
            "api_error_count",
            "diagnostic_event_count",
            "repeated_diagnostic_count",
        ):
            _int(row.get(field), f"{field} in {task_id}")
        if not isinstance(row.get("compile_ok"), bool):
            _fail(f"{task_id}: compile_ok must be boolean")
        if not isinstance(row.get("max_iterations_reached"), bool):
            _fail(f"{task_id}: max_iterations_reached must be boolean")

        calls = row.get("calls")
        if not isinstance(calls, dict):
            _fail(f"{task_id}: calls is missing")
        call_total = 0
        for field in ("proposer_calls", "reviewer_calls", "memory_calls", "other_llm_calls", "tool_calls"):
            value = _int(calls.get(field, 0) or 0, f"calls.{field} in {task_id}")
            if field != "tool_calls":
                call_total += value
        if call_total != row["call_count"]:
            _fail(f"{task_id}: call_count does not equal LLM call counters")
        if calls.get("memory_calls") != row["memory_llm_calls"]:
            _fail(f"{task_id}: memory_llm_calls does not equal calls.memory_calls")
        if _int(calls.get("capsule_llm_calls", 0) or 0, f"calls.capsule_llm_calls in {task_id}") != 0:
            _fail(f"{task_id}: CapsuleFeedback made an LLM call")
        if _int(calls.get("capsule_compiler_calls", 0) or 0, f"calls.capsule_compiler_calls in {task_id}") != 0:
            _fail(f"{task_id}: CapsuleFeedback made an extra compiler call")

        usage = row.get("usage")
        if not isinstance(usage, dict):
            _fail(f"{task_id}: usage is missing")
        _int(usage.get("total_tokens"), f"usage.total_tokens in {task_id}")

        feedback_events = row.get("feedback_events")
        if not isinstance(feedback_events, list):
            _fail(f"{task_id}: feedback_events must be a list")


def _validate_summary(rows: list[dict[str, Any]]) -> None:
    if sum(row["compile_ok"] is True for row in rows) != EXPECTED["successes"]:
        _fail("final success count mismatch")
    for field, key in (
        ("rounds", "rounds"),
        ("compilation_error_count", "compilation_errors"),
        ("build_timeout_count", "build_timeouts"),
        ("call_count", "llm_calls"),
        ("memory_llm_calls", "memory_calls"),
        ("api_error_count", "api_errors"),
        ("diagnostic_event_count", "feedback_events"),
    ):
        expected = EXPECTED[key]
        actual = _sum(rows, field)
        if actual != expected:
            _fail(f"sum of {field} is {actual}, expected {expected}")
    if _sum_nested(rows, "calls", "proposer_calls") != EXPECTED["proposer_calls"]:
        _fail("proposer call total mismatch")
    if _sum_nested(rows, "calls", "reviewer_calls") != EXPECTED["reviewer_calls"]:
        _fail("reviewer call total mismatch")
    if _sum_nested(rows, "calls", "memory_calls") != EXPECTED["memory_calls"]:
        _fail("memory call total mismatch")
    if _sum_nested(rows, "calls", "compiler_calls") != EXPECTED["compilation_calls"]:
        _fail("compiler call total mismatch")
    token_total = _sum_nested(rows, "usage", "total_tokens")
    if token_total != EXPECTED["tokens"]:
        _fail(f"token total is {token_total}, expected {EXPECTED['tokens']}")
    if sum(bool(row["max_iterations_reached"]) for row in rows) != 5:
        _fail("max-iteration count mismatch")
    if sum(len(row["feedback_events"]) for row in rows) != EXPECTED["feedback_events"]:
        _fail("feedback event list total mismatch")


def _validate_cache(cache: Any, rows: list[dict[str, Any]]) -> None:
    if not isinstance(cache, dict):
        _fail("first-round cache must be an object")
    expected_keys = {_canonical_target(row) for row in rows}
    if set(cache) != expected_keys:
        _fail("first-round cache keys do not match the 25 result targets")
    for row in rows:
        key = _canonical_target(row)
        cached = cache.get(key)
        if not isinstance(cached, dict):
            _fail(f"first-round cache entry is missing: {key}")
        row_fields = {
            "code": "first_round_candidate",
            "reasoning": "first_round_reasoning",
            "imports": "first_round_imports",
            "opens": "first_round_opens",
        }
        for cache_field, row_field in row_fields.items():
            if cached.get(cache_field) != row.get(row_field):
                _fail(f"first-round cache {cache_field} mismatch for {key}")


def _validate_metrics(metrics: list[dict[str, Any]]) -> None:
    if len(metrics) != EXPECTED["telemetry_records"]:
        _fail(f"metrics JSONL must contain {EXPECTED['telemetry_records']} records")
    counts = {"shared": 0, "summary": 0, "feedback": 0}
    summary_rows: list[dict[str, Any]] = []
    theorem_names: set[str] = set()
    event_ids: list[str] = []
    for row in metrics:
        if row.get("integration_schema_version") != EXPECTED["integration_schema_version"]:
            _fail("telemetry integration schema mismatch")
        if row.get("feedback_mode") != EXPECTED["feedback_mode"]:
            _fail("telemetry feedback_mode mismatch")
        event = row.get("event")
        if event != "run_summary":
            event_id = row.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                _fail("non-summary telemetry records need an event_id")
            event_ids.append(event_id)
        if event == "shared_first_round_candidate":
            counts["shared"] += 1
            if row.get("proposer_llm_calls") != 0:
                _fail("shared first-round event has a proposer call")
        elif event == "run_summary":
            counts["summary"] += 1
            summary_rows.append(row)
        elif event in (None, ""):
            counts["feedback"] += 1
            if row.get("input_feedback_type") != "build_failed":
                _fail("feedback telemetry has an unexpected input type")
            if not isinstance(row.get("feedback_text"), str) or not row["feedback_text"]:
                _fail("feedback telemetry is missing feedback_text")
            if row.get("memory_processor") != EXPECTED["memory_processor"]:
                _fail("feedback telemetry memory processor mismatch")
        else:
            _fail(f"unknown telemetry event type: {event!r}")

        theorem_name = row.get("theorem_name")
        if isinstance(theorem_name, str) and theorem_name:
            theorem_names.add(theorem_name)
        if event != "shared_first_round_candidate":
            for field, expected in (
                ("axproverbase_commit", EXPECTED["ax_commit"]),
                ("model", EXPECTED["model"]),
                ("base_url", EXPECTED["base_url"]),
                ("wire_api", EXPECTED["wire_api"]),
                ("reasoning_effort", EXPECTED["reasoning_effort"]),
            ):
                if row.get(field) != expected:
                    _fail(f"telemetry {field} mismatch")
            if row.get("memory_processor") != EXPECTED["memory_processor"]:
                _fail("telemetry memory processor mismatch")
            if row.get("use_responses_api") is not True or row.get("store") is not False:
                _fail("telemetry Responses/storage settings mismatch")

    if len(set(event_ids)) != len(event_ids):
        _fail("telemetry event_id values must be unique")
    if counts != {
        "shared": EXPECTED["shared_events"],
        "summary": EXPECTED["summary_events"],
        "feedback": EXPECTED["feedback_events"],
    }:
        _fail(f"telemetry event counts mismatch: {counts}")
    if len(theorem_names) != EXPECTED["paired_problems"]:
        _fail("telemetry theorem coverage is not 25 unique names")
    if _sum(summary_rows, "memory_llm_calls") != EXPECTED["memory_calls"]:
        _fail("run-summary memory call total mismatch")
    if _sum_nested(summary_rows, "usage", "total_tokens") != EXPECTED["tokens"]:
        _fail("run-summary token total mismatch")
    if any(row.get("capsule_llm_calls", 0) != 0 or row.get("capsule_compiler_calls", 0) != 0 for row in metrics):
        _fail("CapsuleFeedback telemetry reports an extra call")


def _validate_states(
    directory: Path,
    state_paths: list[str],
    rows: list[dict[str, Any]],
) -> None:
    expected: dict[str, int] = {
        _canonical_target(row): len(row["feedback_events"])
        for row in rows
        if row["feedback_events"]
    }
    if len(expected) != EXPECTED["state_files"]:
        _fail(f"expected {EXPECTED['state_files']} result sessions with feedback")
    observed: dict[str, int] = {}
    for relative in state_paths:
        payload = _read_json(directory / Path(*PurePosixPath(relative).parts))
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
            _fail(f"invalid state payload: {relative}")
        theorem_key = payload.get("theorem_key")
        state = payload["state"]
        if not isinstance(theorem_key, str) or theorem_key not in expected:
            _fail(f"unexpected state theorem key: {theorem_key!r}")
        if theorem_key in observed:
            _fail(f"duplicate state theorem key: {theorem_key}")
        if state.get("schema_version") != EXPECTED["state_schema_version"]:
            _fail(f"state schema mismatch for {theorem_key}")
        history = state.get("history")
        counts = state.get("feedback_counts")
        if not isinstance(history, list) or not isinstance(counts, dict):
            _fail(f"state history/counts missing for {theorem_key}")
        attempts = _int(state.get("attempt_count"), f"state attempt_count for {theorem_key}")
        if attempts != len(history) or attempts != expected[theorem_key]:
            _fail(f"state attempt count mismatch for {theorem_key}")
        if not history or not all(isinstance(item, dict) for item in history):
            _fail(f"state history has an invalid entry for {theorem_key}")
        if [item["round"] for item in history] != list(range(1, attempts + 1)):
            _fail(f"state history rounds are not consecutive for {theorem_key}")
        for item in history:
            if not isinstance(item, dict) or item.get("compile_ok") is not False:
                _fail(f"state history contains a non-failure for {theorem_key}")
        for value in counts.values():
            _int(value, f"state feedback count for {theorem_key}")
        observed[theorem_key] = attempts
    if observed != expected:
        _fail("state theorem coverage does not match result feedback events")


def _validate_report(path: Path) -> None:
    try:
        report = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError) as exc:
        _fail(f"cannot read report {path}: {exc}")
    required = (
        "B condition: `capsule_experience`",
        "Final successes | 20/25 (80.0%)",
        "Total rounds | 47",
        "LLM requests | 69",
        "Total tokens | 659,791",
        "API/infrastructure errors | 0",
        "python scripts/validate_b_handoff.py",
    )
    for text in required:
        if text not in report:
            _fail(f"REPORT.md is missing expected text: {text}")


def _validate_public_text(directory: Path) -> None:
    credential_patterns = (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}"),
    )
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            _fail(f"published file is not UTF-8: {path}: {exc}")
        if any(pattern.search(content) for pattern in credential_patterns):
            _fail(f"credential-like value found in published file: {path}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--handoff",
        type=Path,
        default=Path("results/handoff/part2-experience-capsule-20260829"),
        help="B handoff directory",
    )
    args = parser.parse_args()
    directory = args.handoff if args.handoff.is_absolute() else ROOT / args.handoff
    directory = directory.resolve()
    if not _is_relative_to(directory, ROOT / "results" / "handoff"):
        _fail("handoff directory must be inside results/handoff")

    handoff = _read_json(directory / "handoff.json")
    if not isinstance(handoff, dict):
        _fail("handoff.json must contain an object")
    state_paths = _validate_manifest(handoff, directory)
    rows = _read_jsonl(directory / "capsule-experience.jsonl")
    _validate_rows(rows)
    _validate_summary(rows)
    _validate_cache(_read_json(directory / "part2-first-round-full.json"), rows)
    _validate_metrics(_read_jsonl(directory / "metrics.jsonl"))
    _validate_states(directory, state_paths, rows)
    _validate_report(directory / "REPORT.md")
    _validate_public_text(directory)

    reference = handoff["baseline_reference"].replace("\\", "/")
    baseline_path = (directory / Path(*PurePosixPath(reference).parts)).resolve()
    baseline = _read_jsonl(baseline_path)
    pairing = _read_json(directory / "pairing.json")
    if not isinstance(pairing, dict) or pairing.get("ok") is not True:
        _fail("pairing.json must report ok=true")
    for field, expected in (
        ("pair_count", EXPECTED["paired_problems"]),
        ("expected_model", EXPECTED["model"]),
        ("expected_axproverbase_commit", EXPECTED["ax_commit"]),
        ("expected_base_url", EXPECTED["base_url"]),
        ("expected_wire_api", EXPECTED["wire_api"]),
        ("expected_store", False),
        ("expected_reasoning_effort", EXPECTED["reasoning_effort"]),
        ("expected_right_condition", EXPECTED["condition"]),
        ("expected_right_memory_mode", EXPECTED["memory_mode"]),
        ("expected_right_memory_processor", EXPECTED["memory_processor"]),
        ("require_zero_memory_calls", False),
    ):
        if pairing.get(field) != expected:
            _fail(f"pairing.json {field} mismatch")
    pairs = pairing.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != EXPECTED["paired_problems"]:
        _fail("pairing.json must contain 25 pairs")
    if not all(isinstance(pair, dict) for pair in pairs):
        _fail("pairing.json pairs must be objects")
    if not all(
        pair.get("first_round_candidate_equal") is True
        and pair.get("first_round_proposal_equal") is True
        for pair in pairs
    ):
        _fail("pairing.json contains a first-round mismatch")
    if {str(pair.get("task_id")) for pair in pairs} != {str(row.get("task_id")) for row in rows}:
        _fail("pairing.json task ids do not match the result rows")

    regenerated = validate_experience_capsule_pair(baseline, rows)
    if not regenerated.get("ok") or regenerated.get("pair_count") != EXPECTED["paired_problems"]:
        _fail("regenerated baseline/B pairing failed: " + "; ".join(regenerated.get("errors", [])))

    print(json.dumps({
        "ok": True,
        "handoff": str(directory),
        "condition": EXPECTED["condition"],
        "paired_problems": EXPECTED["paired_problems"],
        "successes": EXPECTED["successes"],
        "rounds": EXPECTED["rounds"],
        "llm_calls": EXPECTED["llm_calls"],
        "tokens": EXPECTED["tokens"],
        "telemetry_records": EXPECTED["telemetry_records"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
