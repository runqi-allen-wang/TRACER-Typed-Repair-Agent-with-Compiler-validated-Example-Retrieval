"""独立研究实验入口：冻结输入、随机化四条件、重复运行和成本汇总。"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import math
import os
import platform
import random
import re
import statistics
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from agent import ROOT, PROMPT_TEMPLATES, safe_name, solve_problem
from compiler import compile_candidate, diagnostics_use_sorry, find_project_root, isolate_target, patch_proof_region, run_lean_file
from diagnostics import normalize_diagnostics
from provider import OpenAICompatibleProvider, redact_sensitive_text
from proof_protocol import LEGACY_PROTOCOL_VERSION, PROOF_PROTOCOL
from retriever import Example, find_retrieval_leaks, load_examples
from leancapsule.privacy import redact_value

ARMS = {
    "A": ("A", "static"),
    "B": ("B", "static"),
    "C": ("C", "static"),
    "D": ("D", "static"),
    "C_dynamic": ("C", "diagnostic"),
    "C_failure": ("C", "diagnostic"),
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_benchmark(path):
    path = Path(path).resolve()
    manifest = read_json(path)
    if not manifest.get("version") or not manifest.get("problems"):
        raise ValueError("题库缺少版本或题目")
    ids = set()
    for problem in manifest["problems"]:
        if not re.fullmatch(r"[a-z0-9_]+", problem["id"]) or problem["id"] in ids:
            raise ValueError("题目 ID 非法或重复")
        ids.add(problem["id"])
        source = (path.parent / problem["file"]).resolve()
        if not source.is_relative_to(path.parent):
            raise ValueError("题目路径越出冻结目录")
        if source.read_text(encoding="utf-8") != problem["source_text"]:
            raise ValueError("冻结源码发生改变：" + problem["id"])
        if problem["source_text"].count("-- PROOF_START") != 1 or problem["source_text"].count("-- PROOF_END") != 1:
            raise ValueError("修复题必须有唯一局部证明区域")
    return manifest


def load_config(path):
    config = read_json(path)
    allowed = {"models", "repeats", "arms", "max_rounds", "compile_timeout", "order_seed", "examples_dir", "failure_notes"}
    if set(config) - allowed:
        raise ValueError("配置存在未知字段；不得将密钥写入配置")
    if type(config.get("repeats")) is not int or config["repeats"] < 1:
        raise ValueError("repeats 必须为正整数")
    if not config.get("arms") or len(set(config["arms"])) != len(config["arms"]) or set(config["arms"]) - ARMS.keys():
        raise ValueError("实验组非法或重复")
    if not 1 <= config.get("max_rounds", 3) <= 3 or config.get("compile_timeout", 60) <= 0:
        raise ValueError("轮数或超时预算不合法")
    if not config.get("models"):
        raise ValueError("至少配置一个模型")
    ids = set()
    for model in config["models"]:
        required = {"id", "model", "api_url", "api_key_env", "temperature", "max_tokens"}
        optional = {"input_price_per_1k", "output_price_per_1k", "pricing_note", "thinking", "reasoning_effort"}
        if not required <= model.keys() or set(model) - required - optional:
            raise ValueError("模型配置字段缺失或含不允许字段")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", model["id"]) or model["id"] in ids:
            raise ValueError("模型 ID 非法或重复")
        ids.add(model["id"])
        parsed = urlsplit(model["api_url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("研究 API 地址必须为不含凭据或查询参数的 HTTPS URL")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", model["api_key_env"]):
            raise ValueError("仅允许配置密钥环境变量的名称")
        if not model["model"].strip() or model["max_tokens"] < 1 or not 0 <= model["temperature"] <= 2:
            raise ValueError("模型名称或生成预算无效")
        for key in ("input_price_per_1k", "output_price_per_1k"):
            price = model.get(key)
            if price is not None and (not isinstance(price, (float, int)) or not math.isfinite(price) or price < 0):
                raise ValueError("价格必须非负或 null")
        if model.get("thinking") not in {None, "enabled", "disabled"} or model.get("reasoning_effort") not in {None, "low", "high", "max"}:
            raise ValueError("模型思考参数无效")
    # 一个输入框对应一个服务来源，避免同名环境变量把凭据送往另一个服务。
    key_origins = {}
    for model in config["models"]:
        origin = urlsplit(model["api_url"]).netloc
        name = model["api_key_env"]
        if name in key_origins and key_origins[name] != origin:
            raise ValueError("同一密钥变量不得用于不同 API 来源")
        key_origins[name] = origin
    if "C_failure" in config["arms"] and ("C_dynamic" not in config["arms"] or not config.get("failure_notes")):
        raise ValueError("C_failure 必须有配对 C_dynamic 和失败注释语料")
    return config


def build_plan(config, benchmark):
    tasks = [
        {"model_id": model["id"], "repeat": repeat, "arm": arm, "problem_id": problem["id"]}
        for repeat in range(1, config["repeats"] + 1)
        for model in config["models"]
        for arm in config["arms"]
        for problem in benchmark["problems"]
    ]
    random.Random(config.get("order_seed", 20260828)).shuffle(tasks)
    return tasks


def check_benchmark(path, timeout=60):
    manifest = load_benchmark(path)
    results = []
    for problem in manifest["problems"]:
        source = problem["source_text"]
        bad = source.split("-- PROOF_START")[1].split("-- PROOF_END")[0].strip()
        compiled = compile_candidate(Path(path).parent / problem["file"], source, bad, problem["theorem"], timeout=timeout)
        diagnostic = normalize_diagnostics(compiled.diagnostics, returncode=compiled.returncode, timed_out=compiled.timed_out)
        if compiled.ok or compiled.returncode is None or diagnostic["category"] in {"syntax", "timeout"}:
            raise ValueError("初始候选未形成有效修复任务：" + problem["id"] + " / " + diagnostic["summary"])
        results.append({"problem_id": problem["id"], "compile_ok": compiled.ok, "diagnostic": diagnostic,
                        "raw_diagnostics": compiled.diagnostics, "compile_elapsed_ms": compiled.elapsed_ms})
    return results


def trial_path(out, task):
    return out / "trials" / task["model_id"] / str(task["repeat"]) / task["arm"] / task["problem_id"]


def valid_protocol_record(row):
    """验证新协议的独立判定字段，不能将旧口径或截断记录混入新批次。"""
    if row.get("proof_protocol") != PROOF_PROTOCOL:
        return False
    finish = row.get("provider_response", {}).get("finish_reason")
    expected = {"length": "truncated", "stop": "complete", "incomplete": "incomplete"}.get(finish, "unknown")
    if row.get("generation_status") != expected:
        return False
    if expected == "incomplete" and (row.get("compile_ok") or row.get("compile_invoked") or
            row.get("diagnostic", {}).get("category") not in {"generation_incomplete", "sensitive_candidate"}):
        return False
    if expected == "truncated" and (row.get("compile_ok") or row.get("compile_invoked") or
            row.get("diagnostic", {}).get("category") not in {"generation_truncated", "sensitive_candidate"}):
        return False
    if not row.get("compile_invoked"):
        return not row.get("compile_ok") and all(row.get(k) is None for k in ("kernel_pass", "compile_has_warnings", "warning_free"))
    return (type(row.get("kernel_pass")) is bool and row["kernel_pass"] == row.get("compile_ok")
            and type(row.get("compile_has_warnings")) is bool
            and row["compile_has_warnings"] == bool(row.get("diagnostic", {}).get("warning_count"))
            and type(row.get("warning_free")) is bool
            and row["warning_free"] == (row["kernel_pass"] and not row["compile_has_warnings"]))


class PricedProvider:
    """每个模型独立携带价格配置，不修改全局环境变量。"""

    def __init__(self, provider, model, budget=None):
        self.provider, self.model = provider, model
        self.name = provider.name
        self.budget = budget

    def generate(self, prompt):
        if self.budget is not None:
            self.budget.reserve(prompt, self.model)
        return self.provider.generate(prompt)

    def metadata(self):
        return {**self.provider.metadata(), **{key: self.model.get(key) for key in
                ("input_price_per_1k", "output_price_per_1k", "pricing_note")}}


class CallBudget:
    """单次 HTTP 尝试并按保守输入/输出额度预留；不是服务方账单硬上限。"""

    def __init__(self, max_calls, max_reserved_usd):
        if max_calls < 1 or not math.isfinite(max_reserved_usd) or max_reserved_usd <= 0:
            raise ValueError("调用次数和预算必须为正数")
        self.max_calls, self.max_reserved_usd = max_calls, max_reserved_usd
        self.calls, self.reserved_usd = 0, 0.0
        self.ledger_path = None

    def reserve(self, prompt, model):
        prices = [model.get(k) for k in ("input_price_per_1k", "output_price_per_1k")]
        if any(price is None for price in prices):
            raise ValueError("预算模式要求明确的保守价格")
        # 按 UTF-8 字节近似输入 token 上界，并给消息封装预留 1024；不依赖摘要。
        reservation = ((len(prompt.encode("utf-8")) + 1024) * prices[0] + model["max_tokens"] * prices[1]) / 1000
        if self.calls >= self.max_calls or self.reserved_usd + reservation > self.max_reserved_usd:
            raise RuntimeError("已达到用户批准的调用次数或预留费用预算；停止，保留未完成批次")
        # 请求结果不明也不退回预算，不自动重试可能已经计费的请求。
        self.calls += 1
        self.reserved_usd += reservation
        if self.ledger_path is not None:
            write_json(self.ledger_path, self.snapshot())

    def snapshot(self):
        return {"attempted_calls": self.calls, "max_calls": self.max_calls,
                "reserved_usd": self.reserved_usd, "max_reserved_usd": self.max_reserved_usd,
                "scope": "保守预留，非实际账单；服务方额外费用或价格变化不受本地控制"}


def prompt_api_keys(config):
    if not sys.stdin.isatty():
        raise ValueError("隐藏密钥输入需要本地交互终端；拒绝退回明文回显或从管道读入")
    keys = {}
    for model in config["models"]:
        name = model["api_key_env"]
        if name not in keys:
            key = getpass.getpass(f"{urlsplit(model['api_url']).hostname} API key（不会回显或保存）：").strip()
            if not key:
                raise ValueError("API key 不能为空")
            keys[name] = key
    print("已在进程内读取密钥；不显示长度、后缀或内容。", flush=True)
    return keys


def run_matrix(config, benchmark_path, out, api_keys=None, budget=None):
    benchmark = load_benchmark(benchmark_path)
    template_names = set(PROMPT_TEMPLATES.values()) | {"proof_contract.txt"}
    prompt_snapshot = {name: (ROOT / "prompts" / name).read_text(encoding="utf-8") for name in sorted(template_names)}
    examples_dir = (ROOT / config.get("examples_dir", "examples")).resolve()
    examples = load_examples(examples_dir)
    if not examples:
        raise ValueError("检索语料为空")
    leaks = find_retrieval_leaks([(p["id"], p["source_text"]) for p in benchmark["problems"]], examples)
    if leaks:
        raise ValueError("冻结修复集与示例声明重合：" + json.dumps(leaks, ensure_ascii=False))
    notes = {}
    if config.get("failure_notes"):
        corpus = read_json(ROOT / config["failure_notes"])
        available = {example.path: example.text for example in examples}
        for item in corpus["examples"]:
            if available.get(item["path"]) != item["source_text"]:
                raise ValueError("失败案例与固定检索示例不匹配")
            notes[item["path"]] = item["failure_context"]
        if not notes:
            raise ValueError("失败案例语料为空")
        if find_retrieval_leaks([(p["id"], p["source_text"]) for p in benchmark["problems"]],
                                [Example(name, (), text) for name, text in notes.items()]):
            raise ValueError("失败上下文包含冻结题目声明")
    # 配置缺失在创建运行目录之前报告；不会归档或清除历史 pilot。
    providers = {}
    for model in config["models"]:
        if "REPLACE" in model["model"] or "实际模型" in model["model"]:
            raise ValueError("请先替换配置中的示例模型名称")
        key = (api_keys or {}).get(model["api_key_env"], os.environ.get(model["api_key_env"], "")).strip()
        if not key:
            raise ValueError("未设置密钥环境变量：" + model["api_key_env"])
        # 冻结矩阵只使用 Chat 协议；不继承用户终端中其他实验的协议或推理参数。
        providers[model["id"]] = PricedProvider(OpenAICompatibleProvider(
            url=model["api_url"], api_key=key, model=model["model"], wire_api="chat_completions",
            temperature=model["temperature"], max_tokens=model["max_tokens"],
            thinking=model.get("thinking"), reasoning_effort=model.get("reasoning_effort"),
            max_attempts=1, request_timeout=180), model, budget)
    initial = {row["problem_id"]: row for row in check_benchmark(benchmark_path, config.get("compile_timeout", 60))}
    out.mkdir(parents=True, exist_ok=False)
    if budget is not None:
        budget.ledger_path = out / "budget.json"
        write_json(budget.ledger_path, budget.snapshot())
    tasks = build_plan(config, benchmark)
    experiment_id = "research-" + str(uuid.uuid4())
    write_json(out / "plan.json", {"experiment_id": experiment_id, "config": config,
               "proof_protocol": dict(PROOF_PROTOCOL), "prompt_templates": prompt_snapshot,
               "benchmark_version": benchmark["version"], "tasks": tasks, "status": "running",
               "platform": platform.system(), "python": platform.python_version(),
               "approved_budget": budget.snapshot() if budget else None,
               "lean_toolchain": (ROOT / "lean-toolchain").read_text().strip()})
    write_json(out / "benchmark.json", benchmark)
    write_json(out / "examples.json", [{"path": ex.path, "tags": ex.tags, "text": ex.text} for ex in examples])
    # 后续读取本批次快照，避免实验中编辑 examples 改变某一组的语料。
    examples_dir = out / "corpus"
    examples_dir.mkdir()
    for example in examples:
        (examples_dir / example.path).write_text(example.text, encoding="utf-8")
    write_json(out / "failure_notes.json", notes)
    write_json(out / "initial_compilation.json", redact_value(initial))
    with (out / "manual_review.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["experiment_id", "model_id", "repeat", "arm", "problem_id", "kernel_pass", "inappropriate_assumption", "leakage_risk", "reviewer_note"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({"experiment_id": experiment_id, **task} for task in tasks)
    problems = {p["id"]: p for p in benchmark["problems"]}
    completed = []
    for index, task in enumerate(tasks, 1):
        dest = trial_path(out, task)
        dest.mkdir(parents=True)
        problem = problems[task["problem_id"]]
        source_path = Path(benchmark_path).parent / problem["file"]
        condition, strategy = ARMS[task["arm"]]
        started = time.perf_counter()
        result = {"compile_ok": False}
        error = None
        independent_ok = None
        try:
            if source_path.read_text(encoding="utf-8") != problem["source_text"]:
                raise ValueError("运行中源码已改变")
            result = solve_problem(
                source_path, problem["theorem"], condition, providers[task["model_id"]],
                config.get("max_rounds", 3), config.get("compile_timeout", 60), examples_dir,
                dest / "unused.sqlite3", dest / "solutions", dest / "runs.jsonl",
                benchmark_id=problem["id"], tags=problem["tags"], difficulty=problem["difficulty"],
                experiment_id=experiment_id, retrieval_strategy=strategy, use_cache=False,
                record_prompt=True, initial_feedback=initial[problem["id"]]["diagnostic"],
                initial_diagnostics=initial[problem["id"]]["raw_diagnostics"],
                failure_notes=notes if task["arm"] == "C_failure" else None,
                prompt_templates=prompt_snapshot)
            if result["compile_ok"]:
                saved = list((dest / "solutions" / condition).glob("*.lean"))
                if len(saved) != 1:
                    raise ValueError("缺少唯一成功证明")
                check = run_lean_file(saved[0], config.get("compile_timeout", 60), find_project_root(source_path))
                if not check.ok or diagnostics_use_sorry(check.diagnostics):
                    raise ValueError("成功证明独立复编译失败")
                independent_ok = True
            error = result.get("provider_error")
            task_log = dest / "runs.jsonl"
            if task_log.exists():
                recorded = [json.loads(line) for line in task_log.read_text(encoding="utf-8").splitlines()]
                if any(row.get("compile_timed_out") or row.get("diagnostic", {}).get("category") == "patch_error"
                       or (row.get("compile_invoked") and row.get("compile_returncode") is None) for row in recorded):
                    error = "编译超时或工具链/补丁错误；该任务不作为纯证明失败"
        except Exception as exc:
            error = redact_sensitive_text(exc)
        item = {**task, "experiment_id": experiment_id, "compile_ok": bool(result["compile_ok"]) and error is None,
                "independent_compile_ok": independent_ok,
                "error": error, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        write_json(dest / "trial.json", redact_value(item))
        completed.append(item)
        print(f"{index}/{len(tasks)} {task['model_id']} r{task['repeat']} {task['arm']} {task['problem_id']}: " +
              ("ERROR" if error else "PASS" if item["compile_ok"] else "FAIL"), flush=True)
        # 基础设施错误不是数学失败；停止付费调用，保留完整的未完成批次证据。
        if error:
            break
    write_json(out / "completion.json", {"planned": len(tasks), "completed": len(completed),
               "complete": len(completed) == len(tasks), "infrastructure_errors": sum(bool(x["error"]) for x in completed),
               "budget": budget.snapshot() if budget else None})
    return not any(x["error"] for x in completed) and len(completed) == len(tasks)


def load_trials(out):
    plan = read_json(out / "plan.json")
    trials, errors = [], []
    protocol = plan.get("proof_protocol")
    if protocol is not None and protocol != PROOF_PROTOCOL:
        errors.append("不支持的证明协议版本；拒绝猜测验收口径")
    benchmark = read_json(out / "benchmark.json")
    problems = {p["id"]: p for p in benchmark["problems"]}
    expected_tasks = build_plan(plan["config"], benchmark)
    if expected_tasks != plan["tasks"] or plan["benchmark_version"] != benchmark["version"]:
        errors.append("实验矩阵或题库版本与冻结计划不符")
    global_runs = set()
    for task in plan["tasks"]:
        directory = trial_path(out, task)
        if not (directory / "trial.json").exists():
            errors.append("未完成：" + "/".join(str(v) for v in task.values()))
            continue
        trial = read_json(directory / "trial.json")
        rows = [json.loads(line) for line in (directory / "runs.jsonl").read_text(encoding="utf-8").splitlines()] if (directory / "runs.jsonl").exists() else []
        limit = plan["config"].get("max_rounds", 3)
        valid = (trial.get("experiment_id") == plan["experiment_id"] and all(trial.get(k) == v for k, v in task.items())
                 and rows and len(rows) <= limit and [r["round"] for r in rows] == list(range(1, len(rows) + 1))
                 and len({r["run_id"] for r in rows}) == 1
                 and not any(r["compile_ok"] for r in rows[:-1])
                 and (rows[-1]["compile_ok"] or len(rows) == limit)
                 and bool(trial["compile_ok"]) == bool(rows[-1]["compile_ok"])
                 and all(r.get("experiment_id") == plan["experiment_id"] and r["problem_id"] == task["problem_id"]
                         and r["condition"] == ARMS[task["arm"]][0] and not r["cache_hit"]
                         and not r.get("provider_error") and r["provider"] == "openai_compatible"
                         and not r.get("compile_timed_out")
                         and not (r.get("compile_invoked") and r.get("compile_returncode") is None)
                         and r.get("retrieval_strategy") == ARMS[task["arm"]][1] for r in rows))
        model = next(m for m in plan["config"]["models"] if m["id"] == task["model_id"])
        valid = valid and all(all(r["provider_config"].get(k) == model[k] for k in ("model", "temperature", "max_tokens"))
                              and r["provider_config"].get("url") == model["api_url"] for r in rows)
        valid = valid and all(all(r["provider_config"].get(k) == model.get(k) for k in
                                  ("input_price_per_1k", "output_price_per_1k", "thinking", "reasoning_effort")) for r in rows)
        if protocol is not None:
            valid = valid and all(valid_protocol_record(r) for r in rows)
        else:
            # 没有协议字段的历史批次仍按原始 compile_ok 汇总，不套用新版口径。
            valid = valid and all(r.get("proof_protocol") is None for r in rows)
        if rows:
            if rows[0]["run_id"] in global_runs:
                valid = False
            global_runs.add(rows[0]["run_id"])
        if trial["compile_ok"] and rows:
            problem = problems[task["problem_id"]]
            condition = ARMS[task["arm"]][0]
            solutions = list((directory / "solutions" / condition).glob("*.lean"))
            patched = patch_proof_region(problem["source_text"], rows[-1]["candidate"], problem["theorem"], "-- PROOF_START", "-- PROOF_END")
            expected = isolate_target(problem["source_text"], patched, problem["theorem"])
            if len(solutions) != 1 or solutions[0].read_text(encoding="utf-8") != expected:
                errors.append("成功文件缺失或与候选重建文本不一致：" + str(directory.relative_to(out)))
            if trial.get("independent_compile_ok") is not True:
                errors.append("缺少独立重编译通过记录：" + str(directory.relative_to(out)))
            valid = (valid and trial.get("independent_compile_ok") is True and len(solutions) == 1
                     and solutions[0].read_text(encoding="utf-8") == expected)
        if not valid or trial.get("error"):
            errors.append("轨迹无效：" + str(directory.relative_to(out)))
        trials.append((trial, rows))
    return plan, trials, errors


def summarize(out, allow_partial=False):
    plan, trials, errors = load_trials(out)
    if errors and not allow_partial:
        raise ValueError("正式汇总门禁拒绝不完整或错误批次：" + "; ".join(errors[:5]))
    groups = defaultdict(list)
    for trial, rows in trials:
        groups[(trial["model_id"], trial["arm"])].append((trial, rows))
    summary = []
    protocol_version = plan.get("proof_protocol", {}).get("version", LEGACY_PROTOCOL_VERSION)
    for (model, arm), items in sorted(groups.items()):
        totals = defaultdict(int)
        costs, token_totals, repeat_rates = [], [], defaultdict(list)
        failure_categories = defaultdict(int)
        truncated_calls = empty_calls = warning_successes = warning_free_successes = 0
        prompt_tokens, completion_tokens, generation_ms, compile_ms = [], [], [], []
        for trial, rows in items:
            totals["success"] += int(trial["compile_ok"])
            totals["first"] += int(bool(rows) and rows[0]["compile_ok"])
            totals["rounds"] += len(rows)
            totals["infrastructure_errors"] += int(bool(trial.get("error")))
            if trial["compile_ok"] and rows:
                warning_successes += int(rows[-1].get("compile_has_warnings") is True)
                warning_free_successes += int(rows[-1].get("warning_free") is True)
            repeat_rates[trial["repeat"]].append(int(trial["compile_ok"]))
            for row in rows:
                truncated_calls += int(row.get("provider_response", {}).get("finish_reason") == "length")
                empty_calls += int(not row.get("candidate", "").strip())
                if not row["compile_ok"]:
                    failure_categories[row.get("diagnostic", {}).get("category", "unclassified")] += 1
                costs.append(row.get("estimated_cost_usd"))
                token_totals.append(row.get("usage", {}).get("total_tokens"))
                prompt_tokens.append(row.get("usage", {}).get("prompt_tokens", row.get("usage", {}).get("input_tokens")))
                completion_tokens.append(row.get("usage", {}).get("completion_tokens", row.get("usage", {}).get("output_tokens")))
                generation_ms.append(row.get("generation_elapsed_ms", 0))
                compile_ms.append(row.get("compile_elapsed_ms", 0))
        rates = [statistics.mean(v) for v in repeat_rates.values()]
        summary.append({"model": model, "arm": arm, "tasks": len(items), **totals,
            "protocol_version": protocol_version,
            "generation_truncated_calls": truncated_calls, "empty_candidate_calls": empty_calls,
            "success_with_warnings": warning_successes if plan.get("proof_protocol") == PROOF_PROTOCOL else None,
            "warning_free_success": warning_free_successes if plan.get("proof_protocol") == PROOF_PROTOCOL else None,
            "failed_attempt_categories": dict(failure_categories),
            "pass_at_1_rate": totals["first"] / len(items),
            "pass_at_3_rate": totals["success"] / len(items) if plan["config"].get("max_rounds", 3) == 3 else None,
            "success_within_budget_rate": totals["success"] / len(items),
            "repeat_mean": statistics.mean(rates), "repeat_sd": statistics.stdev(rates) if len(rates) > 1 else None,
            "avg_rounds": totals["rounds"] / len(items),
            "avg_wall_ms": statistics.mean(t["elapsed_ms"] for t, _ in items),
            "avg_generation_ms": sum(generation_ms) / len(items), "avg_compile_ms": sum(compile_ms) / len(items),
            "avg_prompt_tokens": sum(prompt_tokens) / len(items) if prompt_tokens and all(isinstance(t, int) for t in prompt_tokens) else None,
            "avg_completion_tokens": sum(completion_tokens) / len(items) if completion_tokens and all(isinstance(t, int) for t in completion_tokens) else None,
            "total_tokens": sum(token_totals) if token_totals and all(isinstance(t, int) for t in token_totals) else None,
            "known_estimated_cost_usd": sum(c for c in costs if c is not None),
            "missing_cost_records": sum(c is None for c in costs),
            "total_estimated_cost_usd": sum(costs) if costs and all(c is not None for c in costs) else None})
    review_path = out / "manual_review.csv"
    reviewed = set()
    if review_path.exists():
        with review_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("experiment_id") == plan["experiment_id"] and row.get("kernel_pass") == "yes" and row.get("inappropriate_assumption") == "no" and row.get("leakage_risk") == "no" and row.get("reviewer_note", "").strip():
                    reviewed.add((row["model_id"], row["repeat"], row["arm"], row["problem_id"]))
    successes = {(t["model_id"], str(t["repeat"]), t["arm"], t["problem_id"]) for t, _ in trials if t["compile_ok"]}
    design_complete = (len(plan["config"]["models"]) >= 2 and plan["config"]["repeats"] >= 3
                       and plan["config"].get("max_rounds", 3) == 3
                       and {"A", "B", "C", "D"} <= set(plan["config"]["arms"]))
    paired = []
    lookup = {(t["model_id"], t["repeat"], t["problem_id"], t["arm"]): (t, rows) for t, rows in trials}
    comparisons = [("B", "A"), ("D", "A"), ("C", "B"), ("C", "D"), ("C_dynamic", "C"), ("C_failure", "C_dynamic")]
    for model in plan["config"]["models"]:
        for treatment, baseline in comparisons:
            differences = []
            for key, (trial, rows) in lookup.items():
                if key[0] != model["id"] or key[3] != treatment:
                    continue
                other = lookup.get((*key[:3], baseline))
                if other:
                    differences.append((int(trial["compile_ok"]) - int(other[0]["compile_ok"]), len(rows) - len(other[1])))
            if differences:
                paired.append({"model": model["id"], "comparison": treatment + " - " + baseline,
                               "matched_pairs": len(differences),
                               "mean_success_delta": statistics.mean(d[0] for d in differences),
                               "mean_rounds_delta": statistics.mean(d[1] for d in differences),
                               "interpretation": "描述性配对差异，不是显著性检验"})
    report = {"experiment_id": plan["experiment_id"], "trajectory_valid": not errors,
              "protocol_version": protocol_version,
              "metric_definition": ("完整生成且 Lean 验证通过；普通警告另记，未完成证明拒绝。" if plan.get("proof_protocol") == PROOF_PROTOCOL
                                    else "历史严格警告口径：保留原始 compile_ok，不按新协议改判。"),
              "full_research_design": design_complete,
              "manual_review_complete": successes <= reviewed,
              "release_ready": design_complete and not errors and bool(successes) and successes <= reviewed,
              "errors": errors, "summary": summary,
              "paired_comparisons": paired,
              "scope": "条件内重复成功率；非独立题目的重复不能当成新题扩大样本量。价格估算不是账单。"}
    write_json(out / "summary.json", report)
    if summary:
        with (out / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, default=ROOT / "experiments/research.example.json")
        command.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks/repair24/manifest.json")
        if name == "run":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--api-key-prompt", action="store_true")
            command.add_argument("--max-calls", type=int, required=True, help="用户批准的 HTTP 调用上限；不自动重试")
            command.add_argument("--max-reserved-usd", type=float, required=True, help="保守费用预留上限，不是实际账单")
    check = sub.add_parser("check-benchmark")
    check.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks/repair24/manifest.json")
    check.add_argument("--timeout", type=float, default=60)
    report = sub.add_parser("report")
    report.add_argument("--run", type=Path, required=True)
    report.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        if args.command in {"plan", "run"}:
            config = load_config(args.config)
            benchmark = load_benchmark(args.benchmark)
            if args.command == "run":
                budget = CallBudget(args.max_calls, args.max_reserved_usd)
                if args.out.exists():
                    raise ValueError("输出目录已存在，不覆盖旧研究")
                keys = prompt_api_keys(config) if args.api_key_prompt else None
                return 0 if run_matrix(config, args.benchmark, args.out.resolve(), keys, budget) else 1
            tasks = build_plan(config, benchmark)
            result = {"benchmark": benchmark["version"], "models": len(config["models"]),
                      "proof_protocol": dict(PROOF_PROTOCOL),
                      "repeats": config["repeats"], "arms": config["arms"], "tasks": len(tasks),
                      "max_generations": len(tasks) * config.get("max_rounds", 3),
                      "network_calls": 0, "warning": "plan 不调用 API；示例配置需填真实模型。"}
        elif args.command == "check-benchmark":
            rows = check_benchmark(args.benchmark, args.timeout)
            result = {"ok": True, "initial_failures": len(rows), "reference_proofs": "仅由测试套件验证"}
        else:
            result = summarize(args.run.resolve(), args.allow_partial)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": redact_sensitive_text(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
