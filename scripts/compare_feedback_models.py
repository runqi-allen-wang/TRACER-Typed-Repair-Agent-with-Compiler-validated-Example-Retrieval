"""比较两个已通过发布审计的 Feedback Study v1 模型批次。"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_feedback_study import audit_release  # noqa: E402


FORMAT = "tracer-feedback-cross-model-comparison-v1"
PROTOCOL_VERSION = "tracer-feedback-study-v1"
REPLICATION_PROTOCOL_VERSION = "tracer-feedback-cross-model-v1"
REPRESENTATIONS = ("raw", "normalized", "structured")
CONTROL_FIELDS = (
    "repeats", "representations", "max_rounds", "compile_timeout",
    "order_seed", "examples_dir",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _task_key(row: dict) -> tuple[int, str, str]:
    return (
        int(row.get("repeat", 0)),
        str(row.get("representation", "")),
        str(row.get("problem_id", "")),
    )


def _model(plan: dict) -> dict:
    models = plan.get("config", {}).get("models", [])
    if len(models) != 1:
        raise ValueError("每个 Feedback Study 发布包必须只包含一个模型")
    return models[0]


def _model_public(model: dict) -> dict:
    return {
        key: model.get(key)
        for key in (
            "id", "model", "api_url", "temperature", "max_tokens",
            "thinking", "reasoning_effort",
        )
    }


def _sign(value: int) -> int:
    return 0 if value == 0 else 1 if value > 0 else -1


def compare_outcomes(
    baseline_trials: list[dict],
    baseline_attempts: list[dict],
    replication_trials: list[dict],
    replication_attempts: list[dict],
) -> tuple[list[dict], list[dict]]:
    """对齐任务结局，并区分最终一致、首轮一致与表示差方向一致。"""

    baseline = {_task_key(row): row for row in baseline_trials}
    replication = {_task_key(row): row for row in replication_trials}
    if len(baseline) != 216 or set(baseline) != set(replication):
        raise ValueError("两个模型没有形成相同的 216 个任务")
    baseline_rounds: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    replication_rounds: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for row in baseline_attempts:
        baseline_rounds[_task_key(row)].append(row)
    for row in replication_attempts:
        replication_rounds[_task_key(row)].append(row)
    if set(baseline_rounds) != set(baseline) or set(replication_rounds) != set(baseline):
        raise ValueError("两个模型的逐轮记录没有完整覆盖任务集合")

    by_representation = []
    for representation in REPRESENTATIONS:
        keys = sorted(key for key in baseline if key[1] == representation)
        baseline_final = [bool(baseline[key].get("compile_ok")) for key in keys]
        replication_final = [bool(replication[key].get("compile_ok")) for key in keys]
        baseline_first = [bool(baseline_rounds[key][0].get("compile_ok")) for key in keys]
        replication_first = [bool(replication_rounds[key][0].get("compile_ok")) for key in keys]
        by_representation.append({
            "representation": representation,
            "matched_tasks": len(keys),
            "baseline_pass_at_1": sum(baseline_first),
            "replication_pass_at_1": sum(replication_first),
            "pass_at_1_agreement_rate": statistics.mean(
                left == right for left, right in zip(baseline_first, replication_first)
            ),
            "baseline_pass_within_budget": sum(baseline_final),
            "replication_pass_within_budget": sum(replication_final),
            "success_delta": sum(replication_final) - sum(baseline_final),
            "final_outcome_agreement_rate": statistics.mean(
                left == right for left, right in zip(baseline_final, replication_final)
            ),
            "both_success": sum(left and right for left, right in zip(baseline_final, replication_final)),
            "baseline_only_success": sum(left and not right for left, right in zip(baseline_final, replication_final)),
            "replication_only_success": sum(right and not left for left, right in zip(baseline_final, replication_final)),
            "both_failed": sum(not left and not right for left, right in zip(baseline_final, replication_final)),
            "baseline_avg_rounds": statistics.mean(len(baseline_rounds[key]) for key in keys),
            "replication_avg_rounds": statistics.mean(len(replication_rounds[key]) for key in keys),
        })

    contrast_consistency = []
    for treatment, control in (
        ("normalized", "raw"),
        ("structured", "raw"),
        ("structured", "normalized"),
    ):
        pairs = []
        for repeat in range(1, 4):
            problem_ids = sorted(key[2] for key in baseline if key[0] == repeat and key[1] == treatment)
            for problem_id in problem_ids:
                treatment_key = (repeat, treatment, problem_id)
                control_key = (repeat, control, problem_id)
                baseline_delta = int(bool(baseline[treatment_key].get("compile_ok"))) - int(
                    bool(baseline[control_key].get("compile_ok"))
                )
                replication_delta = int(bool(replication[treatment_key].get("compile_ok"))) - int(
                    bool(replication[control_key].get("compile_ok"))
                )
                pairs.append((baseline_delta, replication_delta))
        contrast_consistency.append({
            "comparison": f"{treatment} - {control}",
            "matched_problem_repeats": len(pairs),
            "baseline_mean_success_delta": statistics.mean(left for left, _ in pairs),
            "replication_mean_success_delta": statistics.mean(right for _, right in pairs),
            "same_direction_rate": statistics.mean(_sign(left) == _sign(right) for left, right in pairs),
            "both_zero": sum(left == 0 and right == 0 for left, right in pairs),
            "concordant_nonzero": sum(_sign(left) == _sign(right) and left != 0 for left, right in pairs),
            "opposite_direction": sum(left * right < 0 for left, right in pairs),
            "one_model_only_nonzero": sum((left == 0) != (right == 0) for left, right in pairs),
        })
    return by_representation, contrast_consistency


def compare_releases(baseline_root: Path, replication_root: Path, run_audit: bool = True) -> dict:
    """严格校验两个发布包后生成描述性跨模型一致性报告。"""

    baseline_root = baseline_root.resolve()
    replication_root = replication_root.resolve()
    errors: list[str] = []
    if run_audit:
        for label, root in (("baseline", baseline_root), ("replication", replication_root)):
            audit = audit_release(root)
            if not audit.get("ok"):
                errors.append(f"{label} 发布审计失败: " + "; ".join(audit.get("errors", [])[:3]))
    try:
        baseline_plan = _read_json(baseline_root / "plan.sanitized.json")
        replication_plan = _read_json(replication_root / "plan.sanitized.json")
        baseline_benchmark = _read_json(baseline_root / "benchmark.json")
        replication_benchmark = _read_json(replication_root / "benchmark.json")
        baseline_trials = _read_jsonl(baseline_root / "trials.jsonl")
        replication_trials = _read_jsonl(replication_root / "trials.jsonl")
        baseline_attempts = _read_jsonl(baseline_root / "attempts.sanitized.jsonl")
        replication_attempts = _read_jsonl(replication_root / "attempts.sanitized.jsonl")
        baseline_model = _model(baseline_plan)
        replication_model = _model(replication_plan)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"format": FORMAT, "ok": False, "errors": errors + [str(exc)]}

    if baseline_plan.get("protocol_version") != PROTOCOL_VERSION or replication_plan.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("两个发布包必须使用相同的 Feedback Study v1 协议")
    if baseline_benchmark != replication_benchmark:
        errors.append("两个发布包的冻结 repair24 题库不一致")
    for field in CONTROL_FIELDS:
        if baseline_plan.get("config", {}).get(field) != replication_plan.get("config", {}).get(field):
            errors.append(f"公共实验控制不一致: {field}")
    for field in ("temperature", "max_tokens"):
        if baseline_model.get(field) != replication_model.get(field):
            errors.append(f"公共生成预算不一致: {field}")
    if (
        baseline_model.get("api_url") == replication_model.get("api_url")
        and baseline_model.get("model") == replication_model.get("model")
    ):
        errors.append("复现批次与基线使用了相同模型身份")
    for name in ("feedback_study.protocol.json", "feedback.txt", "proof_contract.txt"):
        baseline_protocol = baseline_root / "protocol" / name
        replication_protocol = replication_root / "protocol" / name
        try:
            baseline_text = baseline_protocol.read_text(encoding="utf-8")
            replication_text = replication_protocol.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"公开协议或提示模板无法读取: {name}: {exc}")
            continue
        if baseline_text != replication_text:
            errors.append(f"公开协议或提示模板不一致: {name}")
    baseline_order = [_task_key(row) for row in baseline_plan.get("tasks", [])]
    replication_order = [_task_key(row) for row in replication_plan.get("tasks", [])]
    if baseline_order != replication_order:
        errors.append("任务集合或随机执行顺序不一致")
    contract = replication_plan.get("replication_contract")
    if not (
        isinstance(contract, dict)
        and contract.get("version") == REPLICATION_PROTOCOL_VERSION
        and contract.get("status") == "reference-validated"
        and contract.get("reference_experiment_id") == baseline_plan.get("experiment_id")
        and contract.get("reference_release") == baseline_root.name
    ):
        errors.append("复现发布包缺少指向基线批次的已验证冻结合同")

    by_representation: list[dict] = []
    contrast_consistency: list[dict] = []
    if not errors:
        try:
            by_representation, contrast_consistency = compare_outcomes(
                baseline_trials, baseline_attempts, replication_trials, replication_attempts,
            )
        except ValueError as exc:
            errors.append(str(exc))
    return {
        "format": FORMAT,
        "ok": not errors,
        "baseline": {
            "release": baseline_root.name,
            "experiment_id": baseline_plan.get("experiment_id"),
            "model": _model_public(baseline_model),
        },
        "replication": {
            "release": replication_root.name,
            "experiment_id": replication_plan.get("experiment_id"),
            "model": _model_public(replication_model),
        },
        "matched_tasks": 216 if not errors else 0,
        "by_representation": by_representation,
        "contrast_direction_consistency": contrast_consistency,
        "errors": errors,
        "interpretation": (
            "同题、同重复、同反馈表示的描述性跨模型配对。结果一致率不是模型等价性证明；"
            "表示差方向一致率需同时查看 both_zero，不能把共同无差异误写成处理增益复现。"
        ),
    }


def _write_report(out: Path, report: dict) -> None:
    if out.exists():
        raise ValueError(f"输出目录已存在: {out}")
    out.mkdir(parents=True)
    (out / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    fields = list(report["by_representation"][0])
    with (out / "by_representation.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(report["by_representation"])
    lines = [
        "# Feedback Study v1 跨模型复现报告",
        "",
        f"基线：[ `{report['baseline']['model']['model']}` ](../{report['baseline']['release']})；"
        f"复现：[ `{report['replication']['model']['model']}` ](../{report['replication']['release']})。",
        "",
        "| 表示 | 基线三轮内 | 复现三轮内 | 成功差 | 最终结局一致率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["by_representation"]:
        lines.append(
            f"| {row['representation']} | {row['baseline_pass_within_budget']}/72 | "
            f"{row['replication_pass_within_budget']}/72 | {row['success_delta']:+d} | "
            f"{row['final_outcome_agreement_rate']:.3f} |"
        )
    lines.extend(["", report["interpretation"], ""])
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    files = sorted(path for path in out.iterdir() if path.is_file())
    manifest = {
        "format": FORMAT,
        "files": [
            {"path": path.name, "size_bytes": path.stat().st_size}
            for path in files
        ],
        "inventory_method": "relative path and byte size",
    }
    (out / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # 正式比较包必须在写出时立即通过自己的脱敏与完整性审计。
    from audit_feedback_comparison import audit_comparison

    audit = audit_comparison(out)
    if not audit.get("ok"):
        raise ValueError("跨模型比较包自审计失败: " + "; ".join(audit.get("errors", [])[:5]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--replication", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        report = compare_releases(args.baseline, args.replication)
        if args.out is not None:
            if not report["ok"]:
                raise ValueError("跨模型门禁未通过，不写入正式报告: " + "; ".join(report["errors"][:5]))
            _write_report(args.out.resolve(), report)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
