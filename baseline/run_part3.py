"""Run the Part 3 Raw and Capsule conditions in per-task interleaved order."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from run_part2 import (  # noqa: E402
    _read_jsonl,
    prepare_run_artifacts,
    run_target,
    validate_inputs,
)


FATE_M_COMMIT = "4eb33c8ccd0ff058b461cd763cc406509129743f"
_ERROR_SECRET_RE = re.compile(r"(?i)(?:bearer\s+|(?:api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*)\S+")
_ERROR_PATH_RE = re.compile(r"(?i)[A-Z]:[\\/][^\r\n]+")


def _git_head(folder: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=folder,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"cannot read FATE-M git revision: {completed.stderr.strip()[:160]}")
    return completed.stdout.strip()


def _safe_relative_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe benchmark path: {value}")
    normalized = value.replace("\\", "/").lstrip("./")
    if not normalized or not normalized.endswith(".lean"):
        raise ValueError(f"invalid benchmark Lean path: {value}")
    return normalized


class SourceGuard:
    """Temporarily use clean benchmark files, then restore the prior files."""

    def __init__(self, folder: Path, modules: list[str]) -> None:
        self.folder = folder
        self.modules = sorted(set(_safe_relative_path(module) for module in modules))
        self.current: dict[str, bytes] = {}
        self.pristine: dict[str, bytes] = {}
        for module in self.modules:
            path = self.folder / module
            if not path.is_file():
                raise ValueError(f"benchmark file is missing: {module}")
            self.current[module] = path.read_bytes()
            completed = subprocess.run(
                ["git", "show", f"HEAD:{module}"],
                cwd=self.folder,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                raise ValueError(f"cannot read pristine benchmark file: {module}")
            self.pristine[module] = completed.stdout

    def restore_pristine(self) -> None:
        for module, content in self.pristine.items():
            path = self.folder / module
            if path.read_bytes() != content:
                path.write_bytes(content)

    def restore_current(self) -> None:
        for module, content in self.current.items():
            path = self.folder / module
            if path.read_bytes() != content:
                path.write_bytes(content)


def _safe_error(exc: BaseException) -> str:
    message = str(exc or "").strip()
    message = _ERROR_SECRET_RE.sub("<redacted>", message)
    message = _ERROR_PATH_RE.sub("<path>", message)
    return " ".join(message.split())[:500]


def _read_existing_ids(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    rows = _read_jsonl(path)
    ids: set[str] = set()
    for row in rows:
        task_id = str(row.get("task_id") or "")
        if not task_id or task_id in ids:
            raise ValueError(f"existing output contains invalid or duplicate task_id: {task_id!r}")
        ids.add(task_id)
    return ids


def _prepare_paths(out_dir: Path, overwrite: bool) -> dict[str, Path]:
    paths = {
        "raw": out_dir / "raw.jsonl",
        "capsule": out_dir / "capsule.jsonl",
        "raw_metrics": out_dir / "raw-metrics.jsonl",
        "capsule_metrics": out_dir / "capsule-metrics.jsonl",
        "capsule_state": out_dir / "capsule-state",
        "errors": out_dir / "errors.jsonl",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    prepare_run_artifacts(
        paths["raw"],
        state_dir=None,
        metrics_path=paths["raw_metrics"],
        overwrite=overwrite,
    )
    prepare_run_artifacts(
        paths["capsule"],
        state_dir=paths["capsule_state"],
        metrics_path=paths["capsule_metrics"],
        overwrite=overwrite,
    )
    if paths["errors"].exists() and paths["errors"].stat().st_size and not overwrite:
        raise ValueError(f"existing error log would contaminate a fresh run: {paths['errors']}")
    if overwrite:
        paths["errors"].write_text("", encoding="utf-8")
    else:
        paths["errors"].touch()
    return paths


def _append_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--raw-config", type=Path, default=ROOT / "configs" / "axprover_raw_memoryless.yaml")
    parser.add_argument("--capsule-config", type=Path, default=ROOT / "configs" / "axprover_part2_capsule.yaml")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    baseline_path = args.baseline.resolve()
    cache_path = args.cache.resolve()
    folder = args.folder.resolve()
    raw_config = args.raw_config.resolve()
    capsule_config = args.capsule_config.resolve()
    out_dir = args.out_dir.resolve()
    try:
        rows = validate_inputs(_read_jsonl(baseline_path), cache_path)
        if args.limit is not None:
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            rows = rows[: args.limit]
        if not rows:
            raise ValueError("baseline selection is empty")
        if _git_head(folder) != FATE_M_COMMIT:
            raise ValueError(f"FATE-M commit must be {FATE_M_COMMIT}")
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is not set")
        paths = _prepare_paths(out_dir, args.overwrite)
        guard = SourceGuard(folder, [str(row["module"]) for row in rows])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Part 3 preflight failed: {_safe_error(exc)}", file=sys.stderr)
        return 2

    # Formal runs are deliberately fresh. The helper above validates known
    # artifacts and leaves unrelated files in the output directory untouched.
    completed = {
        "raw": _read_existing_ids(paths["raw"]),
        "capsule": _read_existing_ids(paths["capsule"]),
    }
    errors = 0
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        guard.restore_pristine()
        for index, row in enumerate(rows, 1):
            task_id = str(row["task_id"])
            target = str(row["target"])
            metadata = {
                "id": task_id,
                "module": row.get("module", ""),
                "theorem": row.get("theorem", ""),
            }
            order = ("raw", "capsule") if index % 2 else ("capsule", "raw")
            for mode in order:
                if task_id in completed[mode]:
                    print(f"[{index}/{len(rows)}] {task_id} {mode}: already present")
                    continue
                guard.restore_pristine()
                output_path = paths[mode]
                metrics_path = paths[f"{mode}_metrics"]
                state_dir = paths["capsule_state"] if mode == "capsule" else None
                config = raw_config if mode == "raw" else capsule_config
                try:
                    records = asyncio.run(
                        run_target(
                            target,
                            str(folder),
                            str(config),
                            feedback_mode=mode,
                            telemetry_path=metrics_path,
                            state_dir=state_dir,
                            first_round_cache_path=cache_path,
                            task_metadata=metadata,
                        )
                    )
                    if len(records) != 1:
                        raise ValueError(f"expected one result record, got {len(records)}")
                    record = records[0]
                    _append_json(output_path, record)
                    completed[mode].add(task_id)
                    print(
                        f"[{index}/{len(rows)}] {task_id} {mode}: "
                        f"proven={record['compile_ok']} rounds={record['rounds']} "
                        f"calls={record['call_count']} tokens={record['usage']['total_tokens']}"
                    )
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    error_row = {
                        "task_id": task_id,
                        "target": target,
                        "condition": mode,
                        "error_type": type(exc).__name__,
                        "message": _safe_error(exc),
                    }
                    _append_json(paths["errors"], error_row)
                    print(
                        f"[{index}/{len(rows)}] {task_id} {mode}: ERROR {error_row['error_type']}",
                        file=sys.stderr,
                    )
                finally:
                    guard.restore_pristine()
    finally:
        try:
            guard.restore_current()
        except OSError as exc:
            errors += 1
            _append_json(
                paths["errors"],
                {
                    "task_id": "<source-restore>",
                    "condition": "runner",
                    "error_type": type(exc).__name__,
                    "message": _safe_error(exc),
                },
            )

    print(
        f"Part 3 interleaved run finished: started={started} "
        f"raw={len(completed['raw'])}/{len(rows)} capsule={len(completed['capsule'])}/{len(rows)} "
        f"errors={errors}"
    )
    return 0 if not errors and len(completed["raw"]) == len(rows) and len(completed["capsule"]) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
