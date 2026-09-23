"""TRACER 因果反馈实验：冻结首轮失败后执行可审计的反馈干预。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import random
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from adaptive_router import route_feedback
from agent import ROOT, estimate_cost
from compiler import (
    candidate_safety_violation, compile_candidate, diagnostics_use_sorry,
    declaration_scope, find_project_root, run_lean_file,
)
from compiler_feedback import ALLOWED_CATEGORIES, build_feedback_record
from diagnostics import normalize_diagnostics
from error_state_graph import build_error_state_graph
from feedback_study import apply_direct_model_config
from provider import Generation, OpenAICompatibleProvider, clean_candidate, generation_finish_reason, redact_sensitive_text
from research import CallBudget, PricedProvider, load_benchmark, load_config as load_research_config, write_json
from retriever import load_examples, retrieve
from leancapsule.privacy import redact_text


PROTOCOL_VERSION = "tracer-causal-feedback-v1"
PREREGISTRATION_VERSION = "tracer-causal-preregistration-v1"
PROMPT_SOURCE_CHARS = 12000
ARMS = (
    "content_free_retry",
    "true_raw",
    "true_normalized",
    "true_structured",
    "irrelevant_matched",
    "counterfactual",
    "retrieval_only",
    "adaptive",
)
INFRASTRUCTURE = {"timeout", "provider_error", "compiler_unavailable", "patch_error", "candidate_security"}


class CandidateOutcomeError(ValueError):
    """模型返回完整性或候选策略失败；这是观测结果，不是传输故障。"""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_protocol(path: Path = ROOT / "experiments/causal_feedback.protocol.json") -> dict[str, Any]:
    protocol = read_json(path)
    if protocol.get("version") != PROTOCOL_VERSION:
        raise ValueError("因果反馈协议版本不匹配")
    if protocol.get("arms") != list(ARMS):
        raise ValueError("因果反馈干预组或顺序发生漂移")
    if protocol.get("primary_estimand", {}).get("population") != "eligible_first_failures":
        raise ValueError("主估计对象必须限定为冻结首轮失败")
    if protocol.get("primary_estimand", {}).get("primary_contrast") != "true_structured - content_free_retry":
        raise ValueError("主对比必须唯一冻结为 structured 对 content-free retry")
    prompt_view = protocol.get("prompt_view", {})
    if prompt_view.get("maximum_source_characters") != PROMPT_SOURCE_CHARS:
        raise ValueError("提示源码上下文预算发生漂移")
    if "完整冻结首轮候选" not in str(prompt_view.get("first_candidate_policy", "")):
        raise ValueError("协议必须冻结完整首轮候选")
    return protocol


def validate_config(path: Path) -> dict[str, Any]:
    """复用既有模型门禁，并冻结因果实验专属控制。"""

    import tempfile

    config = read_json(path)
    allowed = {
        "models", "repeats", "arms", "compile_timeout", "order_seed",
        "examples_dir", "branch_attempts", "benchmark_splits",
    }
    if set(config) - allowed:
        raise ValueError("因果反馈配置存在未知字段；不得将密钥写入配置")
    if config.get("arms") != list(ARMS):
        raise ValueError("配置必须按冻结顺序包含全部因果反馈干预")
    if config.get("branch_attempts") != 1:
        raise ValueError("v1 主估计只允许每个分支一次修复生成")
    with tempfile.TemporaryDirectory() as directory:
        bridge = Path(directory) / "config.json"
        bridge.write_text(json.dumps({
            "models": config.get("models"),
            "repeats": config.get("repeats"),
            "arms": ["B"],
            "max_rounds": 1,
            "compile_timeout": config.get("compile_timeout"),
            "order_seed": config.get("order_seed"),
            "examples_dir": config.get("examples_dir", "examples"),
        }, ensure_ascii=False), encoding="utf-8")
        checked = load_research_config(bridge)
    checked.pop("max_rounds")
    checked.pop("arms")
    checked["arms"] = list(ARMS)
    checked["branch_attempts"] = 1
    splits = config.get("benchmark_splits")
    if splits is not None:
        allowed_splits = {"development", "validation", "test"}
        if (
            not isinstance(splits, list) or not splits or len(splits) != len(set(splits))
            or any(split not in allowed_splits for split in splits)
        ):
            raise ValueError("benchmark_splits 必须是互不重复的项目级标准划分")
        checked["benchmark_splits"] = splits
    return checked


def seed_key(seed: dict[str, Any]) -> str:
    return f"{seed['model_id']}/r{seed['repeat']}/{seed['problem_id']}"


def build_plan(config: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    selected = [
        problem for problem in benchmark["problems"]
        if not config.get("benchmark_splits") or problem.get("split") in config["benchmark_splits"]
    ]
    if not selected:
        raise ValueError("项目级划分筛选后没有实验题目")
    if config.get("benchmark_splits") and any(not problem.get("project_id") for problem in selected):
        raise ValueError("项目级因果实验要求每题记录 project_id")
    seeds = [
        {
            "model_id": model["id"], "repeat": repeat, "problem_id": problem["id"],
            "project_id": problem.get("project_id"), "split": problem.get("split"),
        }
        for repeat in range(1, config["repeats"] + 1)
        for model in config["models"]
        for problem in selected
    ]
    random.Random(config.get("order_seed", 20260913)).shuffle(seeds)
    return {
        "seed_tasks": seeds,
        "maximum_branch_tasks": len(seeds) * len(ARMS),
        "maximum_generations": len(seeds) * (1 + len(ARMS)),
        "branch_tasks_depend_on": "eligible_first_failures",
        "selected_splits": config.get("benchmark_splits"),
        "selected_projects": sorted({problem.get("project_id") for problem in selected if problem.get("project_id")}),
    }


def resolve_compile_environments(
    benchmark: dict[str, Any], project_root: Path | None,
) -> tuple[dict[str, Path], str | dict[str, str], str]:
    """解析冻结编译环境；v2 必须逐项目绑定，v1 保持单项目兼容。"""

    if benchmark.get("version") != "tracer-real-v2":
        active_root = project_root.resolve() if project_root is not None else ROOT
        if project_root is not None and not (
            (active_root / "lakefile.toml").is_file() or (active_root / "lakefile.lean").is_file()
        ):
            raise ValueError("显式编译项目根缺少 lakefile")
        toolchain_path = active_root / "lean-toolchain"
        if not toolchain_path.is_file():
            raise ValueError("编译项目根缺少 lean-toolchain")
        return {}, toolchain_path.read_text(encoding="utf-8").strip(), (
            "explicit_lake_project" if project_root is not None else "benchmark_project"
        )

    if project_root is not None:
        raise ValueError("TRACER-REAL v2 必须使用 manifest 中逐项目冻结的编译环境；禁止统一覆盖")
    from tracer_real_v2 import (
        SHARE_GATE_AMENDMENT_PATH, apply_share_gate_amendment,
        read_json as read_v2_json, validate_v2_benchmark,
    )

    contract = apply_share_gate_amendment(
        read_v2_json(ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json"),
        read_v2_json(SHARE_GATE_AMENDMENT_PATH),
    )
    validate_v2_benchmark(benchmark, contract)
    roots: dict[str, Path] = {}
    toolchains: dict[str, str] = {}
    for row in benchmark["project_environments"]:
        root = (ROOT / row["project_root"]).resolve()
        try:
            root.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ValueError("v2 项目编译根逃逸仓库") from exc
        if not ((root / "lakefile.toml").is_file() or (root / "lakefile.lean").is_file()):
            raise ValueError("v2 项目编译根缺少 lakefile：" + row["project_id"])
        toolchain_path = root / "lean-toolchain"
        if not toolchain_path.is_file():
            raise ValueError("v2 项目编译根缺少 lean-toolchain：" + row["project_id"])
        actual_toolchain = toolchain_path.read_text(encoding="utf-8").strip()
        if actual_toolchain != row["lean_toolchain"]:
            raise ValueError("v2 项目 lean-toolchain 与冻结记录不一致：" + row["project_id"])
        roots[row["project_id"]] = root
        toolchains[row["project_id"]] = actual_toolchain
    return roots, toolchains, "manifest_project_lake_roots"


def validate_preregistration(
    path: Path, config: dict[str, Any], benchmark: dict[str, Any],
) -> dict[str, Any]:
    """在任何 provider 调用前核对机器可读预注册与冻结运行对象。"""

    prereg = read_json(path)
    validate_preregistration_record(prereg, config, benchmark)
    return prereg


def validate_preregistration_record(
    prereg: dict[str, Any], config: dict[str, Any], benchmark: dict[str, Any],
) -> None:
    """核对已经加载的预注册；供 CLI 与直接调用共享。"""

    required = {
        "version", "status", "planned_experiment_id", "registered_at_utc",
        "registration_medium", "benchmark", "models", "design", "primary_analysis",
        "secondary_analyses", "stopping_rule", "claim_gate",
    }
    if set(prereg) != required or prereg.get("version") != PREREGISTRATION_VERSION:
        raise ValueError("因果反馈预注册版本或顶层字段不匹配")
    if prereg.get("status") != "frozen-before-provider-run":
        raise ValueError("预注册必须在 provider 运行前冻结")
    if not re_fullmatch_identifier(prereg.get("planned_experiment_id", "")):
        raise ValueError("预注册实验 ID 非法")
    benchmark_record = prereg["benchmark"]
    if benchmark_record.get("version") != benchmark.get("version"):
        raise ValueError("预注册题库版本与运行题库不一致")
    if benchmark_record.get("split_policy") != benchmark.get("split_policy"):
        raise ValueError("预注册项目划分策略与运行题库不一致")
    projects = sorted(
        (row["project_id"], row["split"], row["tasks"])
        for row in benchmark.get("projects", [])
    )
    frozen_projects = sorted(
        (row["project_id"], row["split"], row["tasks"])
        for row in benchmark_record.get("projects", [])
    )
    if projects != frozen_projects:
        raise ValueError("预注册的项目与题目数量发生漂移")
    if benchmark.get("version") == "tracer-real-v2":
        # v2 采用两阶段预注册：先冻结纳入规则，再冻结满足门槛的精确清单。
        from tracer_real_v2 import (
            SHARE_GATE_AMENDMENT_PATH, apply_share_gate_amendment,
            read_json as read_v2_json, validate_v2_benchmark,
        )

        contract = apply_share_gate_amendment(
            read_v2_json(ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json"),
            read_v2_json(SHARE_GATE_AMENDMENT_PATH),
        )
        validate_v2_benchmark(benchmark, contract)
    frozen_models = prereg["models"]
    model_fields = (
        "id", "model", "api_url", "temperature", "max_tokens", "thinking", "reasoning_effort",
    )
    active_models = [{field: model.get(field) for field in model_fields} for model in config["models"]]
    if frozen_models != active_models:
        raise ValueError("预注册模型或生成参数与运行配置发生漂移")
    design = prereg["design"]
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "arms": list(ARMS),
        "repeats": config["repeats"],
        "branch_attempts": config["branch_attempts"],
        "benchmark_splits": config.get("benchmark_splits"),
        "order_seed": config.get("order_seed", 20260913),
        "compile_timeout": config["compile_timeout"],
        "prompt_files": ["prompts/causal_seed.txt", "prompts/causal_branch.txt", "prompts/proof_contract.txt"],
    }
    if design != expected:
        raise ValueError("预注册设计与运行配置发生漂移")
    if prereg["primary_analysis"].get("contrast") != "true_structured - content_free_retry":
        raise ValueError("v1 主对比必须唯一冻结为 structured 对 content-free retry")
    expected_population = (
        "eligible_first_failures_on_preregistered_v2_test_projects"
        if benchmark.get("version") == "tracer-real-v2"
        else "eligible_first_failures_on_test_split"
    )
    if prereg["primary_analysis"].get("population") != expected_population:
        raise ValueError("主分析人群必须是预注册测试项目上的合格首轮失败")


def re_fullmatch_identifier(value: str) -> bool:
    return bool(value and all(character.isalnum() or character in "-_" for character in value))


def _providers(config: dict[str, Any], api_keys: dict[str, str] | None, budget: CallBudget | None) -> dict[str, Any]:
    providers = {}
    for model in config["models"]:
        if "REPLACE" in model["model"] or "实际模型" in model["model"]:
            raise ValueError("请先替换因果反馈示例配置中的模型名称")
        key = (api_keys or {}).get(model["api_key_env"], os.environ.get(model["api_key_env"], "")).strip()
        if not key:
            raise ValueError("未设置密钥环境变量：" + model["api_key_env"])
        base = OpenAICompatibleProvider(
            url=model["api_url"], api_key=key, model=model["model"], wire_api="chat_completions",
            temperature=model["temperature"], max_tokens=model["max_tokens"],
            thinking=model.get("thinking"), reasoning_effort=model.get("reasoning_effort"),
            max_attempts=1, request_timeout=180,
        )
        providers[model["id"]] = PricedProvider(base, model, budget)
    return providers


def _generate(provider: Any, prompt: str) -> tuple[str, Generation, str]:
    generation = provider.generate(prompt)
    candidate = clean_candidate(generation.candidate)
    finish = generation_finish_reason(generation.raw)
    if finish != "stop":
        raise CandidateOutcomeError("generation_incomplete", "生成未以完整 stop 结束，不能进入 Lean 编译")
    violation = candidate_safety_violation(candidate)
    if not candidate or violation:
        raise CandidateOutcomeError("candidate_security" if violation else "empty_candidate", violation or "模型未返回候选证明")
    return candidate, generation, finish


def _prompt_source(problem: dict[str, Any], limit: int = PROMPT_SOURCE_CHARS) -> str:
    """为长文件保留 imports、目标前局部上下文和完整目标声明。"""

    source = str(problem["source_text"])
    if len(source) <= limit:
        return source
    start, end = declaration_scope(source, problem["theorem"])
    target = source[start:end].strip()
    imports = "\n".join(
        line for line in source[:start].splitlines() if line.lstrip().startswith("import ")
    )
    separator = "\n\n-- 省略与目标无关的较早上下文\n\n"
    head = imports + separator
    reserved = len(head) + len(target) + 2
    if reserved > limit:
        raise ValueError("目标声明与 imports 超过冻结提示上下文预算")
    prefix = source[:start].rstrip()
    tail = prefix[-(limit - reserved):] if prefix else ""
    if len(tail) < len(prefix) and "\n" in tail:
        tail = tail.split("\n", 1)[1]
    view = head + tail + ("\n\n" if tail else "") + target
    if len(view) > limit or target not in view:
        raise ValueError("无法构造包含完整目标声明的冻结提示视图")
    return view


def _seed_prompt(problem: dict[str, Any]) -> str:
    template = (ROOT / "prompts/causal_seed.txt").read_text(encoding="utf-8")
    contract = (ROOT / "prompts/proof_contract.txt").read_text(encoding="utf-8")
    return template.format(theorem=_prompt_source(problem)) + "\n" + contract.format(
        start_marker="-- PROOF_START", end_marker="-- PROOF_END"
    )


def build_seed_artifact(
    *,
    task: dict[str, Any],
    problem: dict[str, Any],
    source_path: Path,
    candidate: str,
    timeout: float,
    generation: Generation | None = None,
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """编译并冻结首轮候选；只有真实证明失败才有资格进入反馈分叉。"""

    compiled = compile_candidate(
        source_path, problem["source_text"], candidate, problem["theorem"], timeout=timeout,
    )
    diagnostic = normalize_diagnostics(
        compiled.diagnostics, returncode=compiled.returncode, timed_out=compiled.timed_out,
    )
    if compiled.ok and diagnostics_use_sorry(compiled.diagnostics):
        diagnostic = {"category": "incomplete_proof", "summary": "候选依赖未完成证明", "feedback": "", "errors": []}
    category = str(diagnostic.get("category") or "compile_error")
    supported_failure = category in ALLOWED_CATEGORIES and category not in INFRASTRUCTURE
    eligible = not compiled.ok and not compiled.timed_out and compiled.returncode is not None and supported_failure
    record = None
    graph = None
    if eligible:
        record = build_feedback_record(
            case_id=seed_key({**task, "problem_id": problem["id"]}),
            diagnostic_text=compiled.diagnostics,
            compile_ok=False,
            returncode=compiled.returncode,
            round_no=1,
            roots=(ROOT, source_path.parent),
        )
        graph = build_error_state_graph(
            record,
            theorem_name=problem["theorem"],
            source_text=compiled.isolated_source,
            candidate=candidate,
        )
    safe_diagnostics = record["raw"]["text"] if record else redact_text(
        redact_sensitive_text(compiled.diagnostics), (ROOT, source_path.parent)
    )
    return {
        **task,
        "problem_id": problem["id"],
        "seed_id": seed_key({**task, "problem_id": problem["id"]}),
        "candidate": candidate,
        "compile_ok": bool(compiled.ok),
        "eligible_first_failure": eligible,
        "ineligibility_reason": None if eligible else (
            "first_candidate_succeeded" if compiled.ok else
            "unsupported_feedback_category" if not supported_failure else
            "infrastructure_or_non_compiler_failure"
        ),
        "diagnostic": diagnostic,
        "raw_diagnostics": safe_diagnostics[:8000],
        "compile_returncode": compiled.returncode,
        "compile_timed_out": compiled.timed_out,
        "feedback_record": record,
        "error_state_graph": graph,
        "provider_config": provider_metadata or {},
        "provider_response": {
            "model": generation.raw.get("model") if generation else None,
            "finish_reason": generation_finish_reason(generation.raw) if generation else None,
        },
        "usage": generation.usage if generation else {},
        "estimated_cost_usd": estimate_cost(generation.usage, provider_metadata or {}) if generation else None,
    }


def _signal_signature(seed: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(signal["kind"]), str(signal["value"]))
        for signal in seed["feedback_record"]["structured"]["signals"]
    )


def donor_map(seeds: list[dict[str, Any]], *, distinct_signals: bool = False) -> dict[str, str]:
    """在同模型、同重复、同错误类别内选供体，禁止自配对。"""

    groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for seed in seeds:
        if seed.get("eligible_first_failure"):
            groups[(seed["model_id"], seed["repeat"], seed["diagnostic"]["category"])].append(seed)
    mapping: dict[str, str] = {}
    for items in groups.values():
        ordered = sorted(items, key=lambda item: item["problem_id"])
        for index, item in enumerate(ordered):
            candidates = [*ordered[index + 1:], *ordered[:index]]
            if distinct_signals:
                candidates = [candidate for candidate in candidates if _signal_signature(candidate) != _signal_signature(item)]
            if candidates:
                mapping[item["seed_id"]] = candidates[0]["seed_id"]
    return mapping


def intervention_for(
    arm: str,
    target: dict[str, Any],
    *,
    donor: dict[str, Any] | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError("未知因果反馈干预")
    if not target.get("eligible_first_failure"):
        raise ValueError("只有冻结首轮失败可进入反馈干预")
    record = target["feedback_record"]
    graph = target["error_state_graph"]
    source_seed = target["seed_id"]
    payload = ""
    donor_id = None
    available = True
    if arm == "content_free_retry":
        payload = "上一候选未通过验证。请重新给出完整证明。"
    elif arm == "true_raw":
        payload = record["raw"]["text"]
    elif arm == "true_normalized":
        payload = record["normalized"]["summary"] + "\n" + record["normalized"]["diagnostic_text"]
    elif arm == "true_structured":
        payload = json.dumps(record["structured"], ensure_ascii=False, sort_keys=True)
    elif arm in {"irrelevant_matched", "counterfactual"}:
        available = donor is not None
        if donor is not None:
            donor_id = donor["seed_id"]
            donor_record = donor["feedback_record"]
            if donor_record["structured"]["category"] != record["structured"]["category"]:
                raise ValueError("无关反馈供体必须与目标错误类别一致")
            if donor_id == source_seed:
                raise ValueError("无关反馈供体不得是目标自身")
            if arm == "irrelevant_matched":
                payload = donor_record["raw"]["text"]
            else:
                payload = json.dumps({
                    "category": record["structured"]["category"],
                    "signals": [
                        {"kind": signal["kind"], "value": signal["value"]}
                        for signal in donor_record["structured"]["signals"]
                    ],
                }, ensure_ascii=False, sort_keys=True)
    elif arm == "retrieval_only":
        payload = "不提供编译诊断；仅使用下列本地示例重新证明。"
    elif arm == "adaptive":
        route = route_feedback(graph, examples_available=bool(examples))
        payload = route["payload"]
    return {
        "schema_version": PROTOCOL_VERSION,
        "arm": arm,
        "target_seed_id": source_seed,
        "available": available,
        "payload": payload,
        "payload_source": (
            "target_true_diagnostic" if arm.startswith("true_") else
            "category_matched_other_task" if arm == "irrelevant_matched" else
            "category_preserved_donor_signals" if arm == "counterfactual" else
            "adaptive_true_diagnostic" if arm == "adaptive" else
            "no_diagnostic"
        ),
        "donor_seed_id": donor_id,
        "retrieved_examples": examples or [],
        "adaptive_route": route_feedback(graph, examples_available=bool(examples)) if arm == "adaptive" else None,
    }


def branch_prompt(problem: dict[str, Any], seed: dict[str, Any], intervention: dict[str, Any]) -> str:
    if intervention["target_seed_id"] != seed["seed_id"]:
        raise ValueError("反馈干预与冻结首轮候选不匹配")
    template = (ROOT / "prompts/causal_branch.txt").read_text(encoding="utf-8")
    contract = (ROOT / "prompts/proof_contract.txt").read_text(encoding="utf-8")
    return template.format(
        theorem=_prompt_source(problem),
        first_candidate=seed["candidate"],
        intervention=intervention["payload"],
        examples=json.dumps(intervention["retrieved_examples"], ensure_ascii=False),
    ) + "\n" + contract.format(start_marker="-- PROOF_START", end_marker="-- PROOF_END")


def run_matrix(
    config: dict[str, Any], benchmark_path: Path, out: Path,
    *, api_keys: dict[str, str] | None = None, budget: CallBudget | None = None,
    project_root: Path | None = None, preregistration: dict[str, Any] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """运行两阶段矩阵；显式续跑只跳过已落盘记录，不重发已有请求。"""

    protocol = validate_protocol()
    benchmark = load_benchmark(benchmark_path)
    if preregistration is not None:
        validate_preregistration_record(preregistration, config, benchmark)
    if project_root is not None:
        project_root = project_root.resolve()
    project_roots, toolchain_snapshot, compile_environment = resolve_compile_environments(
        benchmark, project_root,
    )
    plan = build_plan(config, benchmark)
    providers = _providers(config, api_keys, budget)
    examples = load_examples(ROOT / config.get("examples_dir", "examples"))
    saved_plan = read_json(out / "plan.json") if resume and (out / "plan.json").is_file() else None
    experiment_id = (
        str(saved_plan["experiment_id"])
        if saved_plan is not None else
        preregistration["planned_experiment_id"]
        if preregistration is not None else "causal-feedback-" + str(uuid.uuid4())
    )
    plan_record = {
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": experiment_id,
        "protocol": protocol,
        "config": config,
        "benchmark_version": benchmark["version"],
        "plan": plan,
        "lean_toolchain": toolchain_snapshot,
        "compile_environment": compile_environment,
        "platform": platform.system(),
        "prompt_templates": {
            name: (ROOT / "prompts" / name).read_text(encoding="utf-8")
            for name in ("causal_seed.txt", "causal_branch.txt", "proof_contract.txt")
        },
        "status": "running",
        "preregistration": preregistration,
    }
    if resume:
        if not out.is_dir():
            raise ValueError("续跑目录不存在")
        if (out / "summary.json").is_file():
            raise ValueError("批次已经生成 summary.json；拒绝再次续跑")
        saved_plan = read_json(out / "plan.json")
        saved_benchmark = read_json(out / "benchmark.json")
        if saved_plan != plan_record or saved_benchmark != benchmark:
            raise ValueError("续跑输入、配置、提示模板、环境或预注册记录与原批次不一致")
        if budget is not None:
            saved_budget = read_json(out / "budget.json")
            budget.restore(saved_budget)
            saved_seed_attempts = len(list((out / "seeds").rglob("*.json"))) if (out / "seeds").is_dir() else 0
            saved_branch_attempts = 0
            if (out / "branches").is_dir():
                for path in (out / "branches").rglob("result.json"):
                    if read_json(path).get("status") != "not_applicable":
                        saved_branch_attempts += 1
            if budget.calls != saved_seed_attempts + saved_branch_attempts:
                raise ValueError(
                    "预算账本与已落盘请求数不一致；可能存在结果未知的已计费请求，拒绝自动续跑"
                )
    else:
        out.mkdir(parents=True, exist_ok=False)
        write_json(out / "plan.json", plan_record)
        write_json(out / "benchmark.json", benchmark)
    if budget is not None:
        budget.ledger_path = out / "budget.json"
        if not resume:
            write_json(out / "budget.json", budget.snapshot())

    selected_ids = {item["problem_id"] for item in plan["seed_tasks"]}
    problems = {item["id"]: item for item in benchmark["problems"] if item["id"] in selected_ids}
    models = {item["id"]: item for item in config["models"]}
    seeds: list[dict[str, Any]] = []
    for index, task in enumerate(plan["seed_tasks"], 1):
        seed_path = out / "seeds" / task["model_id"] / str(task["repeat"]) / f"{task['problem_id']}.json"
        if resume and seed_path.is_file():
            seed = read_json(seed_path)
            expected = {**task, "experiment_id": experiment_id, "seed_id": seed_key(task)}
            if any(seed.get(key) != value for key, value in expected.items()):
                raise ValueError("既有首轮记录与冻结计划不一致：" + seed_key(task))
            seeds.append(seed)
            print(f"seed {index}/{len(plan['seed_tasks'])} {seed['seed_id']}: SKIP", flush=True)
            continue
        problem = problems[task["problem_id"]]
        source_file = benchmark_path.parent / problem["file"]
        active_project_root = project_roots.get(problem.get("project_id")) or project_root
        compile_anchor = (
            active_project_root / f"TRACERCausal_{problem['id']}.lean"
            if active_project_root is not None else source_file
        )
        provider = providers[task["model_id"]]
        prompt = _seed_prompt(problem)
        started = time.perf_counter()
        try:
            candidate, generation, _ = _generate(provider, prompt)
            seed = build_seed_artifact(
                task=task, problem=problem, source_path=compile_anchor,
                candidate=candidate, timeout=config["compile_timeout"], generation=generation,
                provider_metadata=provider.metadata(),
            )
            seed["experiment_id"] = experiment_id
            seed["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        except CandidateOutcomeError as exc:
            seed = {**task, "experiment_id": experiment_id, "seed_id": seed_key(task), "candidate": "", "compile_ok": False,
                    "eligible_first_failure": False, "ineligibility_reason": exc.category,
                    "diagnostic": {"category": exc.category, "summary": str(exc)}}
        except Exception as exc:
            seed = {**task, "experiment_id": experiment_id, "seed_id": seed_key(task), "candidate": "", "compile_ok": False,
                    "eligible_first_failure": False, "ineligibility_reason": "provider_or_policy_error",
                    "error": redact_sensitive_text(exc)}
        write_json(seed_path, seed)
        seeds.append(seed)
        seed_status = "ELIGIBLE" if seed.get("eligible_first_failure") else "INELIGIBLE:" + str(seed.get("ineligibility_reason"))
        print(f"seed {index}/{len(plan['seed_tasks'])} {seed['seed_id']}: {seed_status}", flush=True)

    irrelevant_donors = donor_map(seeds)
    counterfactual_donors = donor_map(seeds, distinct_signals=True)
    by_id = {seed["seed_id"]: seed for seed in seeds}
    branches = [
        {
            "seed_id": seed["seed_id"], "arm": arm,
            "project_id": seed.get("project_id"), "split": seed.get("split"),
        }
        for seed in seeds if seed.get("eligible_first_failure") for arm in ARMS
    ]
    random.Random(config.get("order_seed", 20260913) + 1).shuffle(branches)
    results = []
    for index, item in enumerate(branches, 1):
        seed = by_id[item["seed_id"]]
        problem = problems[seed["problem_id"]]
        source_file = benchmark_path.parent / problem["file"]
        active_project_root = project_roots.get(problem.get("project_id")) or project_root
        compile_anchor = (
            active_project_root / f"TRACERCausal_{problem['id']}.lean"
            if active_project_root is not None else source_file
        )
        target_text = problem["theorem"] + "\n" + problem["source_text"]
        retrieved = retrieve(target_text, examples, top_k=3, target=target_text) if item["arm"] in {"retrieval_only", "adaptive"} else []
        selected_donors = counterfactual_donors if item["arm"] == "counterfactual" else irrelevant_donors
        donor = by_id.get(selected_donors.get(seed["seed_id"], ""))
        intervention = intervention_for(item["arm"], seed, donor=donor, examples=retrieved)
        destination = out / "branches" / seed["model_id"] / str(seed["repeat"]) / item["arm"] / seed["problem_id"]
        result_path = destination / "result.json"
        if resume and result_path.is_file():
            result = read_json(result_path)
            if (
                result.get("experiment_id") != experiment_id
                or result.get("seed_id") != seed["seed_id"]
                or result.get("arm") != item["arm"]
                or result.get("problem_id") != seed["problem_id"]
            ):
                raise ValueError("既有分支记录与冻结计划不一致：" + seed["seed_id"] + "/" + item["arm"])
            results.append(result)
            print(f"branch {index}/{len(branches)} {item['arm']} {seed['seed_id']}: SKIP", flush=True)
            continue
        if not intervention["available"]:
            result = {**item, "experiment_id": experiment_id, "problem_id": seed["problem_id"], "status": "not_applicable",
                      "reason": "同模型、同重复、同错误类别内没有其他供体", "compile_ok": None,
                      "first_candidate": seed["candidate"], "intervention": intervention}
        else:
            prompt = branch_prompt(problem, seed, intervention)
            provider = providers[seed["model_id"]]
            started = time.perf_counter()
            try:
                candidate, generation, _ = _generate(provider, prompt)
                compiled = compile_candidate(
                    compile_anchor, problem["source_text"], candidate,
                    problem["theorem"], timeout=config["compile_timeout"],
                )
                diagnostic = normalize_diagnostics(
                    compiled.diagnostics, returncode=compiled.returncode, timed_out=compiled.timed_out,
                )
                if compiled.timed_out or compiled.returncode is None:
                    raise RuntimeError("分支发生编译超时或编译器不可用；不计作普通证明失败")
                compile_ok = bool(compiled.ok and not diagnostics_use_sorry(compiled.diagnostics))
                independent_ok = None
                if compile_ok:
                    destination.mkdir(parents=True, exist_ok=True)
                    solution_path = destination / "solution.lean"
                    solution_path.write_text(compiled.isolated_source, encoding="utf-8")
                    checked = run_lean_file(
                        solution_path, config["compile_timeout"],
                        active_project_root or find_project_root(source_file),
                    )
                    if not checked.ok or diagnostics_use_sorry(checked.diagnostics):
                        raise RuntimeError("分支成功证明独立复编译失败")
                    independent_ok = True
                result = {
                    **item, "experiment_id": experiment_id, "problem_id": seed["problem_id"], "status": "complete",
                    "first_candidate": seed["candidate"], "candidate": candidate,
                    "same_first_candidate": True, "intervention": intervention,
                    "compile_ok": compile_ok,
                    "independent_compile_ok": independent_ok,
                    "diagnostic": diagnostic,
                    "raw_diagnostics": redact_text(
                        redact_sensitive_text(compiled.diagnostics),
                        tuple(path for path in (ROOT, source_file.parent, active_project_root) if path is not None),
                    )[:8000],
                    "usage": generation.usage,
                    "estimated_cost_usd": estimate_cost(generation.usage, provider.metadata()),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            except CandidateOutcomeError as exc:
                result = {**item, "experiment_id": experiment_id, "problem_id": seed["problem_id"], "status": "complete",
                          "first_candidate": seed["candidate"], "candidate": "",
                          "same_first_candidate": True, "intervention": intervention,
                          "compile_ok": False,
                          "diagnostic": {"category": exc.category, "summary": str(exc)},
                          "usage": {}, "estimated_cost_usd": None}
            except Exception as exc:
                result = {**item, "experiment_id": experiment_id, "problem_id": seed["problem_id"], "status": "error",
                          "first_candidate": seed["candidate"], "same_first_candidate": True,
                          "intervention": intervention, "compile_ok": False,
                          "error": redact_sensitive_text(exc)}
        write_json(result_path, result)
        results.append(result)
        print(f"branch {index}/{len(branches)} {item['arm']} {seed['seed_id']}: {result['status']}", flush=True)

    summary = summarize(seeds, results)
    write_json(out / "summary.json", summary)
    return summary


def summarize(seeds: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [seed for seed in seeds if seed.get("eligible_first_failure")]
    complete = [row for row in results if row.get("status") == "complete"]
    by_arm = {}
    for arm in ARMS:
        rows = [row for row in complete if row["arm"] == arm]
        by_arm[arm] = {
            "completed": len(rows),
            "success": sum(bool(row.get("compile_ok")) for row in rows),
            "success_rate": sum(bool(row.get("compile_ok")) for row in rows) / len(rows) if rows else None,
        }
    baseline = by_arm["content_free_retry"]["success_rate"]
    for arm, values in by_arm.items():
        values["descriptive_lift_over_content_free"] = (
            values["success_rate"] - baseline
            if values["success_rate"] is not None and baseline is not None else None
        )
    by_pair = {(row["seed_id"], row["arm"]): row for row in complete}
    paired = []
    for arm in ARMS:
        if arm == "content_free_retry":
            continue
        differences = []
        for seed in eligible:
            treatment = by_pair.get((seed["seed_id"], arm))
            control = by_pair.get((seed["seed_id"], "content_free_retry"))
            if treatment is not None and control is not None:
                differences.append(int(bool(treatment["compile_ok"])) - int(bool(control["compile_ok"])))
        paired.append({
            "comparison": arm + " - content_free_retry",
            "matched_pairs": len(differences),
            "wins": sum(value > 0 for value in differences),
            "losses": sum(value < 0 for value in differences),
            "ties": sum(value == 0 for value in differences),
            "mean_success_delta": sum(differences) / len(differences) if differences else None,
            "by_project": _project_paired_effects(eligible, by_pair, arm),
        })
    seed_lookup = {seed["seed_id"]: seed["candidate"] for seed in eligible}
    invariant = all(
        row.get("status") != "complete"
        or row.get("first_candidate") == seed_lookup.get(row.get("seed_id"))
        for row in results
    )
    independent_invariant = all(
        not row.get("compile_ok") or row.get("independent_compile_ok") is True
        for row in complete
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "seed_tasks": len(seeds),
        "eligible_first_failures": len(eligible),
        "eligibility_rate": len(eligible) / len(seeds) if seeds else None,
        "branch_results": len(results),
        "infrastructure_errors": sum(
            bool(seed.get("error")) or seed.get("ineligibility_reason") == "provider_or_policy_error"
            for seed in seeds
        ) + sum(row.get("status") == "error" for row in results),
        "same_first_candidate_invariant": invariant,
        "successful_proof_recompile_invariant": independent_invariant,
        "by_arm": by_arm,
        "paired_comparisons": paired,
        "project_coverage": sorted({seed.get("project_id") for seed in seeds if seed.get("project_id")}),
        "claim_boundary": "当前汇总只报告描述性的逐项目配对效应；是否满足预注册的正式结论门禁，必须另行核对项目数、资格样本、排除与发布审计。",
    }


def _project_paired_effects(
    eligible: list[dict[str, Any]], by_pair: dict[tuple[str, str], dict[str, Any]], arm: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for seed in eligible:
        treatment = by_pair.get((seed["seed_id"], arm))
        control = by_pair.get((seed["seed_id"], "content_free_retry"))
        if treatment is not None and control is not None:
            grouped[str(seed.get("project_id") or "unrecorded")].append(
                int(bool(treatment["compile_ok"])) - int(bool(control["compile_ok"]))
            )
    return [
        {
            "project_id": project_id,
            "matched_pairs": len(values),
            "mean_success_delta": sum(values) / len(values),
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "ties": sum(value == 0 for value in values),
        }
        for project_id, values in sorted(grouped.items())
    ]


def _prompt_keys(config: dict[str, Any]) -> dict[str, str]:
    if not sys.stdin.isatty():
        raise ValueError("隐藏密钥输入需要交互终端")
    keys = {}
    for model in config["models"]:
        name = model["api_key_env"]
        if name not in keys:
            value = getpass.getpass("API key（不会回显或保存）：").strip()
            if not value:
                raise ValueError("API key 不能为空")
            keys[name] = value
    print("已在进程内读取密钥；不显示长度、后缀或内容。", flush=True)
    return keys


def audit_run(run: Path) -> dict[str, Any]:
    """核对预注册批次的完整性；不读取或调用 provider。"""

    run = run.resolve()
    plan_path, benchmark_path, summary_path = (
        run / "plan.json", run / "benchmark.json", run / "summary.json",
    )
    missing = [path.name for path in (plan_path, benchmark_path, summary_path) if not path.is_file()]
    if missing:
        return {"ok": False, "run": str(run), "errors": ["缺少文件：" + ", ".join(missing)]}
    plan_record = read_json(plan_path)
    benchmark = read_json(benchmark_path)
    summary = read_json(summary_path)
    config = plan_record.get("config", {})
    errors: list[str] = []
    try:
        validate_preregistration_record(plan_record.get("preregistration"), config, benchmark)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        errors.append("预注册校验失败：" + str(exc))
    planned = plan_record.get("plan", {}).get("seed_tasks", [])
    planned_ids = {seed_key(task) for task in planned}
    seed_rows = [read_json(path) for path in (run / "seeds").rglob("*.json")] if (run / "seeds").is_dir() else []
    actual_ids = {row.get("seed_id") for row in seed_rows}
    if len(seed_rows) != len(planned) or actual_ids != planned_ids:
        errors.append("冻结首轮记录与计划不一致")
    eligible = [row for row in seed_rows if row.get("eligible_first_failure")]
    branch_rows = [
        read_json(path) for path in (run / "branches").rglob("result.json")
    ] if (run / "branches").is_dir() else []
    expected_pairs = {(row["seed_id"], arm) for row in eligible for arm in ARMS}
    actual_pairs = {(row.get("seed_id"), row.get("arm")) for row in branch_rows}
    if len(branch_rows) != len(expected_pairs) or actual_pairs != expected_pairs:
        errors.append("干预分支记录与合格首轮失败不一致")
    infrastructure_errors = sum(
        bool(row.get("error")) or row.get("ineligibility_reason") == "provider_or_policy_error"
        for row in seed_rows
    ) + sum(row.get("status") == "error" for row in branch_rows)
    if infrastructure_errors:
        errors.append(f"存在 {infrastructure_errors} 个 provider、策略或编译基础设施错误")
    if summary.get("same_first_candidate_invariant") is not True:
        errors.append("同首轮候选不变量未通过")
    if summary.get("successful_proof_recompile_invariant") is not True:
        errors.append("成功证明独立复编译不变量未通过")
    prereg = plan_record.get("preregistration") or {}
    gate = prereg.get("claim_gate") or {}
    selected_projects = set(plan_record.get("plan", {}).get("selected_projects") or [])
    claim_authorized = gate.get(
        "confirmatory_claim_allowed",
        gate.get("confirmatory_claim_allowed_for_v1"),
    )
    confirmatory_gate = (
        not errors
        and len(selected_projects) >= gate.get("minimum_test_projects", 10**9)
        and len(eligible) >= gate.get("minimum_eligible_first_failures", 10**9)
        and claim_authorized is True
    )
    return {
        "ok": not errors,
        "protocol_version": plan_record.get("protocol_version"),
        "experiment_id": plan_record.get("experiment_id"),
        "benchmark_version": plan_record.get("benchmark_version"),
        "planned_seeds": len(planned),
        "recorded_seeds": len(seed_rows),
        "eligible_first_failures": len(eligible),
        "recorded_branches": len(branch_rows),
        "infrastructure_errors": infrastructure_errors,
        "analysis_ready": not errors,
        "confirmatory_claim_allowed": confirmatory_gate,
        "required_label": gate.get("required_label"),
        "errors": errors,
    }


def preflight_provider(config: dict[str, Any], api_keys: dict[str, str] | None = None) -> dict[str, Any]:
    """用合成定理验证 provider、候选解析和 Lean；不读取 TRACER-REAL。"""

    providers = _providers(config, api_keys, None)
    source = (
        "import Std\n\n"
        "theorem tracerProviderPreflight : True :=\n"
        "  -- PROOF_START\n"
        "  by trivial\n"
        "  -- PROOF_END\n"
    )
    prompt = (
        "这是连接预检，不是实验任务。请只返回 Lean 证明体，使下列定理成立；"
        "不要返回 Markdown 或解释。\n\n" + source
    )
    rows = []
    for model in config["models"]:
        provider = providers[model["id"]]
        try:
            candidate, generation, finish = _generate(provider, prompt)
            compiled = compile_candidate(
                ROOT / "lean_project/TRACERProviderPreflight.lean", source, candidate,
                "tracerProviderPreflight", timeout=config["compile_timeout"],
            )
            rows.append({
                "model_id": model["id"],
                "provider_ok": True,
                "finish_reason": finish,
                "candidate_parsed": bool(candidate),
                "lean_compile_ok": bool(compiled.ok and not diagnostics_use_sorry(compiled.diagnostics)),
                "usage": generation.usage,
            })
        except Exception as exc:
            rows.append({"model_id": model["id"], "provider_ok": False, "error": redact_sensitive_text(exc)})
    return {
        "ok": all(row["provider_ok"] for row in rows),
        "scope": "合成 True 定理连接预检；不读取 TRACER-REAL，不属于预注册实验调用数。",
        "models": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, default=ROOT / "experiments/causal_feedback.example.json")
        command.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks/repair24/manifest.json")
        command.add_argument("--project-root", type=Path)
        command.add_argument("--preregistration", type=Path)
        if name == "run":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--api-url")
            command.add_argument("--model")
            command.add_argument("--model-id")
            command.add_argument("--temperature", type=float)
            command.add_argument("--max-tokens", type=int)
            command.add_argument("--thinking", choices=("enabled", "disabled"))
            command.add_argument("--reasoning-effort", choices=("low", "high", "max"))
            command.add_argument("--input-price-per-1k", type=float)
            command.add_argument("--output-price-per-1k", type=float)
            command.add_argument("--api-key-prompt", action="store_true")
            command.add_argument("--max-calls", type=int)
            command.add_argument("--resume", action="store_true", help="严格续跑已有目录；跳过已落盘请求")
            cost = command.add_mutually_exclusive_group(required=True)
            cost.add_argument("--max-reserved-usd", type=float)
            cost.add_argument("--no-cost-limit", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--run", type=Path, required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--config", type=Path, default=ROOT / "experiments/causal_feedback.tracer_real_v1.json")
    preflight.add_argument("--api-url")
    preflight.add_argument("--model")
    preflight.add_argument("--model-id")
    preflight.add_argument("--temperature", type=float)
    preflight.add_argument("--max-tokens", type=int)
    preflight.add_argument("--thinking", choices=("enabled", "disabled"))
    preflight.add_argument("--reasoning-effort", choices=("low", "high", "max"))
    preflight.add_argument("--input-price-per-1k", type=float)
    preflight.add_argument("--output-price-per-1k", type=float)
    preflight.add_argument("--api-key-prompt", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            result = audit_run(args.run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "preflight":
            config = validate_config(args.config)
            config = apply_direct_model_config(
                config, args.api_url, args.model, args.model_id, args.temperature,
                args.max_tokens, args.thinking, args.reasoning_effort,
                args.input_price_per_1k, args.output_price_per_1k,
            )
            keys = _prompt_keys(config) if args.api_key_prompt else None
            result = preflight_provider(config, keys)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        protocol = validate_protocol()
        config = validate_config(args.config)
        benchmark = load_benchmark(args.benchmark)
        if args.command == "plan":
            preregistration = (
                validate_preregistration(args.preregistration, config, benchmark)
                if args.preregistration else None
            )
            plan = build_plan(config, benchmark)
            print(json.dumps({
                "protocol": protocol["version"],
                "benchmark": benchmark["version"],
                "seed_tasks": len(plan["seed_tasks"]),
                "maximum_branch_tasks": plan["maximum_branch_tasks"],
                "maximum_generations": plan["maximum_generations"],
                "branch_tasks_depend_on": plan["branch_tasks_depend_on"],
                "selected_splits": plan["selected_splits"],
                "selected_projects": plan["selected_projects"],
                "preregistered_experiment_id": (
                    preregistration["planned_experiment_id"] if preregistration else None
                ),
                "network_calls": 0,
            }, ensure_ascii=False, indent=2))
            return 0
        config = apply_direct_model_config(
            config, args.api_url, args.model, args.model_id, args.temperature,
            args.max_tokens, args.thinking, args.reasoning_effort,
            args.input_price_per_1k, args.output_price_per_1k,
        )
        preregistration = (
            validate_preregistration(args.preregistration, config, benchmark)
            if args.preregistration else None
        )
        maximum = build_plan(config, benchmark)["maximum_generations"]
        max_calls = args.max_calls if args.max_calls is not None else maximum
        if not 1 <= max_calls <= maximum:
            raise ValueError("max-calls 必须在 1 与冻结计划最大生成数之间")
        budget = CallBudget(max_calls, None if args.no_cost_limit else args.max_reserved_usd)
        keys = _prompt_keys(config) if args.api_key_prompt else None
        result = run_matrix(
            config, args.benchmark.resolve(), args.out.resolve(), api_keys=keys, budget=budget,
            project_root=args.project_root, preregistration=preregistration,
            resume=args.resume,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": redact_sensitive_text(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
