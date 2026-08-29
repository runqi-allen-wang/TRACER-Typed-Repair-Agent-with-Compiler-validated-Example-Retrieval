"""Generate validated metrics and artifacts for one TRACER experiment batch."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from compiler import CANDIDATE_POLICY


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
PILOT = RESULTS / "real_pilot_runs.jsonl"
BENCHMARKS = ROOT / "benchmarks" / "manifest.json"
MANUAL_REVIEW = RESULTS / "manual_review.csv"
# 兼容旧测试和外部脚本的路径别名。
REVIEW = MANUAL_REVIEW
FAILURE_COLUMNS = ["condition", "problem_id", "category", "tags"]
TOPIC_COLUMNS = ["condition", "tag", "tasks", "pass_at_1", "pass_at_3", "pass_at_1_rate", "pass_at_3_rate"]
INFRASTRUCTURE_CATEGORIES = {"task_error", "provider_error", "compiler_unavailable"}


def usage_value(usage: object, *names: str) -> int:
    if not isinstance(usage, dict):
        return 0
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return 0


def total_usage(usage: object) -> int:
    total = usage_value(usage, "total_tokens")
    if total:
        return total
    return usage_value(usage, "prompt_tokens", "input_tokens") + usage_value(
        usage, "completion_tokens", "output_tokens"
    )


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def load_frame(path: Path = PILOT) -> pd.DataFrame:
    if not path.exists():
        raise ValueError(f"找不到实验日志: {path}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"实验日志第 {line_no} 行不是有效 JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"实验日志第 {line_no} 行必须是 JSON 对象")
        rows.append(row)
    if not rows:
        raise ValueError("实验日志为空")
    return pd.DataFrame(rows)


def select_experiment(frame: pd.DataFrame, experiment_id: str | None = None) -> tuple[pd.DataFrame, str]:
    if "experiment_id" not in frame.columns:
        raise ValueError("日志缺少 experiment_id；旧格式日志不能生成正式报告，请重新运行 evaluate.py")
    identifiers = sorted({str(value) for value in frame["experiment_id"].dropna() if str(value).strip()})
    if experiment_id is None:
        if len(identifiers) != 1:
            raise ValueError(f"日志包含 {len(identifiers)} 个实验批次，请使用 --experiment-id 明确选择")
        experiment_id = identifiers[0]
    if experiment_id not in identifiers:
        raise ValueError(f"找不到 experiment_id={experiment_id}")
    return frame[frame["experiment_id"].astype(str) == experiment_id].copy(), experiment_id


def _canonical_configs(frame: pd.DataFrame) -> set[str]:
    if "provider_config" not in frame.columns:
        return set()
    return {
        json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=True, sort_keys=True)
        for value in frame["provider_config"]
    }


def validate_experiment(
    frame: pd.DataFrame,
    *,
    allow_incomplete: bool = False,
    allow_cache_hits: bool = False,
) -> tuple[list[str], list[str]]:
    required = {
        "condition", "problem_id", "run_id", "round", "compile_ok", "diagnostic",
        "provider_config", "cache_hit", "candidate_policy",
    }
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        return [f"日志缺少字段: {', '.join(missing_columns)}"], []

    errors: list[str] = []
    warnings: list[str] = []

    def completeness_issue(message: str) -> None:
        (warnings if allow_incomplete else errors).append(message)

    benchmark_ids = {
        str(item["id"])
        for item in json.loads(BENCHMARKS.read_text(encoding="utf-8"))
    }
    conditions = {str(value) for value in frame["condition"]}
    invalid_conditions = sorted(conditions - {"A", "B", "C"})
    if invalid_conditions:
        errors.append(f"未知实验条件: {invalid_conditions}")
    missing_conditions = sorted({"A", "B", "C"} - conditions)
    if missing_conditions:
        completeness_issue(f"实验缺少条件: {missing_conditions}")
    expected_pairs = {(condition, problem_id) for condition in ("A", "B", "C") for problem_id in benchmark_ids}
    actual_pairs = {(str(row.condition), str(row.problem_id)) for row in frame.itertuples()}
    missing_pairs = sorted(expected_pairs - actual_pairs)
    unexpected_pairs = sorted(actual_pairs - expected_pairs)
    if missing_pairs:
        completeness_issue(f"实验缺少 {len(missing_pairs)} 个 condition/problem 组合")
    if unexpected_pairs:
        errors.append(f"实验包含未知 condition/problem 组合: {unexpected_pairs}")

    for pair, group in frame.groupby(["condition", "problem_id"], sort=True):
        raw_run_ids = list(group["run_id"])
        run_ids = {
            str(value).strip()
            for value in raw_run_ids
            if pd.notna(value) and str(value).strip()
        }
        if len(run_ids) != 1 or any(pd.isna(value) or not str(value).strip() for value in raw_run_ids):
            errors.append(f"{pair} 混合了 {len(run_ids)} 个 run_id")
        try:
            rounds = sorted(int(value) for value in group["round"])
        except (TypeError, ValueError):
            errors.append(f"{pair} 包含无效 round")
            continue
        if rounds and rounds[0] == 0:
            completeness_issue(f"{pair} 发生 task_error")
            continue
        if len(rounds) != len(set(rounds)) or rounds != list(range(1, max(rounds, default=0) + 1)):
            errors.append(f"{pair} 的轮次不是从 1 开始的连续唯一序列: {rounds}")
        ordered = group.sort_values("round")
        successes = [index for index, value in enumerate(ordered["compile_ok"]) if bool(value)]
        if successes and successes[0] != len(ordered) - 1:
            errors.append(f"{pair} 在成功后仍记录了额外轮次")
        for row in ordered.itertuples():
            diagnostic = row.diagnostic if isinstance(row.diagnostic, dict) else {}
            category = str(diagnostic.get("category", ""))
            if getattr(row, "provider_error", None) or category in INFRASTRUCTURE_CATEGORIES:
                completeness_issue(f"{pair} 包含基础设施错误: {category or 'provider_error'}")
                break

    configurations = _canonical_configs(frame)
    if len(configurations) != 1:
        errors.append(f"同一实验批次包含 {len(configurations)} 种 provider 配置")
    elif configurations == {"{}"}:
        errors.append("实验缺少 provider 配置")
    if any(
        not isinstance(value, dict) or not str(value.get("provider", "")).strip()
        for value in frame["provider_config"]
    ):
        errors.append("provider 配置必须是包含 provider 名称的对象")
    expected_policy = json.dumps(CANDIDATE_POLICY, ensure_ascii=True, sort_keys=True)
    policies = {
        json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=True, sort_keys=True)
        for value in frame["candidate_policy"]
    }
    if policies != {expected_policy}:
        errors.append("实验未统一使用当前候选执行安全策略")
    cache_hits = sum(bool(value) for value in frame["cache_hit"])
    if cache_hits:
        message = f"实验包含 {cache_hits} 条缓存命中，不能声明为 strict fresh"
        (warnings if allow_cache_hits else errors).append(message)
    return errors, warnings


def validate_manual_review(
    path: Path,
    frame: pd.DataFrame,
    experiment_id: str,
) -> tuple[list[str], list[str]]:
    if not path.exists():
        return [f"缺少人工复核台账: {path}"], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "experiment_id" not in rows[0]:
        return ["人工复核台账缺少 experiment_id 或没有数据行"], []
    selected = [row for row in rows if row.get("experiment_id") == experiment_id]
    by_pair: dict[tuple[str, str], dict[str, str]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for row in selected:
        pair = (row.get("condition", ""), row.get("problem_id", ""))
        if pair in by_pair:
            errors.append(f"人工复核台账重复: {pair}")
        by_pair[pair] = row
    expected_pairs = {
        (str(row.condition), str(row.problem_id))
        for row in frame.itertuples()
    }
    missing_pairs = sorted(expected_pairs - set(by_pair))
    unexpected_pairs = sorted(set(by_pair) - expected_pairs)
    if missing_pairs:
        errors.append(f"人工复核台账缺少 {len(missing_pairs)} 个 condition/problem 组合")
    if unexpected_pairs:
        errors.append(f"人工复核台账包含未知 condition/problem 组合: {unexpected_pairs}")
    successful = {
        (str(row.condition), str(row.problem_id))
        for row in frame.itertuples()
        if bool(row.compile_ok)
    }
    for pair in sorted(successful):
        review = by_pair.get(pair)
        if review is None:
            errors.append(f"缺少成功证明的人工复核: {pair}")
            continue
        kernel_pass = review.get("kernel_pass", "").strip().lower()
        inappropriate = review.get("inappropriate_assumption", "").strip().lower()
        leakage = review.get("leakage_risk", "").strip().lower()
        note = review.get("reviewer_note", "").strip()
        if kernel_pass not in {"yes", "no"}:
            errors.append(f"{pair} 的 kernel_pass 必须为 yes/no")
        elif kernel_pass != "yes":
            errors.append(f"{pair} 未通过 kernel 复核")
        if inappropriate not in {"yes", "no"}:
            errors.append(f"{pair} 的 inappropriate_assumption 必须为 yes/no")
        elif inappropriate == "yes":
            errors.append(f"{pair} 被标记为使用不恰当假设")
        if leakage not in {"yes", "no"}:
            errors.append(f"{pair} 的 leakage_risk 必须为 yes/no")
        elif leakage == "yes":
            errors.append(f"{pair} 被标记为存在泄漏风险")
        if not note:
            errors.append(f"{pair} 缺少 reviewer_note")
    return errors, warnings


def manual_review_complete(experiment_id: str | None, expected_pairs: set[tuple[str, str]] | None = None) -> bool:
    """兼容旧调用：判断复核台账是否覆盖并填写指定实验。"""

    review_path = REVIEW
    if not experiment_id or not review_path.exists():
        return False
    try:
        frame = pd.read_csv(review_path, dtype=str, encoding="utf-8-sig").fillna("")
    except (OSError, ValueError):
        return False
    required = {"kernel_pass", "inappropriate_assumption", "leakage_risk", "reviewer_note"}
    if not required.issubset(frame.columns) or "experiment_id" not in frame.columns:
        return False
    selected = frame[frame["experiment_id"] == experiment_id]
    if expected_pairs is not None:
        actual = set(zip(selected["condition"], selected["problem_id"])) if {"condition", "problem_id"}.issubset(selected.columns) else set()
        if actual != expected_pairs or len(selected) != len(expected_pairs):
            return False
    return all(bool(str(value).strip()) for field in required for value in selected[field].tolist())


def summarize(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if "experiment_id" in frame.columns:
        identifiers = {str(value) for value in frame["experiment_id"].dropna()}
        if len(identifiers) > 1:
            raise ValueError("summarize 只能处理单一 experiment_id")
    records: list[dict[str, Any]] = []
    final_failures: list[dict[str, Any]] = []
    for (condition, problem_id), group in frame.groupby(["condition", "problem_id"], sort=True):
        if "run_id" in group.columns and group["run_id"].dropna().nunique() > 1:
            raise ValueError(f"{condition}/{problem_id} 混合了多个 run_id")
        group = group.sort_values("round")
        first_pass = bool(group.iloc[0]["compile_ok"])
        pass3 = bool(group["compile_ok"].any())
        successful = group[group["compile_ok"]]
        rounds = int(successful.iloc[0]["round"]) if not successful.empty else int(group["round"].max())
        if not pass3:
            last = group.iloc[-1]
            diagnostic = last["diagnostic"] if isinstance(last["diagnostic"], dict) else {}
            final_failures.append({
                "condition": condition,
                "problem_id": problem_id,
                "category": diagnostic.get("category", "unknown"),
                "tags": last.get("tags", []),
            })
        usage_items = list(group["usage"]) if "usage" in group.columns else [{} for _ in range(len(group))]
        prompt_tokens = sum(usage_value(item, "prompt_tokens", "input_tokens") for item in usage_items)
        completion_tokens = sum(usage_value(item, "completion_tokens", "output_tokens") for item in usage_items)
        total_tokens = sum(total_usage(item) for item in usage_items)
        cost_values = list(group["estimated_cost_usd"]) if "estimated_cost_usd" in group.columns else []
        cost_known = len(cost_values) == len(group) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and not pd.isna(value)
            for value in cost_values
        )
        retrieval_items = list(group["retrieved_examples"]) if "retrieved_examples" in group.columns else []
        records.append({
            "condition": condition,
            "problem_id": problem_id,
            "pass_at_1": int(first_pass),
            "pass_at_3": int(pass3),
            "rounds": rounds,
            "compile_ms": round(float(group["compile_elapsed_ms"].mean()), 1),
            "retrieval_count": int(max((len(item) for item in retrieval_items), default=0)),
            "tags": list(group.iloc[0].get("tags", [])),
            "difficulty": group.iloc[0].get("difficulty"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": sum(float(value) for value in cost_values) if cost_known else None,
        })

    task_frame = pd.DataFrame(records)
    if task_frame.empty:
        raise ValueError("没有可汇总的任务")
    summary_rows: list[dict[str, Any]] = []
    for condition, group in task_frame.groupby("condition", sort=True):
        total = len(group)
        p1 = int(group["pass_at_1"].sum())
        p3 = int(group["pass_at_3"].sum())
        p1_lo, p1_hi = wilson(p1, total)
        p3_lo, p3_hi = wilson(p3, total)
        costs = list(group["cost_usd"])
        costs_known = all(value is not None and not pd.isna(value) for value in costs)
        summary_rows.append({
            "condition": condition,
            "tasks": total,
            "pass_at_1": p1,
            "pass_at_1_rate": round(p1 / total, 4),
            "pass_at_1_wilson_low": round(p1_lo, 4),
            "pass_at_1_wilson_high": round(p1_hi, 4),
            "pass_at_3": p3,
            "pass_at_3_rate": round(p3 / total, 4),
            "pass_at_3_wilson_low": round(p3_lo, 4),
            "pass_at_3_wilson_high": round(p3_hi, 4),
            "avg_rounds": round(float(group["rounds"].mean()), 3),
            "avg_compile_ms": round(float(group["compile_ms"].mean()), 1),
            "avg_prompt_tokens": round(float(group["prompt_tokens"].mean()), 1),
            "avg_completion_tokens": round(float(group["completion_tokens"].mean()), 1),
            "avg_total_tokens": round(float(group["total_tokens"].mean()), 1),
            "avg_cost_usd": round(sum(float(value) for value in costs) / total, 8) if costs_known else None,
        })
    summary = pd.DataFrame(summary_rows)
    failures = pd.DataFrame(final_failures, columns=FAILURE_COLUMNS)
    topic_rows: list[dict[str, Any]] = []
    for row in records:
        for tag in row.get("tags", []):
            topic_rows.append({
                "condition": row["condition"], "tag": tag, "tasks": 1,
                "pass_at_1": row["pass_at_1"], "pass_at_3": row["pass_at_3"],
            })
    topic_frame = pd.DataFrame(topic_rows)
    if not topic_frame.empty:
        topic_summary = topic_frame.groupby(["condition", "tag"], as_index=False).agg(
            tasks=("tasks", "sum"), pass_at_1=("pass_at_1", "sum"), pass_at_3=("pass_at_3", "sum")
        )
        topic_summary["pass_at_1_rate"] = (topic_summary["pass_at_1"] / topic_summary["tasks"]).round(4)
        topic_summary["pass_at_3_rate"] = (topic_summary["pass_at_3"] / topic_summary["tasks"]).round(4)
    else:
        topic_summary = pd.DataFrame(columns=TOPIC_COLUMNS)
    failure_counts = {
        f"{key[0]}::{key[1]}": int(value)
        for key, value in (failures.value_counts(["condition", "category"]).items() if not failures.empty else [])
    }
    provider_config = frame.iloc[0].get("provider_config", {})
    candidate_policy = frame.iloc[0].get("candidate_policy", {})
    report: dict[str, Any] = {
        "pilot": "TRACER provider pilot",
        "experiment_id": str(frame.iloc[0].get("experiment_id", "")),
        "provider_config": provider_config if isinstance(provider_config, dict) else {},
        "candidate_policy": candidate_policy if isinstance(candidate_policy, dict) else {},
        "tasks": int(task_frame["problem_id"].nunique()),
        "attempt_records": int(len(frame)),
        "cache_hits": int(sum(bool(value) for value in frame.get("cache_hit", []))),
        "conditions": summary.to_dict(orient="records"),
        "failure_types": failure_counts,
        "by_tag": topic_summary.to_dict(orient="records"),
        "limitations": [
            "题目数量小，区间只应作为 pilot evidence。",
            "题目与本地示例存在结构相似性，不能据此排除训练泄漏。",
            "模型随机性受 provider 配置和服务端 seed 支持影响。",
        ],
    }
    return summary, failures, report


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def bar_svg(summary: pd.DataFrame, field: str, title: str, path: Path) -> None:
    width, height = 760, 420
    margin_left, margin_bottom = 70, 70
    values = [float(value) for value in summary[field]]
    max_value = max(1.0, max(values) * 1.15)
    bar_width, gap = 120, 70
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    elements.append(f'<rect width="100%" height="100%" fill="white"/><text x="{width / 2}" y="32" text-anchor="middle" font-size="20">{html.escape(title)}</text>')
    base_y = height - margin_bottom
    elements.append(f'<line x1="{margin_left}" y1="{base_y}" x2="{width - 30}" y2="{base_y}" stroke="#444"/>')
    for index, (_, row) in enumerate(summary.iterrows()):
        x = margin_left + 55 + index * (bar_width + gap)
        value = float(row[field])
        bar_height = (height - margin_bottom - 80) * value / max_value
        y = base_y - bar_height
        elements.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="#4f81bd"/>')
        elements.append(f'<text x="{x + bar_width / 2}" y="{y - 8:.1f}" text-anchor="middle" font-size="14">{value:.3f}</text>')
        elements.append(f'<text x="{x + bar_width / 2}" y="{base_y + 24}" text-anchor="middle" font-size="14">{html.escape(str(row["condition"]))}</text>')
    elements.append(f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle" font-size="14">rate</text></svg>')
    path.write_text("".join(elements), encoding="utf-8")


def write_report(summary: pd.DataFrame, failures: pd.DataFrame, report: dict[str, Any]) -> None:
    report = _json_safe(report)
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary.to_csv(RESULTS / "pilot_summary.csv", index=False, encoding="utf-8-sig", na_rep="unknown")
    failures.to_csv(RESULTS / "pilot_failure_types.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(report.get("by_tag", []), columns=TOPIC_COLUMNS).to_csv(
        RESULTS / "pilot_topic_summary.csv", index=False, encoding="utf-8-sig"
    )
    (RESULTS / "pilot_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    bar_svg(summary, "pass_at_1_rate", "TRACER pass@1", RESULTS / "pass_at_1.svg")
    bar_svg(summary, "pass_at_3_rate", "TRACER pass@3", RESULTS / "pass_at_3.svg")
    draft = report.get("status") != "formal"
    lines = [
        f"# TRACER Pilot Report{' (DRAFT)' if draft else ''}", "",
        f"- Experiment ID: `{report['experiment_id']}`",
        f"- Status: **{str(report['status']).upper()}**",
        f"- Cache hits: `{report['cache_hits']}`",
        f"- Provider configuration: `{json.dumps(report.get('provider_config', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Candidate policy: `{json.dumps(report.get('candidate_policy', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
    ]
    if report.get("validation_warnings"):
        lines += ["## Validation Warnings", ""] + [f"- {item}" for item in report["validation_warnings"]] + [""]
    lines += [
        "## 汇总", "",
        "| 条件 | 题数 | pass@1 | Wilson 95% CI | pass@3 | Wilson 95% CI | 平均轮次 | 平均编译毫秒 | 平均总 token | 估算成本 |",
        "|---|---:|---:|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in report["conditions"]:
        cost = "unknown" if row.get("avg_cost_usd") is None else f"${row['avg_cost_usd']:.8f}"
        lines.append(
            f"| {row['condition']} | {row['tasks']} | {row['pass_at_1']}/{row['tasks']} ({row['pass_at_1_rate']:.1%}) | "
            f"[{row['pass_at_1_wilson_low']:.1%}, {row['pass_at_1_wilson_high']:.1%}] | "
            f"{row['pass_at_3']}/{row['tasks']} ({row['pass_at_3_rate']:.1%}) | "
            f"[{row['pass_at_3_wilson_low']:.1%}, {row['pass_at_3_wilson_high']:.1%}] | "
            f"{row['avg_rounds']:.2f} | {row['avg_compile_ms']:.1f} | {row['avg_total_tokens']:.1f} | {cost} |"
        )
    lines += [
        "", "## 解释边界", "",
        "- 18 道题是工作流 pilot，不构成通用自动定理证明能力或 SOTA 证据。",
        "- C 条件的本地示例与部分评测题高度相似，泄漏风险必须逐题人工复核。",
        "- 只有状态为 FORMAL、完整保留对应 JSONL 与 proof artifacts 的报告才能用于正式结论。",
    ]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PILOT)
    parser.add_argument("--review", type=Path, default=MANUAL_REVIEW)
    parser.add_argument("--experiment-id")
    parser.add_argument("--allow-incomplete", action="store_true", help="generate an explicitly marked draft")
    parser.add_argument("--allow-cache-hits", action="store_true", help="generate an explicitly marked draft")
    parser.add_argument("--allow-unreviewed", action="store_true", help="generate an explicitly marked draft")
    args = parser.parse_args()
    try:
        frame, experiment_id = select_experiment(load_frame(args.input), args.experiment_id)
        errors, warnings = validate_experiment(
            frame, allow_incomplete=args.allow_incomplete, allow_cache_hits=args.allow_cache_hits
        )
        review_errors, review_warnings = validate_manual_review(args.review, frame, experiment_id)
        if args.allow_unreviewed:
            warnings.extend(review_errors)
        else:
            errors.extend(review_errors)
        warnings.extend(review_warnings)
        if errors:
            raise ValueError("报告门禁失败:\n- " + "\n- ".join(errors))
        summary, failures, report = summarize(frame)
        report["status"] = "draft" if warnings else "formal"
        report["manual_review_complete"] = not review_errors
        report["validation_warnings"] = warnings
        write_report(summary, failures, report)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
