"""TRACER-REAL v2 预注册确认性分析；只读取已完成轨迹，不调用 provider。"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


ANALYSIS_VERSION = "tracer-real-v2-causal-analysis-v1"
CONTROL_ARM = "content_free_retry"
TREATMENT_ARM = "true_structured"
DEFAULT_RESAMPLES = 10_000
DEFAULT_RANDOMIZATION_DRAWS = 100_000
DEFAULT_SEED = 20260916


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("分析输入 JSON 顶层必须是对象")
    return value


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("不能对空样本计算区间")
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _sign_flip_p_value(project_effects: list[float], seed: int) -> tuple[float, str, int]:
    observed = sum(project_effects) / len(project_effects)
    project_count = len(project_effects)
    if project_count <= 20:
        assignments = itertools.product((-1, 1), repeat=project_count)
        exceed, total = 0, 0
        for signs in assignments:
            permuted = sum(sign * effect for sign, effect in zip(signs, project_effects)) / project_count
            exceed += permuted >= observed - 1e-15
            total += 1
        return exceed / total, "exact_all_project_sign_flips", total

    generator = random.Random(seed)
    exceed = 0
    for _ in range(DEFAULT_RANDOMIZATION_DRAWS):
        permuted = sum(
            (-1 if generator.randrange(2) == 0 else 1) * effect
            for effect in project_effects
        ) / project_count
        exceed += permuted >= observed - 1e-15
    # 加一修正确保有限随机化估计不会返回未经支持的零值。
    return (
        (exceed + 1) / (DEFAULT_RANDOMIZATION_DRAWS + 1),
        "seeded_project_sign_flip_monte_carlo",
        DEFAULT_RANDOMIZATION_DRAWS,
    )


def _hierarchical_interval(
    grouped: dict[str, list[int]], *, seed: int, resamples: int,
) -> tuple[float, float]:
    if type(resamples) is not int or resamples <= 0:
        raise ValueError("分层重采样次数必须为正整数")
    projects = sorted(grouped)
    generator = random.Random(seed)
    estimates = []
    for _ in range(resamples):
        sampled_projects = [generator.choice(projects) for _ in projects]
        project_means = []
        for project_id in sampled_projects:
            values = grouped[project_id]
            sampled_values = [generator.choice(values) for _ in values]
            project_means.append(sum(sampled_values) / len(sampled_values))
        estimates.append(sum(project_means) / len(project_means))
    return _percentile(estimates, 0.025), _percentile(estimates, 0.975)


def analyze(
    seeds: list[dict[str, Any]], branches: list[dict[str, Any]],
    *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    """按测试项目等权计算预注册主对比与不确定性。"""

    eligible = [row for row in seeds if row.get("eligible_first_failure")]
    if not eligible:
        raise ValueError("没有合格首轮失败，不能执行 v2 主分析")
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for row in branches:
        key = (str(row.get("seed_id", "")), str(row.get("arm", "")))
        if key in by_pair:
            raise ValueError("分支轨迹包含重复的 seed/arm")
        by_pair[key] = row

    grouped: dict[str, list[int]] = defaultdict(list)
    missing = []
    for row in eligible:
        seed_id = str(row.get("seed_id", ""))
        project_id = row.get("project_id")
        if row.get("split") != "test":
            raise ValueError("v2 主分析只能包含预注册 test 项目的首轮记录")
        if not seed_id or not isinstance(project_id, str) or not project_id:
            raise ValueError("合格首轮记录缺少 seed_id 或 project_id")
        treatment = by_pair.get((seed_id, TREATMENT_ARM))
        control = by_pair.get((seed_id, CONTROL_ARM))
        if (
            treatment is None or control is None
            or treatment.get("status") != "complete" or control.get("status") != "complete"
            or type(treatment.get("compile_ok")) is not bool
            or type(control.get("compile_ok")) is not bool
        ):
            missing.append(seed_id)
            continue
        grouped[project_id].append(
            int(treatment["compile_ok"]) - int(control["compile_ok"])
        )
    if missing:
        raise ValueError("主对比分支不完整；拒绝删除缺失后分析：" + ", ".join(sorted(missing)))
    if not grouped:
        raise ValueError("没有完整的主对比配对")

    project_rows = []
    effects = []
    for project_id in sorted(grouped):
        values = grouped[project_id]
        effect = sum(values) / len(values)
        effects.append(effect)
        project_rows.append({
            "project_id": project_id,
            "matched_pairs": len(values),
            "mean_success_delta": effect,
            "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values),
            "ties": sum(value == 0 for value in values),
        })

    estimate = sum(effects) / len(effects)
    p_value, randomization_method, assignments = _sign_flip_p_value(effects, seed)
    interval_low, interval_high = _hierarchical_interval(grouped, seed=seed, resamples=resamples)
    matched_pairs = sum(len(values) for values in grouped.values())
    sample_gate_pass = len(grouped) >= 5 and matched_pairs >= 30
    primary_test_pass = estimate > 0 and p_value <= 0.05
    return {
        "analysis_version": ANALYSIS_VERSION,
        "primary_contrast": TREATMENT_ARM + " - " + CONTROL_ARM,
        "population": "eligible_first_failures_on_preregistered_v2_test_projects",
        "project_weighting": "equal_weight_per_test_project",
        "test_projects": len(grouped),
        "matched_pairs": matched_pairs,
        "project_effects": project_rows,
        "mean_success_delta": estimate,
        "one_sided_p_value": p_value,
        "randomization_method": randomization_method,
        "randomization_assignments_or_draws": assignments,
        "hierarchical_interval_95": {"low": interval_low, "high": interval_high},
        "hierarchical_resamples": resamples,
        "analysis_seed": seed,
        "confirmatory_direction": "true_structured > content_free_retry",
        "confirmatory_direction_pass": estimate > 0,
        "minimum_sample_gate_pass": sample_gate_pass,
        "primary_test_pass_at_0_05": primary_test_pass,
        "confirmatory_claim_allowed": sample_gate_pass and primary_test_pass,
        "claim_boundary": "统计门槛通过仍不替代题库、轨迹、基础设施、同首轮候选和成功证明复编译审计。",
    }


def load_run(run: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not (run / "summary.json").is_file():
        raise ValueError("批次未完成或缺少 summary.json")
    seeds = [read_json(path) for path in sorted((run / "seeds").rglob("*.json"))]
    branches = [read_json(path) for path in sorted((run / "branches").rglob("result.json"))]
    return seeds, branches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    args = parser.parse_args()
    try:
        seeds, branches = load_run(args.run)
        result = analyze(seeds, branches, resamples=args.resamples)
        if args.out is not None:
            if args.out.exists():
                raise ValueError("分析输出已存在；拒绝覆盖")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
