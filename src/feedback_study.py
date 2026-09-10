"""原始、规范化、结构化编译反馈的独立受控对照实验。"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import shutil
import statistics
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from agent import ROOT, solve_problem
from compiler import diagnostics_use_sorry, find_project_root, isolate_target, patch_proof_region, run_lean_file
from provider import OpenAICompatibleProvider, redact_sensitive_text
from research import CallBudget, PricedProvider, check_benchmark, load_benchmark, load_config as load_research_config, prompt_api_keys, write_json
from feedback_adoption import analyze_trace, summarize_analyses
from leancapsule.privacy import redact_value


PROTOCOL_VERSION = "tracer-feedback-study-v1"
REPRESENTATIONS = ("raw", "normalized", "structured")
AI_ASSISTED_REVIEW_FILE = "ai_assisted_review.csv"
LEGACY_REVIEW_FILE = "manual_review.csv"


def review_path(out: Path) -> Path:
    """优先使用显式 AI 辅助复核表，同时兼容旧批次文件名。"""

    current = out / AI_ASSISTED_REVIEW_FILE
    if current.is_file():
        return current
    legacy = out / LEGACY_REVIEW_FILE
    if legacy.is_file():
        return legacy
    return current


def latest_infrastructure_error(out: Path) -> str | None:
    """按冻结任务顺序返回当前未归档的基础设施错误。"""

    plan_path = out / "plan.json"
    if not plan_path.is_file():
        return None
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for task in plan.get("tasks", []):
        path = trial_path(out, task) / "trial.json"
        if not path.is_file():
            continue
        error = json.loads(path.read_text(encoding="utf-8")).get("error")
        if error:
            return str(error)
    return None


def is_retryable_transport_error(error: str | None) -> bool:
    """只识别可安全重试的网络传输错误，不重试证明或鉴权失败。"""

    if not error:
        return False
    lowered = error.lower()
    transport_markers = (
        "incompleteread",
        "remotedisconnected",
        "connectionreseterror",
        "connection reset",
        "connection aborted",
        "remote end closed connection",
        "winerror 10054",
        "远程主机强迫关闭",
        "timed out",
        "timeouterror",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    )
    return any(marker in lowered for marker in transport_markers)


def validate_config(path: Path) -> dict:
    """校验专用配置，同时复用研究模型字段的严格规则。"""

    import tempfile

    config = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "models", "repeats", "representations", "max_rounds", "compile_timeout",
        "order_seed", "examples_dir",
    }
    if set(config) - allowed:
        raise ValueError("反馈实验配置存在未知字段；不得将密钥写入配置")
    if config.get("representations") != list(REPRESENTATIONS):
        raise ValueError("反馈实验必须按冻结顺序包含 raw、normalized、structured 三组")
    with tempfile.TemporaryDirectory() as directory:
        bridge = Path(directory) / "config.json"
        research_fields = {key: value for key, value in config.items() if key != "representations"}
        bridge.write_text(json.dumps({**research_fields, "arms": ["B"]}, ensure_ascii=False), encoding="utf-8")
        validated = load_research_config(bridge)
    validated.pop("arms")
    validated["representations"] = list(REPRESENTATIONS)
    return validated


def apply_direct_model_config(
    config: dict,
    api_url: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    input_price_per_1k: float | None = None,
    output_price_per_1k: float | None = None,
) -> dict:
    """用命令行参数替换示例模型；密钥仍只通过隐藏输入或环境变量传入。"""

    direct = api_url is not None or model is not None
    optional_direct = any(value is not None for value in (
        temperature, max_tokens, thinking, reasoning_effort,
        input_price_per_1k, output_price_per_1k,
    ))
    if direct and (api_url is None or model is None):
        raise ValueError("--api-url 和 --model 必须同时提供")
    if optional_direct and not direct:
        raise ValueError("生成参数覆盖必须与 --api-url、--model 一起使用")
    if not direct:
        return config
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("命令行 API 地址必须为不含凭据或查询参数的 HTTPS URL")
    if not model.strip():
        raise ValueError("模型名称不能为空")
    selected = dict(config["models"][0])
    selected.update({
        "id": "deepseek",
        "api_url": api_url,
        "model": model.strip(),
        "api_key_env": "TRACER_FEEDBACK_MODEL_KEY",
    })
    if temperature is not None:
        if not 0 <= temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        selected["temperature"] = temperature
    if max_tokens is not None:
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("max-tokens 必须为正整数")
        selected["max_tokens"] = max_tokens
    if thinking is not None:
        if thinking not in {"enabled", "disabled"}:
            raise ValueError("thinking 必须为 enabled 或 disabled")
        selected["thinking"] = thinking
    if reasoning_effort is not None:
        if reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("reasoning-effort 必须为 low、high 或 max")
        selected["reasoning_effort"] = reasoning_effort
    for key, value in (
        ("input_price_per_1k", input_price_per_1k),
        ("output_price_per_1k", output_price_per_1k),
    ):
        if value is not None:
            if not math.isfinite(value) or value < 0:
                raise ValueError("价格必须为非负数")
            selected[key] = value
    return {**config, "models": [selected]}


def build_plan(config: dict, benchmark: dict) -> list[dict]:
    tasks = [
        {
            "model_id": model["id"],
            "repeat": repeat,
            "representation": representation,
            "problem_id": problem["id"],
        }
        for repeat in range(1, config["repeats"] + 1)
        for model in config["models"]
        for representation in REPRESENTATIONS
        for problem in benchmark["problems"]
    ]
    random.Random(config.get("order_seed", 20260909)).shuffle(tasks)
    return tasks


def trial_path(out: Path, task: dict) -> Path:
    return out / "trials" / task["model_id"] / str(task["repeat"]) / task["representation"] / task["problem_id"]


def _providers(config: dict, api_keys: dict[str, str] | None, budget: CallBudget | None) -> dict:
    providers = {}
    for model in config["models"]:
        if "REPLACE" in model["model"] or "实际模型" in model["model"]:
            raise ValueError("请先替换反馈实验配置中的示例模型名称")
        key = (api_keys or {}).get(model["api_key_env"], os.environ.get(model["api_key_env"], "")).strip()
        if not key:
            raise ValueError("未设置密钥环境变量：" + model["api_key_env"])
        provider = OpenAICompatibleProvider(
            url=model["api_url"], api_key=key, model=model["model"], wire_api="chat_completions",
            temperature=model["temperature"], max_tokens=model["max_tokens"],
            thinking=model.get("thinking"), reasoning_effort=model.get("reasoning_effort"),
            max_attempts=1, request_timeout=180,
        )
        providers[model["id"]] = PricedProvider(provider, model, budget)
    return providers


def _archive_failed_trial(out: Path, destination: Path) -> Path:
    """在续跑前保留失败请求的全部原始工件。"""

    relative = destination.relative_to(out / "trials")
    root = out / "retry_history" / relative
    attempt = 1
    while (root / f"attempt-{attempt}").exists():
        attempt += 1
    archived = root / f"attempt-{attempt}"
    archived.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(destination), str(archived))
    return archived


def run_matrix(config: dict, benchmark_path: Path, out: Path, api_keys=None, budget=None, resume=False) -> bool:
    benchmark = load_benchmark(benchmark_path)
    providers = _providers(config, api_keys, budget)
    initial_rows = check_benchmark(benchmark_path, config.get("compile_timeout", 60))
    initial = {row["problem_id"]: row for row in initial_rows}
    tasks = build_plan(config, benchmark)
    prompt_snapshot = {
        name: (ROOT / "prompts" / name).read_text(encoding="utf-8")
        for name in ("feedback.txt", "proof_contract.txt")
    }
    if resume:
        plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
        frozen_benchmark = json.loads((out / "benchmark.json").read_text(encoding="utf-8"))
        if (
            plan.get("protocol_version") != PROTOCOL_VERSION
            or plan.get("config") != config
            or plan.get("tasks") != tasks
            or plan.get("prompt_templates") != prompt_snapshot
            or frozen_benchmark != benchmark
        ):
            raise ValueError("续跑参数、题库或提示模板与原批次不一致")
        if not review_path(out).is_file():
            raise ValueError("续跑批次缺少复核表")
        experiment_id = plan["experiment_id"]
    else:
        out.mkdir(parents=True, exist_ok=False)
        experiment_id = "feedback-study-" + str(uuid.uuid4())
        write_json(out / "plan.json", {
            "protocol_version": PROTOCOL_VERSION,
            "experiment_id": experiment_id,
            "config": config,
            "benchmark_version": benchmark["version"],
            "tasks": tasks,
            "platform": platform.system(),
            "python": platform.python_version(),
            "lean_toolchain": (ROOT / "lean-toolchain").read_text(encoding="utf-8").strip(),
            "feedback_protocol": json.loads((ROOT / "experiments/feedback_study.protocol.json").read_text(encoding="utf-8")),
            "prompt_templates": prompt_snapshot,
            "status": "running",
        })
        write_json(out / "benchmark.json", benchmark)
        write_json(out / "initial_compilation.json", redact_value(initial))
        with (out / AI_ASSISTED_REVIEW_FILE).open("w", newline="", encoding="utf-8") as handle:
            fields = ["experiment_id", "model_id", "repeat", "representation", "problem_id", "kernel_pass", "inappropriate_assumption", "leakage_risk", "review_mode", "reviewer_note"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({"experiment_id": experiment_id, **task, "review_mode": "ai_assisted"} for task in tasks)
    if budget is not None:
        budget.ledger_path = out / "budget.json"
        write_json(budget.ledger_path, budget.snapshot())

    problems = {problem["id"]: problem for problem in benchmark["problems"]}
    completed = []
    for index, task in enumerate(tasks, 1):
        destination = trial_path(out, task)
        if resume and destination.exists():
            trial_file, runs_file = destination / "trial.json", destination / "runs.jsonl"
            previous = json.loads(trial_file.read_text(encoding="utf-8")) if trial_file.is_file() else None
            if (
                previous
                and not previous.get("error")
                and previous.get("experiment_id") == experiment_id
                and all(previous.get(key) == value for key, value in task.items())
                and runs_file.is_file()
            ):
                completed.append(previous)
                print(f"{index}/{len(tasks)} {task['model_id']} r{task['repeat']} {task['representation']} {task['problem_id']}: SKIP", flush=True)
                continue
            archived = _archive_failed_trial(out, destination)
            print("已保留失败尝试: " + str(archived.relative_to(out)), flush=True)
        destination.mkdir(parents=True)
        problem = problems[task["problem_id"]]
        source_path = benchmark_path.parent / problem["file"]
        started = time.perf_counter()
        error = None
        result = {"compile_ok": False}
        independent_ok = None
        try:
            if source_path.read_text(encoding="utf-8") != problem["source_text"]:
                raise ValueError("反馈实验运行中冻结源码发生改变")
            result = solve_problem(
                source_path, problem["theorem"], "B", providers[task["model_id"]],
                config.get("max_rounds", 3), config.get("compile_timeout", 60),
                ROOT / config.get("examples_dir", "examples"), destination / "unused.sqlite3",
                destination / "solutions", destination / "runs.jsonl",
                benchmark_id=problem["id"], tags=problem["tags"], difficulty=problem["difficulty"],
                experiment_id=experiment_id, use_cache=False, record_prompt=True,
                initial_feedback=initial[problem["id"]]["diagnostic"],
                initial_diagnostics=initial[problem["id"]]["raw_diagnostics"],
                feedback_representation=task["representation"],
                prompt_templates=prompt_snapshot,
            )
            error = result.get("provider_error")
            task_log = destination / "runs.jsonl"
            if task_log.exists():
                recorded = [json.loads(line) for line in task_log.read_text(encoding="utf-8").splitlines() if line.strip()]
                if any(
                    row.get("compile_timed_out")
                    or row.get("diagnostic", {}).get("category") in {"patch_error", "candidate_security"}
                    or (row.get("compile_invoked") and row.get("compile_returncode") is None)
                    for row in recorded
                ):
                    error = "编译超时或工具链/补丁错误；停止反馈表示对照"
            if result["compile_ok"] and not error:
                saved = list((destination / "solutions" / "B").glob("*.lean"))
                if len(saved) != 1:
                    raise ValueError("反馈实验缺少唯一成功证明")
                checked = run_lean_file(saved[0], config.get("compile_timeout", 60), find_project_root(source_path))
                if not checked.ok or diagnostics_use_sorry(checked.diagnostics):
                    raise ValueError("反馈实验成功证明独立复编译失败")
                independent_ok = True
        except Exception as exc:
            error = redact_sensitive_text(exc)
        trial = {
            **task,
            "experiment_id": experiment_id,
            "compile_ok": bool(result.get("compile_ok")) and error is None,
            "independent_compile_ok": independent_ok,
            "error": error,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        write_json(destination / "trial.json", redact_value(trial, (ROOT,)))
        completed.append(trial)
        print(f"{index}/{len(tasks)} {task['model_id']} r{task['repeat']} {task['representation']} {task['problem_id']}: " + ("ERROR" if error else "PASS" if trial["compile_ok"] else "FAIL"), flush=True)
        if error:
            break
    write_json(out / "completion.json", {
        "planned": len(tasks),
        "completed": len(completed),
        "complete": len(completed) == len(tasks),
        "infrastructure_errors": sum(bool(item["error"]) for item in completed),
        "archived_retry_attempts": len(list((out / "retry_history").rglob("trial.json")))
            if (out / "retry_history").exists() else 0,
        "budget": budget.snapshot() if budget else None,
    })
    return len(completed) == len(tasks) and not any(item["error"] for item in completed)


def summarize(out: Path, allow_partial: bool = False) -> dict:
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    benchmark = json.loads((out / "benchmark.json").read_text(encoding="utf-8"))
    errors = []
    if plan.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("反馈实验协议版本不匹配")
    if plan.get("tasks") != build_plan(plan["config"], benchmark):
        errors.append("反馈实验计划与冻结配置不一致")
    groups = defaultdict(list)
    successes = set()
    global_runs = set()
    completion = json.loads((out / "completion.json").read_text(encoding="utf-8")) if (out / "completion.json").exists() else {}
    if completion.get("planned") != len(plan["tasks"]) or completion.get("completed") != len(plan["tasks"]) or not completion.get("complete"):
        errors.append("completion.json 未记录完整矩阵")
    problems = {problem["id"]: problem for problem in benchmark["problems"]}
    for task in plan["tasks"]:
        destination = trial_path(out, task)
        if not (destination / "trial.json").exists() or not (destination / "runs.jsonl").exists():
            errors.append("缺少任务：" + "/".join(str(value) for value in task.values()))
            continue
        trial = json.loads((destination / "trial.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (destination / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        valid = (
            trial.get("experiment_id") == plan["experiment_id"]
            and all(trial.get(key) == value for key, value in task.items())
            and rows
            and [row.get("round") for row in rows] == list(range(1, len(rows) + 1))
            and len(rows) <= plan["config"].get("max_rounds", 3)
            and (bool(rows[-1].get("compile_ok")) or len(rows) == plan["config"].get("max_rounds", 3))
            and len({row.get("run_id") for row in rows}) == 1
            and all(not row.get("cache_hit") and row.get("feedback_representation") == task["representation"] for row in rows)
            and all(
                row.get("experiment_id") == plan["experiment_id"]
                and row.get("problem_id") == task["problem_id"]
                and row.get("condition") == "B"
                and not row.get("provider_error")
                and not row.get("compile_timed_out")
                for row in rows
            )
            and bool(trial.get("compile_ok")) == bool(rows[-1].get("compile_ok"))
            and not trial.get("error")
        )
        if rows:
            run_id = rows[0].get("run_id")
            if not run_id or run_id in global_runs:
                valid = False
            global_runs.add(run_id)
        model = next(model for model in plan["config"]["models"] if model["id"] == task["model_id"])
        valid = valid and all(
            row.get("provider_config", {}).get("url") == model["api_url"]
            and all(row.get("provider_config", {}).get(key) == model.get(key) for key in (
                "model", "temperature", "max_tokens", "thinking", "reasoning_effort",
                "input_price_per_1k", "output_price_per_1k",
            ))
            for row in rows
        )
        if trial.get("compile_ok"):
            valid = valid and trial.get("independent_compile_ok") is True
            problem = problems[task["problem_id"]]
            solutions = list((destination / "solutions" / "B").glob("*.lean"))
            expected_source = patch_proof_region(
                problem["source_text"], rows[-1]["candidate"], problem["theorem"],
                "-- PROOF_START", "-- PROOF_END",
            )
            expected = isolate_target(problem["source_text"], expected_source, problem["theorem"])
            valid = valid and len(solutions) == 1 and solutions[0].read_text(encoding="utf-8") == expected
            successes.add((task["model_id"], str(task["repeat"]), task["representation"], task["problem_id"]))
        if not valid:
            errors.append("无效任务轨迹：" + str(destination.relative_to(out)))
        groups[(task["model_id"], task["representation"])].append((trial, rows))
    if errors and not allow_partial:
        raise ValueError("正式反馈对照门禁拒绝当前批次：" + "; ".join(errors[:5]))

    summary = []
    for (model, representation), items in sorted(groups.items()):
        tokens = [row.get("usage", {}).get("total_tokens") for _, rows in items for row in rows]
        costs = [row.get("estimated_cost_usd") for _, rows in items for row in rows]
        adoption = summarize_analyses([
            analyze_trace(rows, f"{model}/{representation}/{trial['problem_id']}")
            for trial, rows in items if rows
        ])
        summary.append({
            "model": model,
            "representation": representation,
            "tasks": len(items),
            "pass_at_1": sum(bool(rows[0].get("compile_ok")) for _, rows in items),
            "pass_within_budget": sum(bool(trial.get("compile_ok")) for trial, _ in items),
            "avg_rounds": statistics.mean(len(rows) for _, rows in items),
            "avg_wall_ms": statistics.mean(trial["elapsed_ms"] for trial, _ in items),
            "total_tokens": sum(tokens) if tokens and all(isinstance(value, int) for value in tokens) else None,
            "total_estimated_cost_usd": sum(costs) if costs and all(isinstance(value, (int, float)) for value in costs) else None,
            "feedback_relevant_change_rate": adoption["relevant_change_rate"],
            "repeated_error_category_rate": adoption["repeated_error_category_rate"],
        })
    reviewed = set()
    selected_review_path = review_path(out)
    observed_review_modes = set()
    with selected_review_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_mode = row.get("review_mode", "legacy_manual" if selected_review_path.name == LEGACY_REVIEW_FILE else "")
            observed_review_modes.add(row_mode)
            if row.get("kernel_pass") == "yes" and row.get("inappropriate_assumption") == "no" and row.get("leakage_risk") == "no" and row.get("reviewer_note", "").strip():
                reviewed.add((row["model_id"], row["repeat"], row["representation"], row["problem_id"]))
    design_complete = plan["config"].get("repeats", 0) >= 3 and plan["config"].get("representations") == list(REPRESENTATIONS)
    lookup = {
        (trial["model_id"], trial["repeat"], trial["problem_id"], trial["representation"]): (trial, rows)
        for items in groups.values() for trial, rows in items
    }
    paired = []
    for model in plan["config"]["models"]:
        for treatment, baseline in (("normalized", "raw"), ("structured", "raw"), ("structured", "normalized")):
            differences = []
            for key, (trial, rows) in lookup.items():
                if key[0] != model["id"] or key[3] != treatment:
                    continue
                other = lookup.get((*key[:3], baseline))
                if other:
                    differences.append({
                        "success_delta": int(trial["compile_ok"]) - int(other[0]["compile_ok"]),
                        "round_delta": len(rows) - len(other[1]),
                    })
            if differences:
                paired.append({
                    "model": model["id"],
                    "comparison": treatment + " - " + baseline,
                    "matched_pairs": len(differences),
                    "mean_success_delta": statistics.mean(item["success_delta"] for item in differences),
                    "mean_round_delta": statistics.mean(item["round_delta"] for item in differences),
                    "interpretation": "描述性逐题配对，不是显著性检验。",
                })
    review_complete = successes <= reviewed
    review_mode = "ai_assisted" if observed_review_modes == {"ai_assisted"} else "legacy_manual"
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": plan["experiment_id"],
        "trajectory_valid": not errors,
        "design_complete": design_complete,
        "review_mode": review_mode,
        "review_complete": review_complete,
        "ai_assisted_review_complete": review_mode == "ai_assisted" and review_complete,
        "release_ready": not errors and design_complete and bool(successes) and review_complete,
        "archived_transport_retry_attempts": completion.get("archived_retry_attempts", 0),
        "errors": errors,
        "summary": summary,
        "paired_comparisons": paired,
        "interpretation": "按同模型、同题、同重复进行三种反馈表示的描述性配对比较；网络失败续跑次数单独披露；不自动声称因果增益或统计显著。",
    }
    write_json(out / "summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    run_parser = sub.add_parser("run")
    report_parser = sub.add_parser("report")
    for command in (plan_parser, run_parser):
        command.add_argument("--config", type=Path, default=ROOT / "experiments/feedback_study.example.json")
        command.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks/repair24/manifest.json")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--resume", action="store_true", help="续跑同一冻结批次；保留旧失败请求并跳过已完成任务")
    run_parser.add_argument(
        "--auto-resume-network", type=int, default=0, metavar="N",
        help="遇到可重试网络错误时在同一进程内自动续跑至多 N 次；默认 0",
    )
    run_parser.add_argument("--api-key-prompt", action="store_true")
    run_parser.add_argument(
        "--show-key-confirmation", action="store_true",
        help="仅显示密钥长度和末四位；不显示完整密钥，不写入轨迹",
    )
    run_parser.add_argument("--api-url", help="直接覆盖单个 HTTPS Chat Completions 端点")
    run_parser.add_argument("--model", help="直接覆盖单个真实模型名称")
    run_parser.add_argument("--temperature", type=float)
    run_parser.add_argument("--max-tokens", type=int)
    run_parser.add_argument("--thinking", choices=("enabled", "disabled"))
    run_parser.add_argument("--reasoning-effort", choices=("low", "high", "max"))
    run_parser.add_argument("--input-price-per-1k", type=float)
    run_parser.add_argument("--output-price-per-1k", type=float)
    run_parser.add_argument("--max-calls", type=int, help="默认为冻结矩阵所需的最大生成数")
    cost_group = run_parser.add_mutually_exclusive_group(required=True)
    cost_group.add_argument("--max-reserved-usd", type=float)
    cost_group.add_argument("--no-cost-limit", action="store_true", help="不设本地美元上限；仍受冻结调用次数限制")
    report_parser.add_argument("--run", type=Path, required=True)
    report_parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "report":
            result = summarize(args.run.resolve(), args.allow_partial)
        else:
            config = validate_config(args.config)
            if args.command == "run":
                config = apply_direct_model_config(
                    config, args.api_url, args.model, args.temperature, args.max_tokens,
                    args.thinking, args.reasoning_effort,
                    args.input_price_per_1k, args.output_price_per_1k,
                )
            benchmark = load_benchmark(args.benchmark)
            tasks = build_plan(config, benchmark)
            if args.command == "plan":
                result = {
                    "protocol_version": PROTOCOL_VERSION,
                    "benchmark": benchmark["version"],
                    "models": len(config["models"]),
                    "repeats": config["repeats"],
                    "representations": list(REPRESENTATIONS),
                    "tasks": len(tasks),
                    "max_generations": len(tasks) * config.get("max_rounds", 3),
                    "network_calls": 0,
                }
            else:
                if args.resume and not args.out.exists():
                    raise ValueError("续跑要求输出目录已存在")
                if not args.resume and args.out.exists():
                    raise ValueError("输出目录已存在，不覆盖旧反馈实验")
                if not 0 <= args.auto_resume_network <= 50:
                    raise ValueError("--auto-resume-network 必须在 0 到 50 之间")
                frozen_max_calls = len(tasks) * config.get("max_rounds", 3)
                max_calls = args.max_calls if args.max_calls is not None else frozen_max_calls
                budget = CallBudget(max_calls, None if args.no_cost_limit else args.max_reserved_usd)
                if args.resume:
                    budget.restore(json.loads((args.out / "budget.json").read_text(encoding="utf-8")))
                if args.show_key_confirmation and not args.api_key_prompt:
                    raise ValueError("--show-key-confirmation 必须与 --api-key-prompt 一起使用")
                keys = prompt_api_keys(config, args.show_key_confirmation) if args.api_key_prompt else None
                output = args.out.resolve()
                resume = args.resume
                automatic_resumes = 0
                while True:
                    if run_matrix(
                        config, args.benchmark.resolve(), output, keys, budget, resume=resume,
                    ):
                        return 0
                    error = latest_infrastructure_error(output)
                    if (
                        automatic_resumes >= args.auto_resume_network
                        or not is_retryable_transport_error(error)
                    ):
                        return 1
                    automatic_resumes += 1
                    delay = min(2 ** (automatic_resumes - 1), 10)
                    print(
                        f"检测到可重试的网络中断；{delay} 秒后自动续跑 "
                        f"({automatic_resumes}/{args.auto_resume_network})。",
                        flush=True,
                    )
                    time.sleep(delay)
                    resume = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": redact_sensitive_text(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
