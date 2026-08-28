"""Validate the public Part 3 handoff artifacts without calling model APIs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pairing import validate_paired_runs  # noqa: E402

EXPECTED = {
    "paired_problems": 25,
    "model": "openai:gpt-5.6-sol",
    "ax_commit": "06dfadc9ab439755af5efcfe0add95bfef2733c7",
    "base_url": "https://yxai.chat/v1",
    "wire_api": "responses",
    "reasoning_effort": "high",
    "baseline_success": 25,
    "capsule_success": 25,
    "baseline_rounds": 39,
    "capsule_rounds": 36,
    "baseline_compilation_errors": 14,
    "capsule_compilation_errors": 11,
    "baseline_call_count": 79,
    "capsule_call_count": 36,
    "baseline_tokens": 656657,
    "capsule_tokens": 274742,
}

REQUIRED_FILES = {
    "baseline-full.jsonl",
    "capsule-full.jsonl",
    "part2-first-round-full.json",
    "capsule-metrics-full.jsonl",
    "pairing-full.json",
}


def _fail(message: str) -> None:
    raise SystemExit(f"part3 handoff validation failed: {message}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        _fail(f"invalid JSON in {path}: {exc}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        _fail(f"missing file: {path}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            _fail(f"{path}:{line_no} must be a JSON object")
        rows.append(value)
    return rows


def _sum(rows: list[dict[str, Any]], field: str) -> int:
    return sum(int(row.get(field, 0) or 0) for row in rows)


def _success_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("compile_ok") is True)


def _token_count(rows: list[dict[str, Any]]) -> int:
    return sum(int((row.get("usage") or {}).get("total_tokens", 0) or 0) for row in rows)


def _call_count(rows: list[dict[str, Any]]) -> int:
    return sum(int(row.get("call_count", 0) or 0) for row in rows)


def _require_pairing_report(report: dict[str, Any]) -> None:
    checks = {
        "ok": True,
        "pair_count": EXPECTED["paired_problems"],
        "expected_model": EXPECTED["model"],
        "expected_axproverbase_commit": EXPECTED["ax_commit"],
        "expected_base_url": EXPECTED["base_url"],
        "expected_wire_api": EXPECTED["wire_api"],
        "expected_store": False,
        "expected_reasoning_effort": EXPECTED["reasoning_effort"],
    }
    for key, expected in checks.items():
        if report.get(key) != expected:
            _fail(f"pairing-full.json {key}={report.get(key)!r}, expected {expected!r}")


def _require_handoff_manifest(handoff: dict[str, Any], directory: Path) -> None:
    if handoff.get("format") != "tracer-part12-handoff-v1":
        _fail("unexpected handoff format")
    if handoff.get("benchmark") != "FATE-M":
        _fail("handoff benchmark must be FATE-M")
    if handoff.get("paired_problems") != EXPECTED["paired_problems"]:
        _fail("handoff paired_problems must be 25")
    if handoff.get("pairing_ok") is not True:
        _fail("handoff pairing_ok must be true")
    files = handoff.get("files") or []
    seen = {str(item.get("path")) for item in files if isinstance(item, dict)}
    if seen != REQUIRED_FILES:
        _fail(f"handoff files mismatch: {sorted(seen)}")
    for item in files:
        path = directory / str(item["path"])
        if not path.exists():
            _fail(f"handoff-listed file missing: {path}")
        if path.stat().st_size != int(item["bytes"]):
            _fail(f"byte count mismatch for {path}")


def _require_rows(baseline: list[dict[str, Any]], capsule: list[dict[str, Any]]) -> None:
    if len(baseline) != EXPECTED["paired_problems"]:
        _fail("baseline-full.jsonl must contain 25 rows")
    if len(capsule) != EXPECTED["paired_problems"]:
        _fail("capsule-full.jsonl must contain 25 rows")
    baseline_ids = {str(row.get("task_id")) for row in baseline}
    capsule_ids = {str(row.get("task_id")) for row in capsule}
    if len(baseline_ids) != EXPECTED["paired_problems"] or baseline_ids != capsule_ids:
        _fail("baseline and capsule task ids must be the same 25 unique ids")
    if _success_count(baseline) != EXPECTED["baseline_success"]:
        _fail("baseline success count mismatch")
    if _success_count(capsule) != EXPECTED["capsule_success"]:
        _fail("capsule success count mismatch")
    if _sum(baseline, "rounds") != EXPECTED["baseline_rounds"]:
        _fail("baseline total rounds mismatch")
    if _sum(capsule, "rounds") != EXPECTED["capsule_rounds"]:
        _fail("capsule total rounds mismatch")
    if _sum(baseline, "compilation_error_count") != EXPECTED["baseline_compilation_errors"]:
        _fail("baseline compilation error count mismatch")
    if _sum(capsule, "compilation_error_count") != EXPECTED["capsule_compilation_errors"]:
        _fail("capsule compilation error count mismatch")
    if _call_count(baseline) != EXPECTED["baseline_call_count"]:
        _fail("baseline LLM call count mismatch")
    if _call_count(capsule) != EXPECTED["capsule_call_count"]:
        _fail("capsule LLM call count mismatch")
    if _token_count(baseline) != EXPECTED["baseline_tokens"]:
        _fail("baseline token count mismatch")
    if _token_count(capsule) != EXPECTED["capsule_tokens"]:
        _fail("capsule token count mismatch")
    for row in capsule:
        calls = row.get("calls") or {}
        if int(calls.get("memory_calls", 0) or 0) != 0:
            _fail(f"capsule row {row.get('task_id')} has nonzero memory_calls")
        if int(calls.get("capsule_llm_calls", 0) or 0) != 0:
            _fail(f"capsule row {row.get('task_id')} has nonzero capsule_llm_calls")
        if int(calls.get("capsule_compiler_calls", 0) or 0) != 0:
            _fail(f"capsule row {row.get('task_id')} has nonzero capsule_compiler_calls")


def _canonical_target(row: dict[str, Any]) -> str:
    theorem = str(row.get("theorem") or "").strip()
    target = str(row.get("target") or "").strip()
    suffix = f":{theorem}"
    if theorem and target.endswith(suffix):
        module = target[: -len(suffix)]
    else:
        module = str(row.get("module") or "").strip()
    module = module.replace("\\", "/")
    while module.startswith("./"):
        module = module[2:]
    if module.endswith(".lean"):
        module = module[: -len(".lean")]
    module = module.replace("/", ".").strip(".")
    if not module or not theorem:
        _fail("baseline rows require module/theorem to validate first-round cache")
    return f"{module}:{theorem}"


def _require_cache(cache: dict[str, Any], baseline: list[dict[str, Any]]) -> None:
    keys = {str(row.get("target")) for row in baseline} | {_canonical_target(row) for row in baseline}
    missing = sorted(_canonical_target(row) for row in baseline if _canonical_target(row) not in cache and str(row.get("target")) not in cache)
    if missing:
        _fail(f"first-round cache missing targets: {missing[:3]}")
    for row in baseline:
        raw_target = str(row["target"])
        cache_key = raw_target if raw_target in cache else _canonical_target(row)
        cached = cache[cache_key]
        if cached.get("code") != row.get("first_round_candidate"):
            _fail(f"first-round cache code mismatch for {raw_target}")
        if cached.get("reasoning", "") != row.get("first_round_reasoning", ""):
            _fail(f"first-round cache reasoning mismatch for {raw_target}")
        if cached.get("imports", []) != row.get("first_round_imports", []):
            _fail(f"first-round cache imports mismatch for {raw_target}")
        if cached.get("opens", []) != row.get("first_round_opens", []):
            _fail(f"first-round cache opens mismatch for {raw_target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--handoff",
        type=Path,
        default=Path("results/handoff/part12-live-20260828-corrected"),
        help="Directory containing baseline/capsule JSONL files and pairing-full.json.",
    )
    args = parser.parse_args(argv)
    directory = args.handoff

    handoff = _read_json(directory / "handoff.json")
    pairing = _read_json(directory / "pairing-full.json")
    baseline = _read_jsonl(directory / "baseline-full.jsonl")
    capsule = _read_jsonl(directory / "capsule-full.jsonl")
    cache = _read_json(directory / "part2-first-round-full.json")

    _require_handoff_manifest(handoff, directory)
    _require_pairing_report(pairing)
    _require_rows(baseline, capsule)
    _require_cache(cache, baseline)

    regenerated = validate_paired_runs(baseline, capsule)
    if not regenerated.get("ok"):
        _fail("regenerated pairing validation failed: " + "; ".join(regenerated.get("errors", [])))
    if regenerated.get("pair_count") != EXPECTED["paired_problems"]:
        _fail("regenerated pairing pair_count mismatch")

    print(json.dumps({
        "ok": True,
        "handoff": str(directory),
        "paired_problems": EXPECTED["paired_problems"],
        "baseline_success": EXPECTED["baseline_success"],
        "capsule_success": EXPECTED["capsule_success"],
        "baseline_rounds": EXPECTED["baseline_rounds"],
        "capsule_rounds": EXPECTED["capsule_rounds"],
        "baseline_call_count": EXPECTED["baseline_call_count"],
        "capsule_call_count": EXPECTED["capsule_call_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
