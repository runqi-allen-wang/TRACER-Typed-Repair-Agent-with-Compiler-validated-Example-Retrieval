"""LeanCapsule 价值评测：实际回放、源码缩减和人工定位计时。"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import time
import uuid
from collections import defaultdict
from pathlib import Path

from agent import ROOT, append_jsonl
from compiler import lean_subprocess_environment, run_lean_file
from diagnostics import normalize_diagnostics
from leancapsule.diagnostics_key import diagnostic_key
from provider import redact_sensitive_text
from research import read_json, write_json
from leancapsule.privacy import redact_value
from leancapsule.replay import replay_capsule


def text_size(text):
    return {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines()),
            "nonempty_lines": sum(bool(line.strip()) for line in text.splitlines()),
            "imports": sum(line.strip().startswith("import ") for line in text.splitlines())}


def reduction(original, reduced):
    before, after = text_size(original), text_size(reduced)
    return {"original": before, "capsule": after,
            "byte_reduction": 1 - after["bytes"] / before["bytes"] if before["bytes"] else None,
            "line_reduction": 1 - after["lines"] / before["lines"] if before["lines"] else None}


def collect(capsules, label, out, repeats=2, timeout=180, source_map=None, source_kinds=None):
    if repeats < 1 or timeout <= 0:
        raise ValueError("重复次数或超时无效")
    paths = sorted(capsules.rglob("capsule.json"))
    if source_kinds:
        paths = [p for p in paths if read_json(p).get("source_kind") in source_kinds]
    if not paths:
        raise ValueError("未找到 capsule")
    # 所有源映射先检查，避免长时间回放后才发现不完整的跨系统副本。
    for manifest_path in paths:
        case_id = manifest_path.parent.relative_to(capsules).as_posix()
        if case_id in (source_map or {}):
            original_path = (ROOT / source_map[case_id]).resolve()
            if not original_path.is_relative_to(ROOT) or not original_path.is_file():
                raise ValueError("原始源码映射不存在或越界：" + case_id)
    actual = subprocess.run(["lake", "env", "lean", "--version"], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=30, env=lean_subprocess_environment(ROOT))
    if actual.returncode != 0:
        raise ValueError("无法读取实际 Lean 版本")
    out.mkdir(parents=True, exist_ok=False)
    batch = str(uuid.uuid4())
    environment = {"label": label, "os": platform.system(), "release": platform.release(),
                   "architecture": platform.machine(), "python": platform.python_version(),
                   "actual_lean": actual.stdout.strip()}
    sources = source_map or {}
    rows = []
    for manifest_path in paths:
        capsule = manifest_path.parent
        case_id = capsule.relative_to(capsules).as_posix()
        manifest = read_json(manifest_path)
        source = capsule / manifest["replay"]["file"]
        metrics = {"capsule": text_size(source.read_text(encoding="utf-8")), "original": None,
                   "byte_reduction": None, "line_reduction": None}
        if case_id in sources:
            original_path = (ROOT / sources[case_id]).resolve()
            if not original_path.is_relative_to(ROOT):
                raise ValueError("原始源码映射必须在项目目录中")
            metrics = reduction(original_path.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            dependency = manifest.get("environment", {}).get("dependency_project")
            project = (capsule / dependency).resolve() if dependency else None
            original_run = run_lean_file(original_path, timeout=timeout, project_root=project)
            original_diagnostic = normalize_diagnostics(original_run.diagnostics, returncode=original_run.returncode, timed_out=original_run.timed_out)
            same_failure = (original_run.ok == manifest["expected"]["compile_ok"]
                            and diagnostic_key(original_diagnostic) == manifest["expected"]["diagnostic_key"])
            metrics["original_replay_match"] = same_failure
            if not same_failure:
                metrics["byte_reduction"] = metrics["line_reduction"] = None
        for repeat in range(1, repeats + 1):
            try:
                replay = replay_capsule(capsule, timeout)
            except Exception as exc:
                replay = {"ok": False, "error": redact_sensitive_text(exc)}
            row = {"batch_id": batch, "case_id": case_id, "repeat": repeat, "environment": environment,
                   "measurement_version": "capsule-metrics-v2",
                   "taxonomy": manifest.get("taxonomy"), "source_kind": manifest.get("source_kind"),
                   "expected": manifest["expected"], "size": metrics,
                   "minimization": manifest.get("minimization", {}),
                   "capsule_source": source.read_text(encoding="utf-8"),
                   "manifest": manifest, "replay": replay}
            append_jsonl(out / "replays.jsonl", redact_value(row))
            rows.append(row)
            print(f"{case_id} {repeat}/{repeats}: {'MATCH' if replay['ok'] else 'MISMATCH'}", flush=True)
    summary = summarize_replays(rows)
    write_json(out / "summary.json", summary)
    return summary


def summarize_replays(rows):
    seen, groups, contents, expectations = set(), defaultdict(list), {}, {}
    for row in rows:
        key = (row["batch_id"], row["case_id"], row["repeat"])
        if key in seen:
            raise ValueError("重复回放记录")
        seen.add(key)
        if row["case_id"] in contents and contents[row["case_id"]] != row["capsule_source"]:
            raise ValueError("不同环境中的案例源码不一致")
        contents[row["case_id"]] = row["capsule_source"]
        if row["case_id"] in expectations and expectations[row["case_id"]] != row.get("expected"):
            raise ValueError("不同环境中的预期诊断不一致")
        expectations[row["case_id"]] = row.get("expected")
        env = row["environment"]
        # 更换环境标签不算更换真实平台；不用机器名或个人路径。
        group = (env["os"], env["release"], env["architecture"], env["actual_lean"])
        groups[group].append(row)
    summary = []
    case_sets = []
    for environment, items in groups.items():
        cases = {row["case_id"] for row in items}
        case_sets.append(cases)
        unique_sizes = {row["case_id"]: row["size"] for row in items}
        line_rates = [s["line_reduction"] for s in unique_sizes.values() if s.get("line_reduction") is not None]
        byte_rates = [s["byte_reduction"] for s in unique_sizes.values() if s.get("byte_reduction") is not None]
        summary.append({"environment": list(environment), "cases": len(cases), "attempts": len(items),
                        "matched": sum(bool(r["replay"]["ok"]) for r in items),
                        "replay_rate": statistics.mean(int(r["replay"]["ok"]) for r in items),
                        "mean_replay_ms": statistics.mean(r["replay"].get("elapsed_ms", 0) for r in items),
                        "size_pairs": sum(s["original"] is not None for s in unique_sizes.values()),
                        "verified_size_pairs": len(line_rates),
                        "median_line_reduction": statistics.median(line_rates) if line_rates else None,
                        "median_byte_reduction": statistics.median(byte_rates) if byte_rates else None})
    common = set.intersection(*case_sets) if case_sets else set()
    return {"environments": summary, "distinct_environments": len(groups),
            "distinct_operating_systems": len({key[0] for key in groups}),
            "common_cases": sorted(common),
            "cross_environment_observed": len(groups) >= 2 and bool(common),
            "cross_os_observed": len({key[0] for key in groups}) >= 2 and bool(common),
            "note": "回放率表示预期成功/失败诊断是否重现；原始源码缺失时不估算缩减率。重复回放不是新案例。"}


def diagnosis_timer(args):
    if not args.source.is_file():
        raise ValueError("待定位源码不存在")
    # 旧入口只供预演；正式互补分组研究改用 human_study.py。
    from human_study import valid_answer
    input("请勿提前阅读源码；准备好后按 Enter，源码随后显示并开始计时。")
    started = time.perf_counter()
    print(args.source.read_text(encoding="utf-8"), flush=True)
    input("定位完成后按 Enter 停止计时：")
    elapsed = time.perf_counter() - started
    answer = input("填写具体行号与真实错误原因（不是提示文字）：").strip()
    if not valid_answer(answer):
        raise ValueError("答案为空、太短或是占位文字，不写入定位记录")
    row = {"session": args.session, "participant": args.participant, "case_id": args.case,
           "representation": args.representation, "elapsed_seconds": round(elapsed, 3),
           "answer": redact_sensitive_text(answer), "correctness": "pending",
           "source_text": args.source.read_text(encoding="utf-8")}
    append_jsonl(args.out, redact_value(row))
    return {"recorded": True, "correctness": "pending"}


def summarize_diagnoses(rows):
    """计时和定位正确性分别报告；pending 不能充当人工验收通过。"""
    seen, groups = set(), defaultdict(list)
    for row in rows:
        from human_study import valid_answer
        if "answer" in row and not valid_answer(row["answer"]):
            raise ValueError("含占位文字的预演记录不能作为人工定位结果")
        key = (row["session"], row["participant"], row["case_id"], row["representation"])
        if key in seen or row["elapsed_seconds"] <= 0 or row["representation"] not in {"original", "capsule"}:
            raise ValueError("重复或无效人工定位记录")
        seen.add(key)
        groups[row["representation"]].append(row)
    return {"groups": {name: {"observations": len(items),
                "median_seconds": statistics.median(r["elapsed_seconds"] for r in items),
                "reviewed_correct": sum(r.get("correctness") == "yes" for r in items),
                "pending_review": sum(r.get("correctness") not in {"yes", "no"} for r in items)}
                for name, items in groups.items()},
            "both_representations": {"original", "capsule"} <= groups.keys(),
            "note": "描述统计不证明因果收益；须按协议平衡题目、参与者和顺序。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--capsules", type=Path, default=ROOT / "capsules")
    measure.add_argument("--environment-label", required=True)
    measure.add_argument("--out", type=Path, required=True)
    measure.add_argument("--repeats", type=int, default=2)
    measure.add_argument("--timeout", type=float, default=180)
    measure.add_argument("--source-map", type=Path)
    measure.add_argument("--source-kinds", help="可选 std,mathlib,project-local 子集；必须在报告披露")
    merge = sub.add_parser("merge")
    merge.add_argument("files", type=Path, nargs="+")
    merge.add_argument("--out", type=Path, required=True)
    human = sub.add_parser("diagnosis-report")
    human.add_argument("files", type=Path, nargs="+")
    human.add_argument("--out", type=Path, required=True)
    timer = sub.add_parser("diagnose")
    timer.add_argument("--source", type=Path, required=True)
    timer.add_argument("--case", required=True)
    timer.add_argument("--participant", required=True, help="匿名参与者编号")
    timer.add_argument("--session", required=True)
    timer.add_argument("--representation", choices=["original", "capsule"], required=True)
    timer.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "measure":
            result = collect(args.capsules.resolve(), args.environment_label, args.out.resolve(), args.repeats,
                             args.timeout, read_json(args.source_map) if args.source_map else None,
                             args.source_kinds.split(",") if args.source_kinds else None)
        elif args.command in {"merge", "diagnosis-report"}:
            rows = [json.loads(line) for path in args.files for line in path.read_text(encoding="utf-8").splitlines()]
            result = summarize_replays(rows) if args.command == "merge" else summarize_diagnoses(rows)
            write_json(args.out, result)
        else:
            result = diagnosis_timer(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": redact_sensitive_text(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
