"""Validate, compare, and package the Part 3 Raw/Capsule pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from leancapsule.ax_integration import FirstRoundCandidateCache  # noqa: E402
from leancapsule.part3 import (  # noqa: E402
    read_jsonl,
    validate_part3_runs,
    write_part3_outputs,
)


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:OPENAI_API_KEY|API_KEY|ACCESS_TOKEN|AUTHORIZATION)\b\s*[:=]"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:sk|key)-[A-Za-z0-9._-]{12,}\b"),
    # Require a non-word boundary so the ``s://`` suffix of an HTTPS URL is
    # not mistaken for a Windows drive path.
    re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\r\n\"]+"),
)


def _cache_errors(baseline: list[dict[str, Any]], cache_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        cache = FirstRoundCandidateCache(cache_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"shared first-round cache cannot be read: {type(exc).__name__}"]
    fields = (
        "first_round_candidate",
        "first_round_reasoning",
        "first_round_imports",
        "first_round_opens",
    )
    for row in baseline:
        task_id = str(row.get("task_id") or "unknown")
        target = str(row.get("target") or "")
        try:
            cached = cache.get(target)
        except (KeyError, ValueError) as exc:
            errors.append(f"{task_id}: shared first-round cache lookup failed")
            continue
        for field in fields:
            cache_field = {
                "first_round_candidate": "code",
                "first_round_reasoning": "reasoning",
                "first_round_imports": "imports",
                "first_round_opens": "opens",
            }[field]
            if row.get(field) != cached.get(cache_field):
                errors.append(f"{task_id}: shared cache mismatch for {field}")
    return errors


def _export_errors(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"cannot scan export file: {path.name}")
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{path.name}: sensitive-looking content found")
                break
    return errors


def _git_revision() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _write_handoff(out_dir: Path, pairing: dict[str, Any]) -> Path:
    included = [
        "raw.jsonl",
        "capsule.jsonl",
        "pairing.json",
        "per-task.csv",
        "summary.json",
        "REPORT.md",
    ]
    files = []
    for name in included:
        path = out_dir / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": name, "bytes": path.stat().st_size, "sha256": digest})
    handoff = {
        "format": "tracer-part3-handoff-v1",
        "benchmark": "FATE-M",
        "paired_problems": int(pairing.get("pair_count", 0)),
        "pairing_ok": bool(pairing.get("ok")),
        "source_revision": _git_revision(),
        "files": files,
    }
    path = out_dir / "handoff.json"
    path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--errors", type=Path)
    parser.add_argument("--expected-count", type=int, default=25)
    args = parser.parse_args(argv)

    try:
        raw_rows = read_jsonl(args.raw)
        capsule_rows = read_jsonl(args.capsule)
        baseline_rows = read_jsonl(args.baseline)
        error_rows = read_jsonl(args.errors) if args.errors and args.errors.exists() else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Part 3 input error: {exc}", file=sys.stderr)
        return 2

    cache_errors = _cache_errors(baseline_rows, args.cache)
    pairing = validate_part3_runs(
        raw_rows,
        capsule_rows,
        baseline_rows=baseline_rows,
        expected_count=args.expected_count,
        error_rows=error_rows,
    )
    pairing["shared_first_round_cache_verified"] = not cache_errors
    pairing["errors"] = list(pairing.get("errors", [])) + cache_errors
    pairing["ok"] = not pairing["errors"] and pairing.get("pair_count") == args.expected_count

    output = args.out_dir
    output.mkdir(parents=True, exist_ok=True)
    for source, name in ((args.raw, "raw.jsonl"), (args.capsule, "capsule.jsonl")):
        destination = output / name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
    exported = write_part3_outputs(pairing, output)
    export_errors = _export_errors(
        [
            output / "raw.jsonl",
            output / "capsule.jsonl",
            exported["pairing"],
            exported["summary"],
            exported["per_task"],
            exported["report"],
        ]
    )
    if export_errors:
        pairing["errors"] = list(pairing.get("errors", [])) + export_errors
        pairing["ok"] = False
        write_part3_outputs(pairing, output)
    handoff = _write_handoff(output, pairing)
    print(json.dumps({
        "ok": pairing["ok"],
        "pair_count": pairing.get("pair_count", 0),
        "out_dir": str(output),
        "handoff": handoff.name,
    }, ensure_ascii=False))
    if pairing.get("errors"):
        for error in pairing["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if pairing["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
