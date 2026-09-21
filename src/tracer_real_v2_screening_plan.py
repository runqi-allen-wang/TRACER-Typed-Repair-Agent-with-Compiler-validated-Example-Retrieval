"""审计 TRACER-REAL v2 剩余筛查计划；不下载依赖、不运行 Lean、不调用 provider。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN_VERSION = "tracer-real-v2-screening-plan-v1"
PLAN_PATH = ROOT / "experiments/tracer_real_v2_screening.plan.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _resolve(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("筛查计划只允许仓库内相对路径")
    return ROOT / path


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    required = {
        "version", "status", "enrollment_contract", "candidate_inventory", "candidate_scan_root",
        "published_report_root", "working_root", "repository_root",
        "completed_before_plan", "screening_order", "execution",
        "ordering_rationale", "provider_calls_allowed",
    }
    if set(plan) != required or plan.get("version") != PLAN_VERSION:
        raise ValueError("V2 筛查计划版本或顶层字段不匹配")
    if plan.get("status") != "operational-plan-no-provider-calls":
        raise ValueError("V2 筛查计划状态无效")
    if plan.get("provider_calls_allowed") is not False:
        raise ValueError("V2 候选筛查不得调用 provider")
    execution = plan.get("execution")
    expected_execution = {
        "workers": 1,
        "timeout_seconds": 180,
        "refuse_while_research_runner_active": True,
        "checkpoint_after_each_candidate": True,
        "publish_report_only_after_complete_screen": True,
    }
    if execution != expected_execution:
        raise ValueError("V2 筛查执行策略发生漂移")

    contract = read_json(_resolve(plan["enrollment_contract"]))
    selection = contract.get("selection")
    if not isinstance(selection, dict):
        raise ValueError("V2 纳入合同缺少 selection")
    inventory = read_json(_resolve(plan["candidate_inventory"]))
    projects = {row["project_id"]: row for row in inventory.get("projects", [])}
    scans: dict[str, dict[str, Any]] = {}
    scan_root = _resolve(plan["candidate_scan_root"])
    for path in scan_root.glob("*.inventory.json"):
        scan = read_json(path)
        project_id = scan.get("project_id")
        if not isinstance(project_id, str) or project_id in scans:
            raise ValueError("候选扫描含未知或重复项目")
        scans[project_id] = scan
    if set(scans) != set(projects):
        raise ValueError("候选扫描没有覆盖全部冻结项目")

    completed = plan.get("completed_before_plan")
    order = plan.get("screening_order")
    if not isinstance(completed, list) or not isinstance(order, list):
        raise ValueError("V2 筛查项目列表格式错误")
    completed_ids = [row.get("project_id") for row in completed]
    ordered_ids = [row.get("project_id") for row in order]
    if completed_ids != ["leanapap", "pfr"]:
        raise ValueError("计划基线必须精确登记 LeanAPAP 与 PFR")
    if ordered_ids != ["scilean", "equational_theories", "flt", "physlean"]:
        raise ValueError("剩余筛查顺序发生漂移")
    if set(completed_ids + ordered_ids) != set(projects):
        raise ValueError("筛查计划没有唯一覆盖六个冻结项目")

    report_root = _resolve(plan["published_report_root"])
    for row in completed:
        project_id = row["project_id"]
        report = read_json(report_root / f"{project_id}.screen.json")
        expected = {
            "candidate_count": report.get("candidates"),
            "accepted": report.get("accepted"),
            "rejected": report.get("rejected"),
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError(f"{project_id} 已完成筛查基线与公开报告不一致")

    counts: list[int] = []
    for row in order:
        project_id = row["project_id"]
        project = projects[project_id]
        scan = scans[project_id]
        count = len(scan.get("candidates", []))
        if row.get("candidate_count") != count:
            raise ValueError(f"{project_id} 候选数与冻结扫描不一致")
        if row.get("endpoint_revision") != project.get("endpoint_revision"):
            raise ValueError(f"{project_id} 端点版本与冻结登记不一致")
        if row.get("lean_toolchain") != project.get("lean_toolchain"):
            raise ValueError(f"{project_id} Lean 工具链与冻结登记不一致")
        counts.append(count)
    if counts != sorted(counts):
        raise ValueError("剩余项目没有按冻结候选数升序排列")
    return {"plan": plan, "contract": contract, "projects": projects, "scans": scans}


def _enrollment_projection(validated: dict[str, Any]) -> dict[str, Any]:
    """根据已经公开的完整筛查报告描述门槛差距，不外推未筛查项目。"""

    plan = validated["plan"]
    inventory = read_json(_resolve(plan["candidate_inventory"]))
    report_root = _resolve(plan["published_report_root"])
    scan_root = _resolve(plan["candidate_scan_root"])
    from tracer_real_v2 import validate_candidate_screen_reports

    summary = validate_candidate_screen_reports(inventory, scan_root, report_root)
    selection = validated["contract"]["selection"]
    per_project = summary["per_project_screening"]
    minimum_per_project = selection["minimum_tasks_per_test_project"]
    qualifying = {
        project_id: row for project_id, row in per_project.items()
        if row["accepted"] >= minimum_per_project
    }
    accepted = sum(row["accepted"] for row in qualifying.values())
    largest = max((row["accepted"] for row in qualifying.values()), default=0)
    largest_share = largest / accepted if accepted else None
    categories: set[str] = set()
    for project_id in per_project:
        report = read_json(report_root / f"{project_id}.screen.json")
        categories.update(
            decision["error_category"] for decision in report["decisions"]
            if decision.get("accepted") is True
        )
    required_total_for_current_largest = (
        math.ceil(largest / selection["maximum_test_project_task_share"])
        if largest else 0
    )
    all_screened = summary["screened_projects"] == len(inventory["projects"])
    gates = {
        "all_frozen_projects_screened": all_screened,
        "minimum_test_projects": len(qualifying) >= selection["minimum_test_projects"],
        "minimum_test_tasks": accepted >= selection["minimum_test_tasks"],
        "maximum_test_project_share": (
            largest_share is not None
            and largest_share <= selection["maximum_test_project_task_share"]
        ),
        "minimum_test_error_categories": len(categories) >= selection["minimum_test_error_categories"],
    }
    return {
        "scope": "仅汇总已公开完整筛查报告；不外推未筛查项目，也不等同于最终题库。",
        "screened_projects": summary["screened_projects"],
        "screened_candidates": summary["screened_candidates"],
        "qualifying_test_projects": len(qualifying),
        "qualifying_project_ids": sorted(qualifying),
        "provisional_accepted_repairs": accepted,
        "provisional_error_categories": sorted(categories),
        "current_largest_project_share": largest_share,
        "additional_qualifying_projects_needed": max(
            0, selection["minimum_test_projects"] - len(qualifying),
        ),
        "minimum_additional_tasks_for_current_largest_share": max(
            0, required_total_for_current_largest - accepted,
        ),
        "gates": gates,
        "ready_to_assemble": all(gates.values()),
    }


def _repository_status(row: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    repo = repository_root / row["project_id"]
    result: dict[str, Any] = {
        "exists": repo.is_dir(),
        "endpoint_ok": False,
        "toolchain_ok": False,
        "clean": False,
        "lake_config_exists": False,
        "dependencies_prepared": False,
    }
    if not repo.is_dir():
        return result
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return result
    toolchain = repo / "lean-toolchain"
    result.update({
        "endpoint_ok": head == row["endpoint_revision"],
        "toolchain_ok": toolchain.is_file()
        and toolchain.read_text(encoding="utf-8").strip() == row["lean_toolchain"],
        "clean": dirty == "",
        "lake_config_exists": (repo / "lakefile.toml").is_file()
        or (repo / "lakefile.lean").is_file(),
        "dependencies_prepared": (repo / ".lake" / "packages").is_dir(),
    })
    return result


def build_status(plan_path: Path = PLAN_PATH, *, check_repositories: bool = False) -> dict[str, Any]:
    validated = validate_plan(read_json(plan_path))
    plan = validated["plan"]
    report_root = _resolve(plan["published_report_root"])
    working_root = _resolve(plan["working_root"])
    repository_root = _resolve(plan["repository_root"])
    rows: list[dict[str, Any]] = []
    next_project: str | None = None
    for project in plan["screening_order"]:
        project_id = project["project_id"]
        report_exists = (report_root / f"{project_id}.screen.json").is_file()
        state_path = working_root / f"{project_id}.screen-state.jsonl"
        checkpoint_count = 0
        if state_path.is_file():
            checkpoint_count = sum(1 for line in state_path.read_text(encoding="utf-8").splitlines() if line.strip())
        row = {
            **project,
            "complete": report_exists,
            "checkpoint_count": checkpoint_count,
        }
        if check_repositories:
            row["repository"] = _repository_status(project, repository_root)
        rows.append(row)
        if next_project is None and not report_exists:
            next_project = project_id
    return {
        "ok": True,
        "provider_calls": 0,
        "screened_before_plan": 327,
        "remaining_candidates": sum(row["candidate_count"] for row in rows if not row["complete"]),
        "next_project": next_project,
        "projects": rows,
        "execution": plan["execution"],
        "enrollment_projection": _enrollment_projection(validated),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--check-repositories", action="store_true")
    args = parser.parse_args()
    try:
        status = build_status(args.plan, check_repositories=args.check_repositories)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
