"""对 repair24 六臂实验执行可复查的 AI 辅助证明复核。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research import ARMS, trial_path  # noqa: E402


START = "-- PROOF_START"
END = "-- PROOF_END"
FORBIDDEN_CANDIDATE = re.compile(
    r"(?i)(?:\bsorry\b|\bsorryAx\b|\badmit\b|\baxiom\b|\bunsafe\b|\brun_tac\b|"
    r"\bnative_decide\b|\bset_option\b|\belab\b|\bmacro\b|\bimport\b|\btheorem\b|"
    r"\blemma\b|\bnamespace\b|#\s*(?:eval|check|print)|\bIO\.|\bSystem\.|\bProcess\.)"
)
FIELDS = [
    "experiment_id", "model_id", "repeat", "arm", "problem_id", "kernel_pass",
    "inappropriate_assumption", "leakage_risk", "review_mode", "reviewer_note",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical_nonproof(text: str) -> tuple[str, ...]:
    """忽略序列化产生的空行与行尾空格，但保留非空行缩进和内容。"""
    return tuple(line.rstrip() for line in normalized_text(text).splitlines() if line.strip())


def proof_parts(text: str) -> tuple[str, str, str]:
    """返回证明区域之前、证明内容、结束标记起始后的文本。"""
    text = normalized_text(text)
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("证明文件必须包含唯一证明区域标记")
    start = text.index(START)
    line_end = text.find("\n", start)
    if line_end < 0:
        raise ValueError("证明起始标记后缺少换行")
    proof_start = line_end + 1
    end_marker = text.index(END, proof_start)
    # 结束标记通常带有与定理体一致的缩进。边界应从标记所在行开头开始，
    # 否则标记前的空格会被误算进证明区域并造成源码漂移误报。
    proof_end = text.rfind("\n", proof_start, end_marker) + 1
    if proof_end <= proof_start:
        raise ValueError("证明区域为空或标记顺序无效")
    return text[:proof_start], text[proof_start:proof_end], text[proof_end:]


def task_key(row: dict) -> tuple[str, str, str, str]:
    return str(row["model_id"]), str(row["repeat"]), str(row["arm"]), str(row["problem_id"])


def leakage_findings(problem: dict, attempts: list[dict], candidate: str) -> list[str]:
    findings: list[str] = []
    problem_id = str(problem["id"]).lower()
    theorem = str(problem["theorem"]).lower()
    candidate = candidate.strip()
    for round_index, attempt in enumerate(attempts, start=1):
        for example_index, example in enumerate(attempt.get("retrieved_examples") or [], start=1):
            if not isinstance(example, dict):
                findings.append(f"round {round_index} example {example_index}: 非对象检索记录")
                continue
            material = "\n".join(
                str(example.get(name, "")) for name in ("path", "snippet", "failure_context")
            )
            lowered = material.lower()
            if problem_id in lowered or theorem in lowered:
                findings.append(f"round {round_index} example {example_index}: 检索内容出现目标标识")
            if candidate and candidate in material:
                findings.append(f"round {round_index} example {example_index}: 检索内容包含完整成功候选")
    return findings


def review_success(source_text: str, solution_text: str, trial: dict, attempts: list[dict], problem: dict) -> dict:
    errors: list[str] = []
    if trial.get("compile_ok") is not True or trial.get("independent_compile_ok") is not True:
        errors.append("任务未同时通过原始与独立 Lean 编译")
    if trial.get("error") not in (None, ""):
        errors.append("任务摘要仍含错误")
    if not attempts or attempts[-1].get("compile_ok") is not True:
        errors.append("最终逐轮记录不是成功编译")
    if any(row.get("compile_ok") is True for row in attempts[:-1]):
        errors.append("成功前仍存在已通过轮次")

    try:
        source_prefix, _, source_suffix = proof_parts(source_text)
        solution_prefix, solution_proof, solution_suffix = proof_parts(solution_text)
    except ValueError as exc:
        return {"errors": [str(exc)], "warning_count": 0, "candidate": ""}
    if (
        canonical_nonproof(source_prefix) != canonical_nonproof(solution_prefix)
        or canonical_nonproof(source_suffix) != canonical_nonproof(solution_suffix)
    ):
        errors.append("imports、定理头、局部定义或证明区域之外的源码发生漂移")

    candidate = str(attempts[-1].get("candidate", "")).strip()
    if not candidate or solution_proof.strip() != candidate:
        errors.append("最终候选与保存证明区域不一致")
    match = FORBIDDEN_CANDIDATE.search(candidate)
    if match:
        errors.append(f"候选包含不允许的构造: {match.group(0)}")
    errors.extend(leakage_findings(problem, attempts, candidate))

    warning_count = int(attempts[-1].get("diagnostic", {}).get("warning_count") or 0)
    if attempts[-1].get("kernel_pass") is not True:
        errors.append("最终逐轮记录缺少 kernel_pass")
    return {"errors": errors, "warning_count": warning_count, "candidate": candidate}


def review_run(run: Path, write: bool = False) -> dict:
    run = run.resolve()
    plan = read_json(run / "plan.json")
    benchmark = read_json(run / "benchmark.json")
    completion = read_json(run / "completion.json")
    if completion.get("complete") is not True or completion.get("infrastructure_errors") != 0:
        raise ValueError("批次尚未完整结束或仍含基础设施错误")
    problems = {str(row["id"]): row for row in benchmark.get("problems", [])}

    review_path = run / "manual_review.csv"
    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if list(reader.fieldnames or []) != FIELDS:
            raise ValueError("manual_review.csv 表头不符合六臂复核契约")
        review_rows = list(reader)
    review = {task_key(row): row for row in review_rows}
    if len(review_rows) != len(plan["tasks"]) or len(review) != len(review_rows):
        raise ValueError("复核表未唯一覆盖计划任务")
    if write and any(
        row.get(field, "").strip()
        for row in review_rows
        for field in ("kernel_pass", "inappropriate_assumption", "leakage_risk", "reviewer_note")
    ):
        raise ValueError("复核表已有实质内容；为避免覆盖既有判断，本工具拒绝写入")

    findings: list[dict] = []
    successes = 0
    warning_successes = 0
    reviewed_rows: list[dict] = []
    for task in plan["tasks"]:
        key = task_key(task)
        row = dict(review[key])
        local = trial_path(run, task)
        trial = read_json(local / "trial.json")
        attempts = read_jsonl(local / "runs.jsonl")
        if trial.get("compile_ok") is True:
            successes += 1
            condition = ARMS[task["arm"]][0]
            solutions = list((local / "solutions" / condition).glob("*.lean"))
            if len(solutions) != 1:
                result = {"errors": ["成功任务缺少唯一证明文件"], "warning_count": 0, "candidate": ""}
            else:
                result = review_success(
                    str(problems[task["problem_id"]]["source_text"]),
                    solutions[0].read_text(encoding="utf-8"), trial, attempts, problems[task["problem_id"]],
                )
            if result["warning_count"]:
                warning_successes += 1
            if result["errors"]:
                findings.append({
                    "model_id": task["model_id"], "repeat": task["repeat"], "arm": task["arm"],
                    "problem_id": task["problem_id"], "errors": result["errors"],
                })
            else:
                row.update({
                    "kernel_pass": "yes",
                    "inappropriate_assumption": "no",
                    "leakage_risk": "no",
                    "review_mode": "ai_assisted",
                    "reviewer_note": (
                        "AI 辅助复核 PASS：独立 Lean 编译通过；imports、定理头、局部定义和假设未改变；"
                        "候选仅替换证明区域；未发现占位、额外公理、不安全/本机执行构造或目标答案泄漏。"
                        + (f" 含 {result['warning_count']} 条非致命 linter 风格警告。" if result["warning_count"] else "")
                    ),
                })
        reviewed_rows.append(row)

    report = {
        "format": "tracer-research-ai-assisted-review-v1",
        "experiment_id": plan["experiment_id"],
        "review_mode": "ai_assisted",
        "tasks": len(plan["tasks"]),
        "successful_tasks": successes,
        "failed_tasks_not_proof_reviewed": len(plan["tasks"]) - successes,
        "reviewed_successes": successes - len(findings),
        "successes_with_linter_warnings": warning_successes,
        "checks": [
            "任务与独立 Lean 编译状态", "保存证明与最终成功候选一致", "证明区域之外源码不变",
            "未完成证明、额外公理、命令注入及本机执行构造", "检索内容不含目标标识或完整成功候选",
        ],
        "errors": findings,
        "complete": not findings and successes > 0,
    }
    if write:
        if findings:
            raise ValueError(f"发现 {len(findings)} 个需进一步复核的成功任务；未写入复核表")
        with review_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(reviewed_rows)
        (run / "ai_review_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="全部检查通过后填写成功任务的复核字段")
    args = parser.parse_args()
    try:
        result = review_run(args.run, args.write)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": result["complete"], **result}, ensure_ascii=False, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
