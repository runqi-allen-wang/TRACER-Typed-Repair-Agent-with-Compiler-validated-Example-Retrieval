"""ACL 2027 因果反馈实验的离线预注册、题库审计与运行计划。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent import ROOT
from causal_feedback import (
    ARMS, PREREGISTRATION_VERSION, PROTOCOL_VERSION, _prompt_source, build_plan,
    prompt_source_limit,
    validate_config, validate_preregistration_record,
)
from research import load_benchmark, write_json
from retriever import find_retrieval_leaks, load_examples
from tracer_real_v2 import (
    SHARE_GATE_AMENDMENT_PATH, apply_share_gate_amendment,
    read_json, validate_contract, validate_v2_benchmark,
)


ACL_PROTOCOL_VERSION = "tracer-acl2027-causal-protocol-v2"
CONFIRMATORY_ARMS = ("content_free_retry", "true_structured", "counterfactual")
PROTOCOL_PATH = ROOT / "experiments/preregistrations/tracer_acl2027_protocol_v2.json"
BENCHMARK_PATH = ROOT / "benchmarks/real_repairs/tracer_real_v2/manifest.json"
CONTRACT_PATH = ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json"
EXTENDED_CONFIG_PATH = ROOT / "experiments/causal_feedback.tracer_acl2027_extended_v2.json"
MINIMAX_CONFIG_PATH = ROOT / "experiments/causal_feedback.tracer_acl2027_minimax_confirmatory_v2.json"
EXTENDED_PREREG_PATH = ROOT / "experiments/preregistrations/tracer_acl2027_extended_v2.json"
MINIMAX_PREREG_PATH = ROOT / "experiments/preregistrations/tracer_acl2027_minimax_confirmatory_v2.json"


def _runtime_model_view(model: dict[str, Any]) -> dict[str, Any]:
    required = ("id", "model", "api_url", "temperature", "max_tokens")
    optional = (
        "provider_kind", "wire_api", "disable_response_storage", "thinking", "reasoning_effort",
        "reasoning_split",
    )
    row = {field: model.get(field) for field in required}
    row.update({field: model.get(field) for field in optional if field in model})
    return row


def _load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = read_json(PROTOCOL_PATH)
    benchmark = load_benchmark(BENCHMARK_PATH)
    extended = validate_config(EXTENDED_CONFIG_PATH)
    minimax = validate_config(MINIMAX_CONFIG_PATH)
    return protocol, benchmark, extended, minimax


def validate_scientific_protocol(
    protocol: dict[str, Any], benchmark: dict[str, Any],
    extended: dict[str, Any], minimax: dict[str, Any],
) -> dict[str, Any]:
    """校验科学设计、项目级划分和检索泄漏；全程不调用 provider。"""

    required = {
        "version", "status", "registered_at_utc", "benchmark", "scientific_question",
        "nested_design", "model_roles", "execution_order", "primary_analysis",
        "negative_control", "runtime_freeze", "stopping_rule", "claim_gate",
    }
    if set(protocol) != required or protocol.get("version") != ACL_PROTOCOL_VERSION:
        raise ValueError("ACL 2027 科学协议版本或顶层字段不匹配")
    if protocol.get("status") != "frozen-after-aborted-v1-before-v2-provider-run":
        raise ValueError("ACL 2027 v2 协议必须在 v2 provider 题库调用前冻结")

    base_contract = read_json(CONTRACT_PATH)
    validate_contract(base_contract)
    contract = apply_share_gate_amendment(base_contract, read_json(SHARE_GATE_AMENDMENT_PATH))
    counts = validate_v2_benchmark(benchmark, contract)
    frozen_benchmark = protocol["benchmark"]
    if frozen_benchmark != {
        "manifest": "benchmarks/real_repairs/tracer_real_v2/manifest.json",
        "version": benchmark["version"],
        "split": "test",
        "split_policy": benchmark["split_policy"],
        "projects": counts["test_projects"],
        "tasks": counts["test_tasks"],
    }:
        raise ValueError("ACL 2027 协议的冻结题库与 TRACER-REAL v2 不一致")

    design = protocol["nested_design"]
    if design.get("confirmatory_arms") != list(CONFIRMATORY_ARMS):
        raise ValueError("ACL 2027 确认性三臂发生漂移")
    if design.get("extended_arms") != list(ARMS):
        raise ValueError("ACL 2027 扩展八臂发生漂移")
    if extended["arms"] != list(ARMS) or minimax["arms"] != list(CONFIRMATORY_ARMS):
        raise ValueError("ACL 2027 运行配置与嵌套设计不一致")
    shared_fields = (
        "repeats", "compile_timeout", "order_seed", "branch_attempts", "benchmark_splits",
        "prompt_source_characters",
    )
    if any(extended.get(field) != minimax.get(field) for field in shared_fields):
        raise ValueError("ACL 2027 两个运行配置的共享实验参数不一致")
    if (
        design.get("repeats") != extended["repeats"]
        or design.get("branch_attempts") != extended["branch_attempts"]
        or design.get("prompt_source_characters") != prompt_source_limit(extended)
        or design.get("same_first_candidate_required") is not True
        or design.get("performance_based_stopping") is not False
    ):
        raise ValueError("ACL 2027 重复、分支或停止规则不一致")

    active_models = {
        model["id"]: (model, "extended") for model in extended["models"]
    } | {
        model["id"]: (model, "confirmatory") for model in minimax["models"]
    }
    roles = protocol["model_roles"]
    if len(active_models) != 3 or len(roles) != 3:
        raise ValueError("ACL 2027 必须冻结三个独立模型家族")
    origins = set()
    families = set()
    for role in roles:
        families.add(role.get("family"))
        match = next(
            (item for item in active_models.values() if item[0]["model"] == role.get("model_id")),
            None,
        )
        if match is None or match[1] != role.get("matrix"):
            raise ValueError("ACL 2027 模型角色与运行配置不一致")
        origins.add(urlsplit(match[0]["api_url"]).netloc.lower())
    if len(families) != 3 or len(origins) != 3:
        raise ValueError("ACL 2027 三模型必须来自三个独立家族与一方 API 来源")
    if sum(role.get("matrix") == "extended" for role in roles) != 2:
        raise ValueError("ACL 2027 必须冻结两个完整八臂模型")

    test_problems = [problem for problem in benchmark["problems"] if problem.get("split") == "test"]
    source_limit = prompt_source_limit(extended)
    prompt_failures = []
    for problem in test_problems:
        try:
            _prompt_source(problem, limit=source_limit)
        except ValueError:
            prompt_failures.append(problem["id"])
    if prompt_failures:
        raise ValueError("ACL 2027 提示预算不能容纳完整目标声明：" + ", ".join(prompt_failures))
    examples = load_examples(ROOT / extended.get("examples_dir", "examples"))
    leaks = find_retrieval_leaks(
        [(problem["id"], problem["source_text"]) for problem in test_problems], examples,
    )
    if leaks:
        raise ValueError("ACL 2027 检索语料与冻结测试声明重合")
    categories = sorted({problem["expected_error"] for problem in test_problems})
    return {
        "test_projects": counts["test_projects"],
        "test_tasks": counts["test_tasks"],
        "test_error_categories": categories,
        "retrieval_examples": len(examples),
        "retrieval_declaration_leaks": len(leaks),
        "prompt_source_characters": source_limit,
        "prompt_view_failures": len(prompt_failures),
        "independent_model_families": len(families),
        "independent_api_origins": len(origins),
    }


def runtime_preregistration(
    protocol: dict[str, Any], benchmark: dict[str, Any], config: dict[str, Any],
    experiment_id: str,
) -> dict[str, Any]:
    test_tasks = sum(row["tasks"] for row in benchmark["projects"] if row["split"] == "test")
    seeds = test_tasks * config["repeats"] * len(config["models"])
    branches = seeds * len(config["arms"])
    registration_medium = (
        "版本控制仓库中的 ACL 2027 v2 机器可读预注册；在 v1 因提示预算实现错误中止并保留后、"
        "冻结于任何 v2 目标题库 provider 调用之前。"
        if protocol["version"] == ACL_PROTOCOL_VERSION else
        "版本控制仓库中的 ACL 2027 机器可读嵌套设计预注册；冻结于任何目标题库 provider 调用之前。"
    )
    return {
        "version": PREREGISTRATION_VERSION,
        "status": "frozen-before-provider-run",
        "planned_experiment_id": experiment_id,
        "registered_at_utc": protocol["registered_at_utc"],
        "registration_medium": registration_medium,
        "benchmark": {
            "version": benchmark["version"],
            "split_policy": benchmark["split_policy"],
            "projects": [
                {"project_id": row["project_id"], "split": row["split"], "tasks": row["tasks"]}
                for row in benchmark["projects"]
            ],
        },
        "models": [_runtime_model_view(model) for model in config["models"]],
        "design": {
            "protocol_version": PROTOCOL_VERSION,
            "arms": list(config["arms"]),
            "repeats": config["repeats"],
            "branch_attempts": config["branch_attempts"],
            "benchmark_splits": config.get("benchmark_splits"),
            "order_seed": config["order_seed"],
            "compile_timeout": config["compile_timeout"],
            "prompt_files": [
                "prompts/causal_seed.txt", "prompts/causal_branch.txt", "prompts/proof_contract.txt",
            ],
            "prompt_source_characters": prompt_source_limit(config),
        },
        "primary_analysis": {
            "population": "eligible_first_failures_on_preregistered_v2_test_projects",
            "contrast": "true_structured - content_free_retry",
            "outcome": "one_branch_attempt_kernel_success",
            "estimand": "测试项目等权的同一冻结首轮失败内平均配对成功率差",
            "project_weighting": "equal_weight_per_test_project",
            "missingness": "首轮成功不进入反馈效果人群；任何 provider、策略或编译基础设施异常都会阻止确认性报告。",
        },
        "secondary_analyses": [
            "counterfactual 负对照相对 content_free_retry 的误导率与错误类别转移",
            "按模型、错误类别、项目、token、墙钟时间和编译次数分层的描述性结果",
            "完整八臂模型额外报告 raw、normalized、irrelevant、retrieval 与 adaptive 探索性对比",
        ],
        "stopping_rule": {
            "maximum_seed_generations": seeds,
            "maximum_branch_generations": branches,
            "maximum_provider_calls": seeds + branches,
            "adaptive_early_stopping": False,
            "transport_policy": protocol["stopping_rule"]["transport_unknown_policy"],
        },
        "claim_gate": {
            "minimum_test_projects": protocol["benchmark"]["projects"],
            "minimum_test_tasks": 40,
            "maximum_test_project_task_share": 0.4,
            "share_gate_amendment": "experiments/preregistrations/tracer_real_v2_share_gate_amendment2.json",
            "minimum_eligible_first_failures": protocol["stopping_rule"]["minimum_eligible_first_failures_per_model"],
            "confirmatory_claim_allowed": True,
            "required_label": "单模型达到样本门槛且通过完整轨迹、基础设施与统计审计后，方可报告该模型的预注册确认性结果。",
        },
    }


def freeze_runtime_records() -> dict[str, Any]:
    protocol, benchmark, extended, minimax = _load_inputs()
    evidence = validate_scientific_protocol(protocol, benchmark, extended, minimax)
    records = (
        (
            EXTENDED_PREREG_PATH,
            runtime_preregistration(protocol, benchmark, extended, "tracer-acl2027-extended-v2"),
            extended,
        ),
        (
            MINIMAX_PREREG_PATH,
            runtime_preregistration(
                protocol, benchmark, minimax, "tracer-acl2027-minimax-confirmatory-v2",
            ),
            minimax,
        ),
    )
    written = []
    for path, record, config in records:
        validate_preregistration_record(record, config, benchmark)
        if path.is_file():
            if read_json(path) != record:
                raise ValueError("已存在的 ACL 运行时预注册与科学协议不一致：" + str(path))
        else:
            write_json(path, record)
            written.append(str(path.relative_to(ROOT)))
    return {"ok": True, "written": written, "evidence": evidence}


def audit_readiness(require_runtime: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    try:
        protocol, benchmark, extended, minimax = _load_inputs()
        evidence = validate_scientific_protocol(protocol, benchmark, extended, minimax)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [str(exc)]}

    runtime = []
    for path, config in ((EXTENDED_PREREG_PATH, extended), (MINIMAX_PREREG_PATH, minimax)):
        row = {"path": str(path.relative_to(ROOT)), "exists": path.is_file(), "valid": False}
        if path.is_file():
            try:
                validate_preregistration_record(read_json(path), config, benchmark)
                row["valid"] = True
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                errors.append(path.name + "：" + str(exc))
        elif require_runtime:
            errors.append("缺少 ACL 运行时预注册：" + path.name)
        runtime.append(row)

    plans = {
        "extended": build_plan(extended, benchmark),
        "minimax_confirmatory": build_plan(minimax, benchmark),
    }
    maximum_calls = sum(plan["maximum_generations"] for plan in plans.values())
    if maximum_calls != protocol["stopping_rule"]["maximum_total_provider_calls"]:
        errors.append("ACL 最大 provider 调用数与冻结运行计划不一致")
    return {
        "ok": not errors,
        "protocol_version": protocol["version"],
        "benchmark_version": benchmark["version"],
        "offline_evidence": evidence,
        "runtime_preregistrations": runtime,
        "plans": {
            name: {
                "seed_tasks": len(plan["seed_tasks"]),
                "maximum_branch_tasks": plan["maximum_branch_tasks"],
                "maximum_generations": plan["maximum_generations"],
            }
            for name, plan in plans.items()
        },
        "maximum_total_provider_calls": maximum_calls,
        "ready_for_synthetic_provider_preflight": not errors,
        "ready_for_benchmark_run": not errors and all(row["valid"] for row in runtime),
        "network_calls": 0,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "audit", "plan"))
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze_runtime_records()
        else:
            result = audit_readiness(require_runtime=args.command == "audit")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
