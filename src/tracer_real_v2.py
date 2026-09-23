"""TRACER-REAL v2 的两阶段纳入、冻结与预注册门禁。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "tracer-real-v2-enrollment-v1"
ENROLLMENT_PREREGISTRATION_VERSION = "tracer-causal-v2-enrollment-preregistration-v1"
FINAL_PREREGISTRATION_VERSION = "tracer-causal-preregistration-v1"
BENCHMARK_VERSION = "tracer-real-v2"
CANDIDATE_INVENTORY_VERSION = "tracer-real-v2-candidate-inventory-v1"
CANDIDATE_INVENTORY_AMENDED_VERSION = "tracer-real-v2-candidate-inventory-v2"
ENROLLMENT_AMENDMENT_VERSION = "tracer-real-v2-enrollment-amendment-v1"
SHARE_GATE_AMENDMENT_VERSION = "tracer-real-v2-share-gate-amendment-v1"
SHARE_GATE_AMENDMENT_PATH = (
    ROOT / "experiments/preregistrations/tracer_real_v2_share_gate_amendment2.json"
)
CANDIDATE_SCAN_VERSION = "tracer-real-candidate-inventory-v1"
CANDIDATE_SCREEN_VERSION = "tracer-real-candidate-screen-v1"
PROJECT_SPLITS = ("development", "validation", "test")
CAUSAL_ARMS = (
    "content_free_retry",
    "true_raw",
    "true_normalized",
    "true_structured",
    "irrelevant_matched",
    "counterfactual",
    "retrieval_only",
    "adaptive",
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _https_repository(value: object) -> bool:
    parsed = urlsplit(str(value))
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def canonical_repository(value: object) -> str:
    """规范仓库身份，防止通过结尾斜杠或 `.git` 后缀重复纳入。"""

    parsed = urlsplit(str(value))
    path = parsed.path.rstrip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    return parsed.netloc.lower() + path.lower()


def validate_contract(contract: dict[str, Any]) -> None:
    required = {
        "version", "status", "registered_at_utc", "benchmark_version", "split_policy",
        "starting_inventory", "selection", "admissibility", "exclusions", "freeze_sequence",
        "provider_gate",
    }
    if set(contract) != required or contract.get("version") != CONTRACT_VERSION:
        raise ValueError("TRACER-REAL v2 纳入合同版本或顶层字段不匹配")
    if contract.get("status") != "frozen-before-new-test-project-enrollment":
        raise ValueError("v2 纳入规则必须先于新测试项目筛选冻结")
    if contract.get("benchmark_version") != BENCHMARK_VERSION:
        raise ValueError("v2 目标题库版本不匹配")
    if contract.get("split_policy") != "upstream_project_disjoint":
        raise ValueError("v2 必须按上游项目完全隔离")

    inventory = contract.get("starting_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {"source_benchmark", "projects"}:
        raise ValueError("v2 起始库存字段不完整")
    projects = inventory.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("v2 起始库存不能为空")
    seen_projects: set[str] = set()
    for row in projects:
        if set(row) != {"project_id", "v2_split", "source_manifest"}:
            raise ValueError("v2 起始项目字段不完整")
        project_id = row.get("project_id")
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9_]+", project_id):
            raise ValueError("v2 起始项目 ID 非法")
        if project_id in seen_projects:
            raise ValueError("v2 起始项目重复")
        if row.get("v2_split") not in {"development", "validation"}:
            raise ValueError("既有项目不得作为 v2 确认性测试项目")
        seen_projects.add(project_id)

    selection = contract.get("selection")
    selection_fields = {
        "minimum_projects_total", "minimum_test_projects", "minimum_total_tasks",
        "minimum_test_tasks", "minimum_tasks_per_test_project",
        "maximum_test_project_task_share", "minimum_test_error_categories",
        "excluded_test_project_ids", "excluded_test_repositories",
        "project_identity_unit", "overflow_policy",
    }
    if not isinstance(selection, dict) or set(selection) != selection_fields:
        raise ValueError("v2 纳入数量门槛字段不完整")
    integer_fields = (
        "minimum_projects_total", "minimum_test_projects", "minimum_total_tasks",
        "minimum_test_tasks", "minimum_tasks_per_test_project", "minimum_test_error_categories",
    )
    if any(type(selection.get(field)) is not int or selection[field] <= 0 for field in integer_fields):
        raise ValueError("v2 纳入数量门槛必须为正整数")
    share = selection.get("maximum_test_project_task_share")
    if not isinstance(share, (int, float)) or not 0 < share <= 1:
        raise ValueError("v2 单项目任务占比上限无效")
    excluded = selection.get("excluded_test_project_ids")
    if not isinstance(excluded, list) or len(excluded) != len(set(excluded)) or set(excluded) != seen_projects:
        raise ValueError("v2 测试项目排除表必须覆盖全部既有项目")
    excluded_repositories = selection.get("excluded_test_repositories")
    if (
        not isinstance(excluded_repositories, list)
        or any(not _https_repository(value) for value in excluded_repositories)
        or len(excluded_repositories) != len(seen_projects)
        or len(excluded_repositories) != len({canonical_repository(value) for value in excluded_repositories})
    ):
        raise ValueError("v2 测试仓库排除表必须唯一覆盖全部既有上游来源")
    if selection.get("project_identity_unit") != "canonical_upstream_repository":
        raise ValueError("v2 项目身份必须按规范上游仓库判定")

    if not isinstance(contract.get("admissibility"), list) or len(contract["admissibility"]) < 6:
        raise ValueError("v2 必须冻结完整任务纳入标准")
    if not isinstance(contract.get("exclusions"), list) or len(contract["exclusions"]) < 5:
        raise ValueError("v2 必须冻结完整排除标准")
    if contract.get("freeze_sequence") != [
        "enrollment_contract", "candidate_inventory", "verified_benchmark_manifest",
        "final_runtime_preregistration", "provider_run",
    ]:
        raise ValueError("v2 冻结顺序发生漂移")
    gate = contract.get("provider_gate")
    if not isinstance(gate, dict) or gate.get("provider_calls_allowed_before_final_freeze") is not False:
        raise ValueError("v2 最终冻结前必须禁止 provider 调用")
    if gate.get("required_runtime_preregistration") != "experiments/preregistrations/tracer_real_causal_v2.json":
        raise ValueError("v2 最终预注册路径发生漂移")
    if gate.get("project_environment_policy") != (
        "每个项目必须绑定仓库内相对 Lake 根和精确 lean-toolchain；正式运行禁止用一个命令行项目根覆盖全部项目。"
    ):
        raise ValueError("v2 项目编译环境策略发生漂移")
    if not (ROOT / "src/causal_analysis_v2.py").is_file():
        raise ValueError("v2 预注册确认性分析实现缺失")


def apply_share_gate_amendment(
    contract: dict[str, Any], amendment: dict[str, Any],
) -> dict[str, Any]:
    """核对公开修订并返回只在项目占比阈值上不同的有效合同。"""

    validate_contract(contract)
    required = {
        "version", "status", "registered_at_utc", "amends",
        "supersedes_enrollment_extension", "trigger", "decision",
        "provider_calls_observed",
    }
    if set(amendment) != required or amendment.get("version") != SHARE_GATE_AMENDMENT_VERSION:
        raise ValueError("v2 项目占比修订版本或顶层字段不匹配")
    if amendment.get("status") != "frozen-before-final-manifest-and-provider-run":
        raise ValueError("v2 项目占比修订必须先于最终 manifest 与 provider 运行冻结")
    if amendment.get("amends") != "benchmarks/real_repairs/tracer_real_v2.enrollment.json":
        raise ValueError("v2 项目占比修订指向错误的纳入合同")
    if amendment.get("provider_calls_observed") != 0:
        raise ValueError("v2 项目占比修订前不得存在 provider 调用")
    trigger = amendment.get("trigger")
    expected_trigger = {
        "screened_projects", "qualifying_test_projects", "qualifying_test_tasks",
        "largest_project_id", "largest_project_tasks", "observed_largest_project_share",
        "original_maximum_project_share", "final_manifest_existed",
        "provider_calls_observed",
    }
    if not isinstance(trigger, dict) or set(trigger) != expected_trigger:
        raise ValueError("v2 项目占比修订触发证据不完整")
    if (
        trigger.get("screened_projects") != 6
        or trigger.get("qualifying_test_projects") != 5
        or trigger.get("qualifying_test_tasks") != 254
        or trigger.get("largest_project_id") != "physlean"
        or trigger.get("largest_project_tasks") != 94
        or abs(float(trigger.get("observed_largest_project_share", -1)) - 94 / 254) > 1e-12
        or trigger.get("original_maximum_project_share")
        != contract["selection"]["maximum_test_project_task_share"]
        or trigger.get("final_manifest_existed") is not False
        or trigger.get("provider_calls_observed") != 0
    ):
        raise ValueError("v2 项目占比修订触发证据与六项目结果不一致")
    decision = amendment.get("decision")
    expected_decision = {
        "effective_maximum_project_share", "reason",
        "preserve_all_existing_admitted_tasks", "performance_blind_to_provider_outputs",
        "all_other_selection_thresholds_unchanged",
        "con_nf_candidate_scan_excluded_from_final_inventory", "future_claim_requirement",
    }
    if not isinstance(decision, dict) or set(decision) != expected_decision:
        raise ValueError("v2 项目占比修订决定字段不完整")
    if (
        decision.get("effective_maximum_project_share") != 0.4
        or not isinstance(decision.get("reason"), str)
        or not decision["reason"].strip()
        or decision.get("preserve_all_existing_admitted_tasks") is not True
        or decision.get("performance_blind_to_provider_outputs") is not True
        or decision.get("all_other_selection_thresholds_unchanged") is not True
        or decision.get("con_nf_candidate_scan_excluded_from_final_inventory") is not True
    ):
        raise ValueError("v2 项目占比修订不得改变其他规则或依赖 provider 表现")
    effective = json.loads(json.dumps(contract))
    effective["selection"]["maximum_test_project_task_share"] = 0.4
    return effective


def validate_enrollment_preregistration(
    preregistration: dict[str, Any], contract: dict[str, Any], config: dict[str, Any],
) -> None:
    required = {
        "version", "status", "planned_experiment_family", "registered_at_utc",
        "registration_medium", "benchmark_contract", "causal_config", "design",
        "primary_analysis", "secondary_analyses", "stopping_rule", "analysis_plan",
        "amendment_policy", "claim_gate",
    }
    if set(preregistration) != required or preregistration.get("version") != ENROLLMENT_PREREGISTRATION_VERSION:
        raise ValueError("v2 纳入预注册版本或顶层字段不匹配")
    if preregistration.get("status") != "frozen-before-test-project-enrollment":
        raise ValueError("v2 纳入预注册状态无效")
    if preregistration.get("planned_experiment_family") != "tracer-real-causal-v2":
        raise ValueError("v2 实验族名称发生漂移")
    if preregistration.get("benchmark_contract") != "benchmarks/real_repairs/tracer_real_v2.enrollment.json":
        raise ValueError("v2 纳入合同路径发生漂移")
    if preregistration.get("causal_config") != "experiments/causal_feedback.tracer_real_v2.json":
        raise ValueError("v2 因果配置路径发生漂移")

    design = preregistration.get("design")
    expected_design = {
        "protocol_version": "tracer-causal-feedback-v1",
        "arms": list(CAUSAL_ARMS),
        "repeats": config.get("repeats"),
        "branch_attempts": config.get("branch_attempts"),
        "benchmark_splits": config.get("benchmark_splits"),
        "order_seed": config.get("order_seed"),
        "compile_timeout": config.get("compile_timeout"),
        "prompt_files": ["prompts/causal_seed.txt", "prompts/causal_branch.txt", "prompts/proof_contract.txt"],
    }
    if design != expected_design:
        raise ValueError("v2 纳入预注册与因果配置不一致")
    primary = preregistration.get("primary_analysis") or {}
    if primary.get("contrast") != "true_structured - content_free_retry":
        raise ValueError("v2 主对比必须唯一冻结为 structured 对 content-free retry")
    if primary.get("project_weighting") != "equal_weight_per_test_project":
        raise ValueError("v2 主分析必须按测试项目等权")
    claim_gate = preregistration.get("claim_gate") or {}
    selection = contract["selection"]
    expected_gate = {
        "minimum_test_projects": selection["minimum_test_projects"],
        "minimum_test_tasks": selection["minimum_test_tasks"],
        "minimum_total_tasks": selection["minimum_total_tasks"],
        "minimum_eligible_first_failures": 30,
        "final_runtime_preregistration_required": True,
        "confirmatory_claim_allowed_before_final_freeze": False,
    }
    if claim_gate != expected_gate:
        raise ValueError("v2 结论门禁与纳入合同不一致")
    stopping = preregistration.get("stopping_rule") or {}
    if stopping.get("provider_calls_before_final_freeze") != 0:
        raise ValueError("v2 最终冻结前 provider 调用数必须为零")
    if stopping.get("performance_based_stopping") is not False:
        raise ValueError("v2 不允许按中间效果提前停止")


def validate_candidate_inventory(inventory: dict[str, Any], contract: dict[str, Any]) -> None:
    """核对在历史扫描前冻结的候选项目、端点和确定性窗口。"""

    base_required = {
        "version", "status", "registered_at_utc", "enrollment_contract",
        "history_policy", "projects", "provider_calls_observed", "replacement_policy",
    }
    version = inventory.get("version")
    if version == CANDIDATE_INVENTORY_VERSION:
        required = base_required
        expected_status = "frozen-before-candidate-history-scan"
    elif version == CANDIDATE_INVENTORY_AMENDED_VERSION:
        required = base_required | {"base_candidate_inventory", "amendment_preregistration"}
        expected_status = "frozen-before-amended-project-history-scan"
        if inventory.get("base_candidate_inventory") != "benchmarks/real_repairs/tracer_real_v2.candidates.json":
            raise ValueError("v2 修订候选清单没有指向原始候选清单")
        if inventory.get("amendment_preregistration") != (
            "experiments/preregistrations/tracer_real_v2_enrollment_amendment1.json"
        ):
            raise ValueError("v2 修订候选清单没有指向公开修订预注册")
    else:
        raise ValueError("v2 候选项目清单版本无效")
    if set(inventory) != required:
        raise ValueError("v2 候选项目清单版本或顶层字段不匹配")
    if inventory.get("status") != expected_status:
        raise ValueError("v2 候选项目必须在历史扫描前冻结")
    if inventory.get("enrollment_contract") != "benchmarks/real_repairs/tracer_real_v2.enrollment.json":
        raise ValueError("v2 候选项目清单指向错误的纳入合同")
    if inventory.get("provider_calls_observed") != 0:
        raise ValueError("v2 候选登记前不得存在 provider 调用")
    policy = inventory.get("history_policy")
    expected_policy_fields = {
        "traversal", "maximum_commits", "endpoint_policy", "candidate_rule",
        "screen_policy", "performance_blind",
    }
    if not isinstance(policy, dict) or set(policy) != expected_policy_fields:
        raise ValueError("v2 候选历史窗口策略字段不完整")
    if policy.get("traversal") != "first_parent":
        raise ValueError("v2 候选扫描必须使用固定 first-parent 窗口")
    if type(policy.get("maximum_commits")) is not int or policy["maximum_commits"] <= 0:
        raise ValueError("v2 候选扫描窗口必须为正整数")
    if policy.get("performance_blind") is not True:
        raise ValueError("v2 候选项目登记必须与 provider 表现隔离")
    projects = inventory.get("projects")
    if not isinstance(projects, list) or len(projects) < contract["selection"]["minimum_test_projects"]:
        raise ValueError("v2 候选项目数低于冻结测试项目门槛")
    required_project_fields = {
        "project_id", "source_repository", "source_license", "endpoint_revision", "lean_toolchain",
    }
    ids: set[str] = set()
    repositories: set[str] = set()
    excluded_ids = set(contract["selection"]["excluded_test_project_ids"])
    excluded_repositories = {
        canonical_repository(value) for value in contract["selection"]["excluded_test_repositories"]
    }
    for project in projects:
        if not isinstance(project, dict) or set(project) != required_project_fields:
            raise ValueError("v2 候选项目字段不完整")
        project_id = project.get("project_id")
        repository = project.get("source_repository")
        canonical = canonical_repository(repository)
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9_]+", project_id):
            raise ValueError("v2 候选项目 ID 非法")
        if project_id in ids or project_id in excluded_ids:
            raise ValueError("v2 候选项目 ID 重复或复用 v1 项目")
        if not _https_repository(repository) or canonical in repositories or canonical in excluded_repositories:
            raise ValueError("v2 候选项目来源非法、重复或复用 v1 上游仓库")
        if not isinstance(project.get("source_license"), str) or not project["source_license"].strip():
            raise ValueError("v2 候选项目许可证不能为空")
        if not re.fullmatch(r"[0-9a-f]{40}", str(project.get("endpoint_revision"))):
            raise ValueError("v2 候选项目端点版本必须是完整 Git revision")
        if not isinstance(project.get("lean_toolchain"), str) or not project["lean_toolchain"].strip():
            raise ValueError("v2 候选项目 Lean 工具链不能为空")
        ids.add(project_id)
        repositories.add(canonical)


def _repository_relative_path(value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("v2 修订只能引用仓库内相对路径")
    return ROOT / path


def validate_enrollment_amendment(
    amendment: dict[str, Any], base_inventory: dict[str, Any],
    amended_inventory: dict[str, Any], contract: dict[str, Any],
) -> None:
    """核对项目占比失败后追加、且先于新增历史扫描冻结的公开修订。"""

    required = {
        "version", "status", "registered_at_utc", "amends", "base_candidate_inventory",
        "trigger", "added_project", "selection_policy", "provider_calls_observed",
    }
    if set(amendment) != required or amendment.get("version") != ENROLLMENT_AMENDMENT_VERSION:
        raise ValueError("v2 纳入修订版本或顶层字段不匹配")
    if amendment.get("status") != "frozen-before-amended-project-history-scan":
        raise ValueError("v2 纳入修订必须先于新增项目历史扫描冻结")
    if amendment.get("amends") != "experiments/preregistrations/tracer_real_causal_v2_enrollment.json":
        raise ValueError("v2 纳入修订没有指向原始预注册")
    if amendment.get("base_candidate_inventory") != "benchmarks/real_repairs/tracer_real_v2.candidates.json":
        raise ValueError("v2 纳入修订没有指向原始候选清单")
    if amendment.get("provider_calls_observed") != 0:
        raise ValueError("v2 纳入修订前不得存在 provider 调用")
    validate_candidate_inventory(base_inventory, contract)
    if base_inventory.get("version") != CANDIDATE_INVENTORY_VERSION:
        raise ValueError("v2 纳入修订的基线候选清单版本无效")

    trigger = amendment.get("trigger")
    expected_trigger_fields = {
        "screened_projects", "qualifying_test_projects", "qualifying_test_tasks",
        "largest_project_id", "largest_project_tasks", "observed_largest_project_share",
        "frozen_maximum_project_share", "minimum_additional_admissible_tasks",
        "final_manifest_existed", "provider_calls_observed",
    }
    if not isinstance(trigger, dict) or set(trigger) != expected_trigger_fields:
        raise ValueError("v2 纳入修订触发证据字段不完整")
    expected_share = 94 / 254
    if (
        trigger.get("screened_projects") != 6
        or trigger.get("qualifying_test_projects") != 5
        or trigger.get("qualifying_test_tasks") != 254
        or trigger.get("largest_project_id") != "physlean"
        or trigger.get("largest_project_tasks") != 94
        or abs(float(trigger.get("observed_largest_project_share", -1)) - expected_share) > 1e-12
        or trigger.get("frozen_maximum_project_share")
        != contract["selection"]["maximum_test_project_task_share"]
        or trigger.get("minimum_additional_admissible_tasks") != 15
        or trigger.get("final_manifest_existed") is not False
        or trigger.get("provider_calls_observed") != 0
    ):
        raise ValueError("v2 纳入修订触发证据与六项目门禁结果不一致")

    policy = amendment.get("selection_policy")
    expected_policy_fields = {
        "reason", "history_traversal", "maximum_commits", "include_all_admissible_repairs",
        "performance_blind", "preserve_all_existing_admitted_tasks",
        "maximum_project_share_unchanged", "minimum_new_admissible_tasks_target",
        "if_target_not_met",
    }
    if not isinstance(policy, dict) or set(policy) != expected_policy_fields:
        raise ValueError("v2 纳入修订选择策略字段不完整")
    if (
        policy.get("history_traversal") != base_inventory["history_policy"]["traversal"]
        or policy.get("maximum_commits") != base_inventory["history_policy"]["maximum_commits"]
        or policy.get("include_all_admissible_repairs") is not True
        or policy.get("performance_blind") is not True
        or policy.get("preserve_all_existing_admitted_tasks") is not True
        or policy.get("maximum_project_share_unchanged") is not True
        or policy.get("minimum_new_admissible_tasks_target") != 15
    ):
        raise ValueError("v2 纳入修订选择策略改变既有门槛或允许事后挑题")

    base_projects = base_inventory["projects"]
    amended_projects = amended_inventory["projects"]
    if amended_projects[:len(base_projects)] != base_projects or len(amended_projects) != len(base_projects) + 1:
        raise ValueError("v2 修订候选清单必须原样保留六个既有项目并只追加一个项目")
    if amendment.get("added_project") != amended_projects[-1]:
        raise ValueError("v2 修订预注册与新增候选项目不一致")


def validate_candidate_scans(
    inventory: dict[str, Any], scan_dir: Path,
) -> dict[str, Any]:
    """核对所有冻结项目的确定性扫描输出与登记端点完全一致。"""

    expected = {project["project_id"]: project for project in inventory["projects"]}
    files = sorted(scan_dir.glob("*.inventory.json")) if scan_dir.is_dir() else []
    if {path.stem.removesuffix(".inventory") for path in files} != set(expected):
        raise ValueError("v2 候选扫描文件没有唯一覆盖全部冻结项目")
    total = 0
    candidate_ids: set[str] = set()
    per_project: dict[str, int] = {}
    for path in files:
        scan = read_json(path)
        project_id = scan.get("project_id")
        project = expected.get(project_id)
        if project is None or scan.get("version") != CANDIDATE_SCAN_VERSION:
            raise ValueError("v2 候选扫描版本或项目不匹配")
        if scan.get("status") != "deterministic-history-scan":
            raise ValueError("v2 候选扫描状态无效")
        if canonical_repository(scan.get("source_repository")) != canonical_repository(project["source_repository"]):
            raise ValueError("v2 候选扫描上游来源与冻结清单不一致")
        if scan.get("source_license") != project["source_license"]:
            raise ValueError("v2 候选扫描许可证与冻结清单不一致")
        if scan.get("endpoint_revision") != project["endpoint_revision"]:
            raise ValueError("v2 候选扫描端点与冻结清单不一致")
        policy = scan.get("history_policy") or {}
        if (
            policy.get("traversal") != inventory["history_policy"]["traversal"]
            or policy.get("maximum_commits") != inventory["history_policy"]["maximum_commits"]
        ):
            raise ValueError("v2 候选扫描窗口与冻结清单不一致")
        candidates = scan.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("v2 候选扫描缺少候选列表")
        for candidate in candidates:
            candidate_id = candidate.get("id") if isinstance(candidate, dict) else None
            if not isinstance(candidate_id, str) or candidate_id in candidate_ids:
                raise ValueError("v2 候选扫描含非法或重复任务 ID")
            if candidate.get("fixed_revision") != project["endpoint_revision"]:
                raise ValueError("v2 候选任务未使用冻结项目端点")
            candidate_ids.add(candidate_id)
        per_project[project_id] = len(candidates)
        total += len(candidates)
    return {"candidate_scans": len(files), "history_candidates": total, "per_project": per_project}


def validate_candidate_screen_reports(
    inventory: dict[str, Any], scan_dir: Path, screen_dir: Path,
    *, require_complete: bool = False,
) -> dict[str, Any]:
    """逐项核对公开筛查决定，防止只发布通过项或改写冻结候选。"""

    expected_projects = {project["project_id"]: project for project in inventory["projects"]}
    scans: dict[str, dict[str, Any]] = {}
    for path in sorted(scan_dir.glob("*.inventory.json")) if scan_dir.is_dir() else []:
        scan = read_json(path)
        project_id = scan.get("project_id")
        if not isinstance(project_id, str) or project_id in scans:
            raise ValueError("v2 候选扫描项目非法或重复")
        scans[project_id] = scan

    files = sorted(screen_dir.glob("*.screen.json")) if screen_dir.is_dir() else []
    seen: set[str] = set()
    accepted_total = 0
    rejected_total = 0
    candidate_total = 0
    per_project: dict[str, dict[str, int]] = {}
    for path in files:
        report = read_json(path)
        project_id = report.get("project_id")
        if project_id not in expected_projects or project_id in seen:
            raise ValueError("v2 筛查报告含未知或重复项目")
        if report.get("version") != CANDIDATE_SCREEN_VERSION:
            raise ValueError("v2 筛查报告版本不匹配")
        project = expected_projects[project_id]
        if report.get("endpoint_revision") != project["endpoint_revision"]:
            raise ValueError("v2 筛查报告端点与冻结清单不一致")
        if report.get("provider_calls_observed") != 0:
            raise ValueError("v2 候选筛查阶段不得发生 provider 调用")
        scan = scans.get(project_id)
        if scan is None:
            raise ValueError("v2 筛查报告缺少对应的冻结候选扫描")
        candidates = scan.get("candidates")
        decisions = report.get("decisions")
        if not isinstance(candidates, list) or not isinstance(decisions, list):
            raise ValueError("v2 筛查报告或候选扫描缺少列表")
        candidate_ids = [row.get("id") for row in candidates if isinstance(row, dict)]
        decision_ids = [row.get("id") for row in decisions if isinstance(row, dict)]
        if (
            len(candidate_ids) != len(candidates)
            or len(decision_ids) != len(decisions)
            or len(set(decision_ids)) != len(decision_ids)
            or set(decision_ids) != set(candidate_ids)
        ):
            raise ValueError("v2 筛查决定没有唯一覆盖对应冻结候选")
        accepted = 0
        for decision in decisions:
            if decision.get("accepted") is True:
                if not isinstance(decision.get("error_category"), str):
                    raise ValueError("v2 接受决定缺少错误类别")
                accepted += 1
            elif decision.get("accepted") is False:
                if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                    raise ValueError("v2 拒绝决定缺少可读理由")
            else:
                raise ValueError("v2 筛查决定缺少布尔接受状态")
        rejected = len(decisions) - accepted
        if (
            report.get("candidates") != len(candidates)
            or report.get("accepted") != accepted
            or report.get("rejected") != rejected
            or report.get("selection_policy")
            != "all candidates passing the preregistered real-repair compile gate"
        ):
            raise ValueError("v2 筛查报告汇总与逐项决定不一致")
        per_project[project_id] = {
            "candidates": len(candidates), "accepted": accepted, "rejected": rejected,
        }
        candidate_total += len(candidates)
        accepted_total += accepted
        rejected_total += rejected
        seen.add(project_id)

    if require_complete and seen != set(expected_projects):
        raise ValueError("最终 v2 题库冻结前必须公开全部候选项目的完整筛查报告")
    return {
        "screened_projects": len(seen),
        "screened_candidates": candidate_total,
        "accepted_repairs": accepted_total,
        "rejected_candidates": rejected_total,
        "per_project_screening": per_project,
    }


def validate_v2_benchmark(
    benchmark: dict[str, Any], contract: dict[str, Any],
    candidate_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """核对最终 v2 manifest 是否达到预注册纳入门槛。"""

    validate_contract(contract)
    if candidate_inventory is not None:
        validate_candidate_inventory(candidate_inventory, contract)
    if benchmark.get("version") != contract["benchmark_version"]:
        raise ValueError("最终题库版本与 v2 纳入合同不一致")
    if benchmark.get("status") != "frozen-project-disjoint-real-history":
        raise ValueError("最终 v2 题库必须是已冻结的真实历史修复集")
    if benchmark.get("split_policy") != contract["split_policy"]:
        raise ValueError("最终 v2 项目划分策略发生漂移")
    projects, problems = benchmark.get("projects"), benchmark.get("problems")
    environments = benchmark.get("project_environments")
    if not isinstance(projects, list) or not isinstance(problems, list) or not isinstance(environments, list):
        raise ValueError("最终 v2 清单缺少项目、题目或项目编译环境")

    project_by_id: dict[str, dict[str, Any]] = {}
    repositories: set[str] = set()
    for project in projects:
        required = {
            "project_id", "split", "source_benchmark_version", "source_repository", "tasks",
        }
        if set(project) != required:
            raise ValueError("最终 v2 项目字段不完整")
        project_id = project.get("project_id")
        repository = project.get("source_repository")
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9_]+", project_id):
            raise ValueError("最终 v2 项目 ID 非法")
        if project_id in project_by_id:
            raise ValueError("最终 v2 项目 ID 重复")
        if project.get("split") not in PROJECT_SPLITS:
            raise ValueError("最终 v2 项目划分非法")
        if type(project.get("tasks")) is not int or project["tasks"] <= 0:
            raise ValueError("最终 v2 项目题数无效")
        if not _https_repository(repository):
            raise ValueError("最终 v2 上游仓库必须是无凭据 HTTPS 地址")
        repository_identity = canonical_repository(repository)
        if repository_identity in repositories:
            raise ValueError("同一上游仓库不得以别名重复进入 v2")
        repositories.add(repository_identity)
        project_by_id[project_id] = project

    environment_ids: set[str] = set()
    for environment in environments:
        if set(environment) != {"project_id", "project_root", "lean_toolchain"}:
            raise ValueError("最终 v2 项目编译环境字段不完整")
        project_id = environment.get("project_id")
        if project_id not in project_by_id or project_id in environment_ids:
            raise ValueError("最终 v2 项目编译环境引用未知或重复项目")
        root = Path(str(environment.get("project_root", "")))
        if not root.parts or root.is_absolute() or ".." in root.parts:
            raise ValueError("最终 v2 项目编译根必须是仓库内相对路径")
        toolchain = environment.get("lean_toolchain")
        if not isinstance(toolchain, str) or not toolchain.strip():
            raise ValueError("最终 v2 项目编译环境缺少 lean-toolchain")
        environment_ids.add(project_id)
    if environment_ids != set(project_by_id):
        raise ValueError("最终 v2 必须为每个项目冻结唯一编译环境")

    counts: Counter[str] = Counter()
    test_categories: set[str] = set()
    seen_problem_ids: set[str] = set()
    for problem in problems:
        problem_id = problem.get("id")
        project_id = problem.get("project_id")
        if not isinstance(problem_id, str) or not problem_id or problem_id in seen_problem_ids:
            raise ValueError("最终 v2 题目 ID 缺失或重复")
        if project_id not in project_by_id:
            raise ValueError("最终 v2 题目引用未知项目")
        project = project_by_id[project_id]
        if problem.get("split") != project["split"]:
            raise ValueError("最终 v2 题目划分与项目划分不一致")
        if problem.get("source_benchmark_version") != project["source_benchmark_version"]:
            raise ValueError("最终 v2 题目来源版本与项目记录不一致")
        provenance = problem.get("provenance") or {}
        if provenance.get("source_repository") != project["source_repository"]:
            raise ValueError("最终 v2 题目来源仓库与项目记录不一致")
        for field in ("statement_unchanged", "initial_failure_reproduced", "fixed_proof_recompiled"):
            if provenance.get(field) is not True:
                raise ValueError("最终 v2 题目未通过真实历史修复门禁：" + problem_id)
        if "real_history" not in (problem.get("tags") or []):
            raise ValueError("最终 v2 题目必须明确标记 real_history")
        counts[project_id] += 1
        if project["split"] == "test":
            category = problem.get("expected_error")
            if not isinstance(category, str) or not category:
                raise ValueError("最终 v2 测试题缺少预期错误类别")
            test_categories.add(category)
        seen_problem_ids.add(problem_id)

    for project_id, project in project_by_id.items():
        if counts[project_id] != project["tasks"]:
            raise ValueError("最终 v2 项目题数与实际题目不一致：" + project_id)

    selection = contract["selection"]
    test_projects = [project for project in projects if project["split"] == "test"]
    test_tasks = sum(project["tasks"] for project in test_projects)
    if len(projects) < selection["minimum_projects_total"]:
        raise ValueError("最终 v2 独立项目数未达到预注册门槛")
    if len(test_projects) < selection["minimum_test_projects"]:
        raise ValueError("最终 v2 测试项目数未达到预注册门槛")
    if len(problems) < selection["minimum_total_tasks"]:
        raise ValueError("最终 v2 总题数未达到预注册门槛")
    if test_tasks < selection["minimum_test_tasks"]:
        raise ValueError("最终 v2 测试题数未达到预注册门槛")
    excluded = set(selection["excluded_test_project_ids"])
    if any(project["project_id"] in excluded for project in test_projects):
        raise ValueError("v1 已使用项目不得进入 v2 确认性测试集")
    excluded_repositories = {
        canonical_repository(value) for value in selection["excluded_test_repositories"]
    }
    if any(canonical_repository(project["source_repository"]) in excluded_repositories for project in test_projects):
        raise ValueError("v1 已使用上游仓库不得改名后进入 v2 确认性测试集")
    if any(project["tasks"] < selection["minimum_tasks_per_test_project"] for project in test_projects):
        raise ValueError("最终 v2 单个测试项目题数未达到预注册门槛")
    if any(project["tasks"] / test_tasks > selection["maximum_test_project_task_share"] for project in test_projects):
        raise ValueError("最终 v2 测试任务被单个项目过度主导")
    if candidate_inventory is not None:
        candidates = {row["project_id"]: row for row in candidate_inventory["projects"]}
        for project in test_projects:
            candidate = candidates.get(project["project_id"])
            if candidate is None:
                raise ValueError("最终 v2 测试项目不在冻结候选清单中")
            if canonical_repository(project["source_repository"]) != canonical_repository(candidate["source_repository"]):
                raise ValueError("最终 v2 测试项目与冻结候选来源不一致")
            fixed_revisions = {
                problem["provenance"].get("fixed_revision")
                for problem in problems if problem["project_id"] == project["project_id"]
            }
            if fixed_revisions != {candidate["endpoint_revision"]}:
                raise ValueError("最终 v2 测试题未统一使用冻结候选端点")
    if len(test_categories) < selection["minimum_test_error_categories"]:
        raise ValueError("最终 v2 测试错误类别数未达到预注册门槛")

    return {
        "ready": True,
        "benchmark_version": benchmark["version"],
        "projects": len(projects),
        "test_projects": len(test_projects),
        "tasks": len(problems),
        "test_tasks": test_tasks,
        "test_error_categories": len(test_categories),
    }


def build_final_preregistration(
    contract: dict[str, Any], enrollment: dict[str, Any], config: dict[str, Any],
    benchmark: dict[str, Any], *, experiment_id: str, registered_at_utc: str,
    candidate_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在最终 manifest 通过门禁后生成 runner 可读取的精确预注册。"""

    validate_enrollment_preregistration(enrollment, contract, config)
    counts = validate_v2_benchmark(benchmark, contract, candidate_inventory)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", experiment_id):
        raise ValueError("v2 正式实验 ID 非法")
    model_fields = ("id", "model", "api_url", "temperature", "max_tokens", "thinking", "reasoning_effort")
    models = [{field: model.get(field) for field in model_fields} for model in config["models"]]
    seed_generations = counts["test_tasks"] * config["repeats"] * len(models)
    branch_generations = seed_generations * len(CAUSAL_ARMS)
    return {
        "version": FINAL_PREREGISTRATION_VERSION,
        "status": "frozen-before-provider-run",
        "planned_experiment_id": experiment_id,
        "registered_at_utc": registered_at_utc,
        "registration_medium": "版本控制仓库中的机器可读最终预注册；由原始 v2 纳入合同与 provider 前公开的项目占比修订共同生成。",
        "benchmark": {
            "version": benchmark["version"],
            "split_policy": benchmark["split_policy"],
            "projects": [
                {"project_id": row["project_id"], "split": row["split"], "tasks": row["tasks"]}
                for row in benchmark["projects"]
            ],
        },
        "models": models,
        "design": enrollment["design"],
        "primary_analysis": enrollment["primary_analysis"],
        "secondary_analyses": enrollment["secondary_analyses"],
        "stopping_rule": {
            "maximum_seed_generations": seed_generations,
            "maximum_branch_generations": branch_generations,
            "maximum_provider_calls": seed_generations + branch_generations,
            "adaptive_early_stopping": False,
            "transport_policy": "传输状态不明时停止并人工核对；不得删除异常后重写同一预注册批次。",
        },
        "claim_gate": {
            "minimum_test_projects": contract["selection"]["minimum_test_projects"],
            "minimum_test_tasks": contract["selection"]["minimum_test_tasks"],
            "maximum_test_project_task_share": contract["selection"]["maximum_test_project_task_share"],
            "share_gate_amendment": "experiments/preregistrations/tracer_real_v2_share_gate_amendment2.json",
            "minimum_eligible_first_failures": enrollment["claim_gate"]["minimum_eligible_first_failures"],
            "confirmatory_claim_allowed": True,
            "required_label": "达到样本门槛后仍须通过完整轨迹、基础设施与统计审计，方可报告预注册确认性结果。",
        },
    }


def audit_enrollment(
    contract_path: Path, preregistration_path: Path, config_path: Path,
    benchmark_path: Path | None = None,
    candidate_path: Path = ROOT / "benchmarks/real_repairs/tracer_real_v2.candidates.json",
    scan_dir: Path = ROOT / "benchmarks/real_repairs/tracer_real_v2_candidates",
    screen_dir: Path = ROOT / "benchmarks/real_repairs/tracer_real_v2_screening",
    share_gate_amendment_path: Path | None = SHARE_GATE_AMENDMENT_PATH,
) -> dict[str, Any]:
    base_contract = read_json(contract_path)
    contract = (
        apply_share_gate_amendment(base_contract, read_json(share_gate_amendment_path))
        if share_gate_amendment_path is not None else base_contract
    )
    enrollment = read_json(preregistration_path)
    from causal_feedback import validate_config

    config = validate_config(config_path)
    validate_contract(base_contract)
    validate_enrollment_preregistration(enrollment, contract, config)
    candidates = read_json(candidate_path)
    validate_candidate_inventory(candidates, contract)
    if candidates.get("version") == CANDIDATE_INVENTORY_AMENDED_VERSION:
        base_inventory = read_json(_repository_relative_path(candidates["base_candidate_inventory"]))
        amendment = read_json(_repository_relative_path(candidates["amendment_preregistration"]))
        validate_enrollment_amendment(amendment, base_inventory, candidates, contract)
    scan_summary = validate_candidate_scans(candidates, scan_dir)
    screen_summary = validate_candidate_screen_reports(
        candidates, scan_dir, screen_dir, require_complete=benchmark_path is not None,
    )
    final_path = ROOT / contract["provider_gate"]["required_runtime_preregistration"]
    result = {
        "ok": True,
        "status": "enrollment_preregistered",
        "benchmark_version": contract["benchmark_version"],
        "provider_calls_allowed": False,
        "final_runtime_preregistration_exists": final_path.is_file(),
        "candidate_projects_frozen": len(candidates["projects"]),
        "enrollment_amendment": candidates.get("amendment_preregistration"),
        "share_gate_amendment": (
            str(share_gate_amendment_path.relative_to(ROOT)).replace("\\", "/")
            if share_gate_amendment_path is not None else None
        ),
        "effective_maximum_test_project_task_share": contract["selection"]["maximum_test_project_task_share"],
        "candidate_history_window": candidates["history_policy"]["maximum_commits"],
        **scan_summary,
        **screen_summary,
    }
    if benchmark_path is None:
        result["ready_for_provider_run"] = False
        result["next_gate"] = "纳入并验证至少五个全新测试项目，再冻结最终 manifest 与运行时预注册。"
        return result
    benchmark = read_json(benchmark_path)
    result.update(validate_v2_benchmark(benchmark, contract, candidates))
    if final_path.is_file():
        from causal_feedback import validate_preregistration_record

        validate_preregistration_record(read_json(final_path), config, benchmark)
        result["ready_for_provider_run"] = True
        result["provider_calls_allowed"] = True
    else:
        result["ready_for_provider_run"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="核对 v2 纳入预注册；不调用 provider")
    audit.add_argument("--contract", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json")
    audit.add_argument("--preregistration", type=Path, default=ROOT / "experiments/preregistrations/tracer_real_causal_v2_enrollment.json")
    audit.add_argument("--config", type=Path, default=ROOT / "experiments/causal_feedback.tracer_real_v2.json")
    audit.add_argument("--candidates", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2.candidates.json")
    audit.add_argument("--share-gate-amendment", type=Path, default=SHARE_GATE_AMENDMENT_PATH)
    audit.add_argument("--candidate-scans", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2_candidates")
    audit.add_argument("--candidate-screening", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2_screening")
    audit.add_argument("--benchmark", type=Path)
    finalize = sub.add_parser("finalize", help="通过纳入门禁后生成最终运行时预注册；不调用 provider")
    finalize.add_argument("--contract", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2.enrollment.json")
    finalize.add_argument("--preregistration", type=Path, default=ROOT / "experiments/preregistrations/tracer_real_causal_v2_enrollment.json")
    finalize.add_argument("--config", type=Path, default=ROOT / "experiments/causal_feedback.tracer_real_v2.json")
    finalize.add_argument("--candidates", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2.candidates.json")
    finalize.add_argument("--share-gate-amendment", type=Path, default=SHARE_GATE_AMENDMENT_PATH)
    finalize.add_argument("--candidate-scans", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2_candidates")
    finalize.add_argument("--candidate-screening", type=Path, default=ROOT / "benchmarks/real_repairs/tracer_real_v2_screening")
    finalize.add_argument("--benchmark", type=Path, required=True)
    finalize.add_argument("--experiment-id", required=True)
    finalize.add_argument("--out", type=Path, default=ROOT / "experiments/preregistrations/tracer_real_causal_v2.json")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            result = audit_enrollment(
                args.contract, args.preregistration, args.config, args.benchmark,
                args.candidates, args.candidate_scans, args.candidate_screening,
                args.share_gate_amendment,
            )
        else:
            if args.out.exists():
                raise ValueError("最终运行时预注册已存在；拒绝覆盖")
            base_contract = read_json(args.contract)
            contract = apply_share_gate_amendment(
                base_contract, read_json(args.share_gate_amendment),
            )
            enrollment = read_json(args.preregistration)
            from causal_feedback import validate_config, validate_preregistration_record

            config = validate_config(args.config)
            candidates = read_json(args.candidates)
            validate_candidate_inventory(candidates, contract)
            if candidates.get("version") == CANDIDATE_INVENTORY_AMENDED_VERSION:
                base_inventory = read_json(_repository_relative_path(candidates["base_candidate_inventory"]))
                amendment = read_json(_repository_relative_path(candidates["amendment_preregistration"]))
                validate_enrollment_amendment(amendment, base_inventory, candidates, contract)
            validate_candidate_scans(candidates, args.candidate_scans)
            validate_candidate_screen_reports(
                candidates, args.candidate_scans, args.candidate_screening,
                require_complete=True,
            )
            benchmark = read_json(args.benchmark)
            result = build_final_preregistration(
                contract, enrollment, config, benchmark,
                experiment_id=args.experiment_id,
                registered_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                candidate_inventory=candidates,
            )
            validate_preregistration_record(result, config, benchmark)
            write_json(args.out, result)
            result = {"ok": True, "out": str(args.out), "provider_calls_allowed": True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
