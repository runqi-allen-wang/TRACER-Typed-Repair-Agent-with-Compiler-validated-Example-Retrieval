"""Validate a baseline/Capsule paired-run result, including the B arm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pairing import validate_paired_runs  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no} must be a JSON object")
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument(
        "--capsule-condition",
        choices=["capsule", "capsule_experience"],
        default="capsule",
        help="Right-hand condition; capsule_experience selects the B arm",
    )
    parser.add_argument(
        "--capsule-memory-class",
        choices=["MemorylessProcessor", "ExperienceProcessor"],
        help="Override the expected right-hand memory processor",
    )
    parser.add_argument(
        "--capsule-memory-mode",
        help="Override the expected right-hand memory mode",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.capsule_condition == "capsule_experience":
        memory_class = args.capsule_memory_class or "ExperienceProcessor"
        memory_mode = args.capsule_memory_mode or "experience_capsule_feedback"
        report = validate_paired_runs(
            _read_jsonl(args.baseline),
            _read_jsonl(args.capsule),
            right_condition=args.capsule_condition,
            right_feedback_mode="capsule",
            right_memory_mode=memory_mode,
            right_memory_processor=memory_class,
            require_zero_memory_calls=False,
        )
    else:
        report = validate_paired_runs(
            _read_jsonl(args.baseline),
            _read_jsonl(args.capsule),
            right_condition=args.capsule_condition,
            right_memory_mode=args.capsule_memory_mode or "capsule_feedback",
            right_memory_processor=args.capsule_memory_class or "MemorylessProcessor",
        )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
