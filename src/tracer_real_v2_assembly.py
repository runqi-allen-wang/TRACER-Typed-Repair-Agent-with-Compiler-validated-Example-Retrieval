"""生成 TRACER-REAL v2 最终项目组合规范；只读检查，不运行 Lean 或 provider。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCREEN_PLAN = ROOT / "experiments/tracer_real_v2_screening.plan.json"
DEFAULT_OUT = ROOT / "benchmarks/real_repairs/tracer_real_v2.projects.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def compose_project_spec(
    contract: dict[str, Any], inventory: dict[str, Any], qualifying_ids: list[str],
) -> dict[str, Any]:
    """按冻结登记顺序组合 spec；不读取模型结果。"""

    candidates = {row["project_id"]: row for row in inventory["projects"]}
    projects: list[dict[str, Any]] = []
    toolchain = (ROOT / "mathlib_project/lean-toolchain").read_text(encoding="utf-8").strip()
    for row in contract["starting_inventory"]["projects"]:
        projects.append({
            "project_id": row["project_id"],
            "split": row["v2_split"],
            "manifest": row["source_manifest"].removeprefix("benchmarks/real_repairs/"),
            "compile_project_root": "mathlib_project",
            "lean_toolchain": toolchain,
        })
    for project_id in qualifying_ids:
        candidate = candidates[project_id]
        projects.append({
            "project_id": project_id,
            "split": "test",
            "manifest": f"{project_id}_v2/manifest.json",
            "compile_project_root": f"results/tracer-real-v2-screening/repos/{project_id}",
            "lean_toolchain": candidate["lean_toolchain"],
        })
    return {
        "version": "tracer-real-project-split-v2",
        "benchmark_version": contract["benchmark_version"],
        "split_policy": contract["split_policy"],
        "projects": projects,
    }


def assembly_status() -> dict[str, Any]:
    from research import load_benchmark
    from tracer_real_v2_screening_plan import build_status

    screen = build_status(SCREEN_PLAN, check_repositories=True)
    projection = screen["enrollment_projection"]
    plan = read_json(SCREEN_PLAN)
    contract = read_json(ROOT / plan["enrollment_contract"])
    inventory = read_json(ROOT / plan["candidate_inventory"])
    blockers: list[str] = []
    incomplete = [row["project_id"] for row in screen["projects"] if not row["complete"]]
    if incomplete:
        blockers.append("未完成完整筛查：" + ", ".join(incomplete))
    for gate, passed in projection["gates"].items():
        if not passed:
            blockers.append("纳入门槛未通过：" + gate)

    # 即使全部项目尚未筛查完，也持续校验已经达到项目门槛的公开子题库。
    # 最终 spec 仍由 incomplete 与 enrollment gates 阻断；这里不提前组装，
    # 只是避免把已完成项目的缺失或损坏推迟到最后一刻才发现。
    qualifying = projection["qualifying_project_ids"]
    reports_root = ROOT / plan["published_report_root"]
    missing_subsets: list[str] = []
    invalid_subsets: list[str] = []
    for project_id in qualifying:
        manifest_path = ROOT / f"benchmarks/real_repairs/{project_id}_v2/manifest.json"
        if not manifest_path.is_file():
            missing_subsets.append(project_id)
            continue
        try:
            manifest = load_benchmark(manifest_path)
            report = read_json(reports_root / f"{project_id}.screen.json")
            repositories = {
                problem.get("provenance", {}).get("source_repository")
                for problem in manifest["problems"]
            }
            candidate = next(row for row in inventory["projects"] if row["project_id"] == project_id)
            if len(manifest["problems"]) != report["accepted"] or repositories != {candidate["source_repository"]}:
                raise ValueError("题数或上游来源与完整筛查报告不一致")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            invalid_subsets.append(f"{project_id}: {error}")
    if missing_subsets:
        blockers.append("缺少已验证公开子题库：" + ", ".join(missing_subsets))
    if invalid_subsets:
        blockers.append("公开子题库无效：" + "; ".join(invalid_subsets))

    spec = compose_project_spec(contract, inventory, qualifying) if not blockers else None
    final_manifest = ROOT / "benchmarks/real_repairs/tracer_real_v2/manifest.json"
    next_command = None
    if not blockers:
        next_command = (
            "python src/tracer_real_v2.py audit "
            "--benchmark benchmarks/real_repairs/tracer_real_v2/manifest.json"
            if final_manifest.is_file() else
            "python src/real_repairs.py assemble-projects "
            "--spec benchmarks/real_repairs/tracer_real_v2.projects.json "
            "--out benchmarks/real_repairs/tracer_real_v2"
        )
    return {
        "ok": True,
        "provider_calls": 0,
        "ready": not blockers,
        "blockers": blockers,
        "qualifying_test_projects": qualifying,
        "enrollment_projection": projection,
        "final_manifest_exists": final_manifest.is_file(),
        "project_spec": spec,
        "next_command": next_command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="只读报告最终组装阻断项")
    write = sub.add_parser("write-spec", help="全部门槛通过后写入拒绝覆盖的项目组合规范")
    write.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    try:
        result = assembly_status()
        if args.command == "write-spec":
            if not result["ready"]:
                raise ValueError("最终项目组合尚未就绪：" + "；".join(result["blockers"]))
            if args.out.exists():
                raise ValueError("最终项目组合规范已存在；拒绝覆盖")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(result["project_spec"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = {**result, "written": str(args.out)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
