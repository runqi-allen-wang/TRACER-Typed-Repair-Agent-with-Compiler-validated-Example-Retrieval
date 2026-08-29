"""导出通过严格门禁的 TRACER 试验包，并清理本机路径与认证信息。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from validate_pilot import DEFAULT_MANIFEST, DEFAULT_REVIEW, DEFAULT_RUNS, EXPECTED_CANDIDATE_POLICY, expected_pairs, load_runs, validate_review, validate_runs
except ModuleNotFoundError:
    from scripts.validate_pilot import DEFAULT_MANIFEST, DEFAULT_REVIEW, DEFAULT_RUNS, EXPECTED_CANDIDATE_POLICY, expected_pairs, load_runs, validate_review, validate_runs


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
REPORT_FILES = ("pilot_summary.csv", "pilot_failure_types.csv", "pilot_topic_summary.csv", "pilot_report.json", "pass_at_1.svg", "pass_at_3.svg")
COPY_FILES = REPORT_FILES
SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|yi)-[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
)
SECRET_FIELD = re.compile(r"(?:api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token)", re.IGNORECASE)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def replacements() -> list[tuple[str, str]]:
    values = [(str(ROOT.resolve()), "<repo>"), (str(Path.home().resolve()), "<home>"), (str(Path(tempfile.gettempdir()).resolve()), "<temp>")]
    expanded = [(source, target) for source, target in values]
    expanded += [(source.replace("\\", "/"), target) for source, target in values]
    return sorted(set(expanded), key=lambda item: len(item[0]), reverse=True)


def sanitize(value: Any, substitutions: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: sanitize(item, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, substitutions) for item in value]
    if isinstance(value, str):
        for source, target in substitutions:
            value = value.replace(source, target)
    return value


def reject_secrets(value: Any, location: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_FIELD.search(str(key)) and isinstance(item, str) and len(item.strip()) >= 12:
                raise ValueError(f"导出内容疑似包含认证信息: {location}.{key}")
            reject_secrets(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, f"{location}[{index}]")
    elif isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"导出内容疑似包含认证信息: {location}")


def git_revision() -> str:
    if not (ROOT / ".git").exists():
        return "unavailable (source export without repository metadata)"
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def validate_artifacts(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    required = [ROOT / "REPORT.md", RESULTS / "pilot_report.json", *(RESULTS / item for item in REPORT_FILES if item != "pilot_report.json")]
    errors.extend(f"缺少发布文件: {path}" for path in required if not path.is_file())
    report_path = RESULTS / "pilot_report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"pilot_report.json 无法读取: {exc}")
        else:
            if report.get("status") != "formal":
                errors.append("pilot_report.json 不是 formal 状态")
            if report.get("candidate_policy") != EXPECTED_CANDIDATE_POLICY:
                errors.append("pilot_report.json 未记录当前候选安全策略")
    for row in rows:
        if not row.get("compile_ok"):
            continue
        source_stem = Path(str(row.get("source_file", ""))).stem
        theorem = str(row.get("theorem", ""))
        pair = (str(row.get("condition", "")), str(row.get("problem_id", "")))
        proof = RESULTS / "solutions" / pair[0] / f"{safe_name(source_stem)}__{safe_name(theorem)}.lean"
        if not proof.is_file():
            errors.append(f"缺少成功证明文件: {pair}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--allow-cache-hits", action="store_true")
    args = parser.parse_args()
    rows = load_runs(args.runs)
    expected = expected_pairs(args.manifest)
    errors = validate_runs(rows, expected, args.allow_cache_hits)
    errors.extend(validate_review(args.review, expected, rows))
    errors.extend(validate_artifacts(rows))
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
        return 1
    out = args.out.resolve()
    if out.exists():
        raise SystemExit(f"输出目录已存在: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    substitutions = replacements()
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        cleaned_rows = sanitize(rows, substitutions)
        reject_secrets(cleaned_rows)
        with (staging / "real_pilot_runs.sanitized.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in cleaned_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        shutil.copy2(args.manifest, staging / "benchmark_manifest.json")
        shutil.copy2(args.review, staging / "manual_review.csv")
        shutil.copy2(ROOT / "REPORT.md", staging / "REPORT.md")
        for name in REPORT_FILES:
            shutil.copy2(RESULTS / name, staging / name)
        if (RESULTS / "solutions").exists():
            shutil.copytree(RESULTS / "solutions", staging / "solutions")
        for path in staging.rglob("*"):
            if not path.is_file() or path.name == "handoff.json":
                continue
            text = path.read_text(encoding="utf-8-sig")
            for source, target in substitutions:
                text = text.replace(source, target)
            reject_secrets(text, path.as_posix())
            path.write_text(text, encoding="utf-8", newline="\n")
        files = sorted(path for path in staging.rglob("*") if path.is_file())
        handoff = {"format": "tracer-pilot-handoff-v1", "git_revision": git_revision(), "task_condition_pairs": len(expected), "records": len(rows), "files": [{"path": path.relative_to(staging).as_posix(), "size_bytes": path.stat().st_size} for path in files]}
        (staging / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.replace(out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps({"ok": True, "out": str(out), "files": len(files) + 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
