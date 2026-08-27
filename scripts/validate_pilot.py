"""Validate completeness and release gates for a TRACER provider pilot."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "results" / "real_pilot_runs.jsonl"
DEFAULT_MANIFEST = ROOT / "benchmarks" / "manifest.json"
DEFAULT_REVIEW = ROOT / "results" / "manual_review.csv"
CONDITIONS = ("A", "B", "C")
REVIEW_FIELDS = ("kernel_pass", "inappropriate_assumption", "leakage_risk", "reviewer_note")
EXPECTED_CANDIDATE_POLICY = {
    "version": "tracer-candidate-v2",
    "meta_execution": "blocked",
    "unsafe_declarations": "blocked",
    "environment": "minimal",
}


def load_runs(path: Path) -> list[dict]:
    if not path.exists():
        raise ValueError(f"missing run log: {path}")
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"run log line {line_no} must be a JSON object")
        rows.append(row)
    return rows


def expected_pairs(manifest_path: Path) -> set[tuple[str, str]]:
    tasks = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {(condition, task["id"]) for condition in CONDITIONS for task in tasks}


def validate_runs(rows: list[dict], expected: set[tuple[str, str]], allow_cache_hits: bool) -> list[str]:
    errors: list[str] = []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("condition", "")), str(row.get("problem_id", "")))].append(row)

    actual = set(groups)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        errors.append(f"missing task-condition pairs: {missing}")
    if unexpected:
        errors.append(f"unexpected task-condition pairs: {unexpected}")

    task_errors = [
        pair
        for pair, attempts in groups.items()
        if any(
            attempt.get("diagnostic", {}).get("category") in {"task_error", "compiler_unavailable"}
            for attempt in attempts
        )
    ]
    if task_errors:
        errors.append(f"task or compiler infrastructure errors: {sorted(task_errors)}")

    provider_errors = [
        pair for pair, attempts in groups.items() if any(attempt.get("provider_error") for attempt in attempts)
    ]
    if provider_errors:
        errors.append(f"provider infrastructure errors: {sorted(provider_errors)}")

    for pair, attempts in sorted(groups.items()):
        run_ids = {str(attempt.get("run_id") or "").strip() for attempt in attempts}
        if "" in run_ids or len(run_ids) != 1:
            errors.append(f"task-condition pair mixes run_id values for {pair}: {sorted(run_ids)}")
        rounds = [attempt.get("round") for attempt in attempts]
        if any(not isinstance(round_no, int) or not 1 <= round_no <= 3 for round_no in rounds):
            errors.append(f"invalid repair round for {pair}: {rounds}")
        elif rounds != list(range(1, len(rounds) + 1)):
            errors.append(f"non-contiguous repair rounds for {pair}: {rounds}")
        successful_rounds = [index for index, attempt in enumerate(attempts) if attempt.get("compile_ok")]
        if successful_rounds and successful_rounds[0] != len(attempts) - 1:
            errors.append(f"attempts continue after success for {pair}")

    cache_hits = sum(bool(row.get("cache_hit")) for row in rows)
    if cache_hits and not allow_cache_hits:
        errors.append(f"strict fresh pilot contains {cache_hits} cache hit(s)")

    configurations = {
        json.dumps(row.get("provider_config", {}), ensure_ascii=True, sort_keys=True) for row in rows
    }
    if len(configurations) != 1:
        errors.append(f"provider configuration changed across attempts: {len(configurations)} variants")
    elif configurations == {"{}"}:
        errors.append("provider configuration is missing")
    if any(
        not isinstance(row.get("provider_config"), dict)
        or not str(row["provider_config"].get("provider", "")).strip()
        for row in rows
    ):
        errors.append("provider configuration must contain a provider name")
    policies = {
        json.dumps(row.get("candidate_policy", {}), ensure_ascii=True, sort_keys=True)
        for row in rows
    }
    expected_policy = json.dumps(EXPECTED_CANDIDATE_POLICY, ensure_ascii=True, sort_keys=True)
    if policies != {expected_policy}:
        errors.append("run log does not consistently use the current candidate security policy")
    experiment_ids = {str(row.get("experiment_id") or "") for row in rows}
    if "" in experiment_ids:
        errors.append("one or more attempts are missing experiment_id")
    elif len(experiment_ids) != 1:
        errors.append(f"multiple experiment_id values: {sorted(experiment_ids)}")
    return errors


def validate_review(path: Path, expected: set[tuple[str, str]], rows: list[dict]) -> list[str]:
    if not path.exists():
        return [f"missing manual review ledger: {path}"]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    errors: list[str] = []
    by_pair = {(row.get("condition", ""), row.get("problem_id", "")): row for row in review_rows}
    if len(by_pair) != len(review_rows):
        errors.append("manual review ledger contains duplicate task-condition rows")
    if set(by_pair) != expected:
        errors.append("manual review ledger does not cover the frozen 54 task-condition pairs")

    run_experiment_ids = {str(row.get("experiment_id") or "") for row in rows}
    review_experiment_ids = {str(row.get("experiment_id") or "") for row in review_rows}
    if len(run_experiment_ids) != 1 or review_experiment_ids != run_experiment_ids:
        errors.append("manual review experiment_id does not match the run log")

    successful = {
        (str(row.get("condition", "")), str(row.get("problem_id", "")))
        for row in rows
        if bool(row.get("compile_ok"))
    }
    for pair in sorted(successful):
        review = by_pair.get(pair, {})
        missing_fields = [field for field in REVIEW_FIELDS if not str(review.get(field, "")).strip()]
        if missing_fields:
            errors.append(f"manual review incomplete for {pair}: {missing_fields}")
            continue
        for field in REVIEW_FIELDS[:3]:
            if str(review[field]).strip().lower() not in {"yes", "no"}:
                errors.append(f"manual review field {field} for {pair} must be yes or no")
        if str(review["kernel_pass"]).strip().lower() == "no":
            errors.append(f"kernel review failed for {pair}")
        if str(review["inappropriate_assumption"]).strip().lower() == "yes":
            errors.append(f"inappropriate assumption reported for {pair}")
        if str(review["leakage_risk"]).strip().lower() == "yes":
            errors.append(f"leakage risk reported for {pair}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--allow-cache-hits", action="store_true")
    parser.add_argument("--require-manual-review", action="store_true")
    args = parser.parse_args()

    try:
        rows = load_runs(args.runs)
        expected = expected_pairs(args.manifest)
        errors = validate_runs(rows, expected, args.allow_cache_hits)
        if args.require_manual_review:
            errors.extend(validate_review(args.review, expected, rows))
    except (OSError, ValueError, KeyError) as exc:
        errors = [str(exc)]
        rows = []
        expected = set()

    result = {
        "ok": not errors,
        "records": len(rows),
        "tasks": len(expected),
        "manual_review_required": args.require_manual_review,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
