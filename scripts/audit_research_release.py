"""审计 repair24 正式六臂实验的脱敏发布包。"""

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


FORMAT = "tracer-repair24-six-arm-release-v1"
ARMS = ("A", "B", "C", "D", "C_dynamic", "C_failure")
ARM_RUNTIME = {
    "A": ("A", "static"),
    "B": ("B", "static"),
    "C": ("C", "static"),
    "D": ("D", "static"),
    "C_dynamic": ("C", "diagnostic"),
    "C_failure": ("C", "diagnostic"),
}
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
    rows: list[dict] = []
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
            if lowered in {"prompt", "prompt_templates"}:
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
        str(row.get("arm", "")),
        str(row.get("problem_id", "")),
    )


def audit_release(root: Path, compile_solutions: bool = False, timeout: int = 180) -> dict:
    root = root.resolve()
    errors: list[str] = []
    required = {
        "README.md", "FILES.md", "MANIFEST.json", "summary.json", "plan.sanitized.json",
        "preregistration.json", "benchmark.json", "examples.sanitized.json", "failure_notes.sanitized.json",
        "completion.sanitized.json", "initial_compilation.sanitized.json", "trials.jsonl",
        "attempts.sanitized.jsonl", "ai_assisted_review.csv", "ai_review_report.json",
        "protocol/theorem_only.txt", "protocol/feedback.txt", "protocol/feedback_retrieval.txt",
        "protocol/retrieval_only.txt", "protocol/proof_contract.txt",
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
        preregistration = _read_json(root / "preregistration.json")
        benchmark = _read_json(root / "benchmark.json")
        summary = _read_json(root / "summary.json")
        completion = _read_json(root / "completion.sanitized.json")
        ai_review = _read_json(root / "ai_review_report.json")
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
    errors.extend(_walk_keys(preregistration, "preregistration"))
    for index, row in enumerate(attempts):
        errors.extend(_walk_keys(row, f"attempts[{index}]"))

    config = plan.get("config", {})
    models = config.get("models", [])
    problem_ids = [str(problem.get("id", "")) for problem in benchmark.get("problems", [])]
    model_ids = [str(model.get("id", "")) for model in models]
    exact_matrix = {
        (model_id, str(repeat), arm, problem_id)
        for model_id in model_ids
        for repeat in range(1, 4)
        for arm in ARMS
        for problem_id in problem_ids
    }
    planned = {_task_key(task) for task in plan.get("tasks", [])}
    trial_tasks = {_task_key(trial) for trial in trials}
    if (
        benchmark.get("version") != "repair24-v1"
        or len(problem_ids) != 24
        or len(set(problem_ids)) != 24
        or len(model_ids) != 2
        or len(set(model_ids)) != 2
        or config.get("repeats") != 3
        or tuple(config.get("arms", [])) != ARMS
        or config.get("max_rounds") != 3
        or config.get("compile_timeout") != 180
        or planned != exact_matrix
        or trial_tasks != exact_matrix
        or len(trials) != 864
    ):
        errors.append("计划与任务摘要未形成冻结的 864 任务六臂矩阵")
    if (
        preregistration.get("version") != "tracer-repair24-six-arm-preregistration-v1"
        or preregistration.get("planned_tasks") != 864
        or preregistration.get("max_generations") != 2592
        or preregistration.get("primary_comparison") != "B - A"
        or preregistration.get("config") != config
    ):
        errors.append("机器可读预注册与六臂发布合同不一致")

    by_task: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    run_ids: set[str] = set()
    for row in attempts:
        by_task[_task_key(row)].append(row)
    for key in sorted(exact_matrix):
        rows = by_task.get(key, [])
        rounds = [row.get("round") for row in rows]
        if not rows or len(rows) > 3 or rounds != list(range(1, len(rows) + 1)):
            errors.append(f"逐轮记录不连续: {key}")
            continue
        ids = {str(row.get("run_id", "")) for row in rows}
        if len(ids) != 1 or "" in ids or ids & run_ids:
            errors.append(f"任务 run_id 不唯一: {key}")
        run_ids.update(ids)
        if any(row.get("provider_error") or row.get("cache_hit") for row in rows):
            errors.append(f"逐轮记录含 provider 错误或缓存复用: {key}")
        if any(row.get("experiment_id") != plan.get("experiment_id") for row in rows):
            errors.append(f"逐轮记录 experiment_id 不一致: {key}")
        trial = next((item for item in trials if _task_key(item) == key), {})
        model = next((item for item in models if str(item.get("id")) == key[0]), {})
        condition, strategy = ARM_RUNTIME[key[2]]
        if any(
            row.get("provider") != "openai_compatible"
            or row.get("condition") != condition
            or row.get("retrieval_strategy") != strategy
            or row.get("compile_timed_out") is True
            or row.get("provider_config", {}).get("url") != model.get("api_url")
            or any(
                row.get("provider_config", {}).get(field) != model.get(field)
                for field in (
                    "model", "temperature", "max_tokens", "thinking", "reasoning_effort",
                    "input_price_per_1k", "output_price_per_1k",
                )
            )
            for row in rows
        ):
            errors.append(f"逐轮记录与冻结模型、条件或检索策略不一致: {key}")
        if (
            trial.get("experiment_id") != plan.get("experiment_id")
            or trial.get("error")
            or (trial.get("compile_ok") is True and trial.get("independent_compile_ok") is not True)
        ):
            errors.append(f"任务摘要的实验编号、错误或独立编译状态无效: {key}")
        if trial.get("compile_ok") is True:
            if rows[-1].get("compile_ok") is not True or any(row.get("compile_ok") for row in rows[:-1]):
                errors.append(f"成功任务的轮次结局无效: {key}")
        elif len(rows) != 3 or any(row.get("compile_ok") for row in rows):
            errors.append(f"失败任务未用完三轮且无成功轮次: {key}")

    counts = manifest.get("counts", {})
    successful = {_task_key(row) for row in trials if row.get("compile_ok") is True}
    failed = exact_matrix - successful
    proof_files = sorted((root / "solutions").rglob("*.lean")) if (root / "solutions").exists() else []
    if (len(trials), len(attempts), len(successful), len(failed), len(proof_files)) != (
        counts.get("tasks"), counts.get("attempts"), counts.get("successes"),
        counts.get("failed_tasks"), counts.get("proof_files"),
    ):
        errors.append("任务、轮次、成功、失败或证明数量与 MANIFEST.json 不一致")
    if not successful:
        errors.append("六臂发布包至少需要一个成功证明")
    for trial in trials:
        solution = trial.get("solution")
        key = _task_key(trial)
        if trial.get("compile_ok") is True:
            if not isinstance(solution, str) or not (root / solution).is_file():
                errors.append(f"成功任务缺少证明: {key}")
        elif solution is not None:
            errors.append(f"失败任务不应引用证明: {key}")

    with (root / "ai_assisted_review.csv").open(encoding="utf-8-sig", newline="") as handle:
        review_rows = list(csv.DictReader(handle))
    review = {_task_key(row): row for row in review_rows}
    if (
        len(review_rows) != 864
        or len(review) != 864
        or set(review) != exact_matrix
        or counts.get("review_rows") != len(review_rows)
    ):
        errors.append("AI 辅助复核表未唯一覆盖 864 个任务")
    if any(row.get("review_mode") != "ai_assisted" for row in review_rows):
        errors.append("复核表存在非 ai_assisted 模式")
    for key in successful:
        row = review.get(key, {})
        if not (
            row.get("kernel_pass") == "yes"
            and row.get("inappropriate_assumption") == "no"
            and row.get("leakage_risk") == "no"
            and str(row.get("reviewer_note", "")).strip()
        ):
            errors.append(f"成功任务的 AI 辅助复核不完整: {key}")
    if not (
        ai_review.get("format") == "tracer-research-ai-assisted-review-v1"
        and ai_review.get("experiment_id") == plan.get("experiment_id")
        and ai_review.get("review_mode") == "ai_assisted"
        and ai_review.get("tasks") == len(exact_matrix)
        and ai_review.get("successful_tasks") == len(successful)
        and ai_review.get("failed_tasks_not_proof_reviewed") == len(failed)
        and ai_review.get("reviewed_successes") == len(successful)
        and ai_review.get("errors") == []
        and ai_review.get("complete") is True
    ):
        errors.append("AI 辅助复核报告与任务矩阵、复核表或实验编号不一致")

    if not (
        summary.get("trajectory_valid") is True
        and summary.get("full_research_design") is True
        and summary.get("manual_review_complete") is True
        and summary.get("release_ready") is True
    ):
        errors.append("summary.json 未通过六臂实验本地正式门禁")
    if completion.get("complete") is not True or completion.get("infrastructure_errors") != 0:
        errors.append("completion.sanitized.json 未记录完整且无残留基础设施错误的矩阵")
    budget_calls = completion.get("budget", {}).get("attempted_calls")
    if budget_calls != counts.get("attempted_call_reservations"):
        errors.append("预算账本调用预留数与 MANIFEST.json 不一致")
    elif budget_calls != (
        len(attempts)
        + counts.get("archived_retry_round_records", -1)
        + counts.get("unmatched_call_reservations", -1)
    ):
        errors.append("调用预留数无法由公开轮次、归档轮次和未配对预留解释")
    retry_inventory = summary.get("publication_retry_inventory", {})
    if (
        retry_inventory.get("observed_attempt_directories") != counts.get("archived_retry_attempts")
        or retry_inventory.get("observed_round_records") != counts.get("archived_retry_round_records")
    ):
        errors.append("发布报告与 MANIFEST.json 的续跑盘点不一致")

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
