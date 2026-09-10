"""审计公开的 Feedback Study v1 发布包。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compiler import diagnostics_use_sorry, run_lean_file  # noqa: E402


FORMAT = "tracer-feedback-study-release-v1"
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".lean", ".md", ".txt"}
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
PRIVATE_POSIX_PATH = re.compile(r"/(?:home|Users|tmp|private|var/tmp)/")
SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|secret|password)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{12,}|bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:sk|yi)-[A-Za-z0-9._~+/=-]{12,}"
)
SENSITIVE_KEYS = {
    "api_key", "api_key_env", "authorization", "access_token", "refresh_token", "secret", "password",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} 第 {line_number} 行不是对象")
        rows.append(value)
    return rows


def _walk_keys(value: Any, location: str = "root") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered == "prompt" or lowered == "prompt_templates":
                errors.append(f"{location}.{key}: 公开记录不得包含逐请求 prompt 或内嵌模板")
            if lowered in SENSITIVE_KEYS:
                errors.append(f"{location}.{key}: 公开记录不得包含认证字段")
            if lowered == "id" and location.endswith("provider_response"):
                errors.append(f"{location}.{key}: 公开记录不得包含供应商响应 ID")
            errors.extend(_walk_keys(item, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_walk_keys(item, f"{location}[{index}]"))
    return errors


def _task_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("model_id", "")),
        str(row.get("repeat", "")),
        str(row.get("representation", "")),
        str(row.get("problem_id", "")),
    )


def audit_release(root: Path, compile_solutions: bool = False, timeout: int = 180) -> dict:
    root = root.resolve()
    errors: list[str] = []
    required = {
        "README.md", "FILES.md", "MANIFEST.json", "summary.json", "plan.sanitized.json",
        "benchmark.json", "completion.sanitized.json", "initial_compilation.sanitized.json",
        "trials.jsonl", "attempts.sanitized.jsonl", "ai_assisted_review.csv",
        "protocol/feedback_study.protocol.json", "protocol/feedback.txt", "protocol/proof_contract.txt",
    }
    for name in sorted(required):
        if not (root / name).is_file():
            errors.append(f"缺少发布文件: {name}")
    if errors:
        return {"ok": False, "errors": errors}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        relative = path.relative_to(root).as_posix()
        if WINDOWS_PATH.search(text) or PRIVATE_POSIX_PATH.search(text):
            errors.append(f"{relative}: 包含绝对本机路径")
        if SECRET_VALUE.search(text):
            errors.append(f"{relative}: 疑似包含认证值")
    if any(part.lower() == "retry_history" for path in root.rglob("*") for part in path.parts):
        errors.append("公开包不得包含 retry_history 原始目录")

    try:
        manifest = _read_json(root / "MANIFEST.json")
        plan = _read_json(root / "plan.sanitized.json")
        benchmark = _read_json(root / "benchmark.json")
        summary = _read_json(root / "summary.json")
        completion = _read_json(root / "completion.sanitized.json")
        trials = _read_jsonl(root / "trials.jsonl")
        attempts = _read_jsonl(root / "attempts.sanitized.jsonl")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": errors + [f"结构化文件无法读取: {exc}"]}

    if manifest.get("format") != FORMAT:
        errors.append("MANIFEST.json 发布格式不匹配")
    listed = manifest.get("files", [])
    listed_map = {str(item.get("path")): item.get("size_bytes") for item in listed if isinstance(item, dict)}
    actual_files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "MANIFEST.json")
    actual_map = {path.relative_to(root).as_posix(): path.stat().st_size for path in actual_files}
    if listed_map != actual_map:
        errors.append("MANIFEST.json 文件清单或字节数与发布目录不一致")

    errors.extend(_walk_keys(plan, "plan"))
    for index, row in enumerate(attempts):
        errors.extend(_walk_keys(row, f"attempts[{index}]"))
    expected_tasks = {_task_key(task) for task in plan.get("tasks", [])}
    trial_tasks = {_task_key(trial) for trial in trials}
    config = plan.get("config", {})
    models = config.get("models", [])
    problem_ids = [str(problem.get("id", "")) for problem in benchmark.get("problems", [])]
    exact_matrix = {
        (str(models[0].get("id", "")), str(repeat), representation, problem_id)
        for repeat in range(1, 4)
        for representation in ("raw", "normalized", "structured")
        for problem_id in problem_ids
    } if len(models) == 1 else set()
    if (
        benchmark.get("version") != "repair24-v1"
        or len(problem_ids) != 24
        or len(set(problem_ids)) != 24
        or config.get("repeats") != 3
        or config.get("representations") != ["raw", "normalized", "structured"]
        or expected_tasks != exact_matrix
        or trial_tasks != expected_tasks
    ):
        errors.append("计划与任务摘要未形成唯一的 216 任务矩阵")

    by_task: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in attempts:
        by_task[_task_key(row)].append(row)
    if len(attempts) != manifest.get("counts", {}).get("attempts"):
        errors.append("逐轮记录数与 MANIFEST.json 不一致")
    for key in sorted(expected_tasks):
        rows = by_task.get(key, [])
        rounds = [row.get("round") for row in rows]
        if not rows or rounds != list(range(1, len(rows) + 1)) or len(rows) > 3:
            errors.append(f"逐轮记录不连续: {key}")
        if any(row.get("experiment_id") != plan.get("experiment_id") for row in rows):
            errors.append(f"逐轮记录 experiment_id 不一致: {key}")

    successful = {_task_key(row) for row in trials if row.get("compile_ok") is True}
    failed = trial_tasks - successful
    proof_files = sorted((root / "solutions").rglob("*.lean")) if (root / "solutions").exists() else []
    counts = manifest.get("counts", {})
    if (len(trials), len(successful), len(failed), len(proof_files)) != (
        counts.get("tasks"), counts.get("successes"), counts.get("failed_tasks"), counts.get("proof_files")
    ):
        errors.append("任务、成功、失败或证明数量与 MANIFEST.json 不一致")
    if len(trials) != 216 or not successful:
        errors.append("Feedback Study 发布包必须包含完整 216 任务且至少有一个成功证明")
    for trial in trials:
        solution = trial.get("solution")
        if trial.get("compile_ok") is True:
            if not isinstance(solution, str) or not (root / solution).is_file():
                errors.append(f"成功任务缺少证明: {_task_key(trial)}")
        elif solution is not None:
            errors.append(f"失败任务不应引用证明: {_task_key(trial)}")

    with (root / "ai_assisted_review.csv").open(encoding="utf-8-sig", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    review = {_task_key(row): row for row in review_rows}
    if (
        len(review_rows) != counts.get("review_rows")
        or len(review_rows) != 216
        or set(review) != expected_tasks
    ):
        errors.append("AI 辅助复核表未唯一覆盖 216 个任务")
    for key in successful:
        row = review.get(key, {})
        if not (
            row.get("review_mode") == "ai_assisted"
            and row.get("kernel_pass") == "yes"
            and row.get("inappropriate_assumption") == "no"
            and row.get("leakage_risk") == "no"
            and str(row.get("reviewer_note", "")).strip()
        ):
            errors.append(f"成功任务的 AI 辅助复核不完整: {key}")
    if any(row.get("review_mode") != "ai_assisted" for row in review_rows):
        errors.append("复核表存在非 ai_assisted 模式")

    if not (
        summary.get("trajectory_valid") is True
        and summary.get("design_complete") is True
        and summary.get("review_mode") == "ai_assisted"
        and summary.get("ai_assisted_review_complete") is True
        and summary.get("release_ready") is True
    ):
        errors.append("summary.json 未通过 Feedback Study 本地正式门禁")
    if completion.get("complete") is not True or completion.get("infrastructure_errors") != 0:
        errors.append("completion.sanitized.json 未记录完整且无残留基础设施错误的矩阵")
    if completion.get("archived_retry_attempts") != summary.get("archived_transport_retry_attempts"):
        errors.append("传输重试披露在 completion 与 summary 中不一致")
    budget_calls = completion.get("budget", {}).get("attempted_calls")
    if budget_calls != counts.get("attempted_call_reservations"):
        errors.append("预算账本调用预留数与 MANIFEST.json 不一致")
    elif budget_calls != (
        len(attempts)
        + counts.get("archived_retry_round_records", -1)
        + counts.get("unmatched_call_reservations", -1)
    ):
        errors.append("调用预留数无法由公开逐轮记录、归档失败计数和未配对预留解释")

    compiled = 0
    if compile_solutions and not errors:
        for proof in proof_files:
            result = run_lean_file(proof, timeout, ROOT)
            if not result.ok or diagnostics_use_sorry(result.diagnostics):
                errors.append(f"公开证明独立编译失败: {proof.relative_to(root).as_posix()}")
                break
            compiled += 1

    return {
        "ok": not errors,
        "tasks": len(trials),
        "attempts": len(attempts),
        "successes": len(successful),
        "failed_tasks": len(failed),
        "proof_files": len(proof_files),
        "compiled_proofs": compiled,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--compile-solutions", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    result = audit_release(args.release, args.compile_solutions, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
