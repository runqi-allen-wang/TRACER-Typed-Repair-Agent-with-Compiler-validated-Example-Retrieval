"""使用真实配置的 provider 运行 18 题 A/B/C 试验。"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

from agent import append_jsonl, solve_problem, theorem_scope
from compiler import CANDIDATE_POLICY
from provider import build_provider
from retriever import find_retrieval_leaks, load_examples


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "benchmarks" / "manifest.json"
PILOT_PATH = ROOT / "results" / "real_pilot_runs.jsonl"
REVIEW_PATH = ROOT / "results" / "manual_review.csv"
CACHE_PATH = ROOT / "results" / "requests.sqlite3"
SOLUTIONS_PATH = ROOT / "results" / "solutions"
ARCHIVE_PATH = ROOT / "results" / "archive"
GENERATED_REPORTS = (
    ROOT / "results" / "pilot_summary.csv",
    ROOT / "results" / "pilot_failure_types.csv",
    ROOT / "results" / "pilot_topic_summary.csv",
    ROOT / "results" / "pilot_report.json",
    ROOT / "results" / "pass_at_1.svg",
    ROOT / "results" / "pass_at_3.svg",
)


def load_benchmarks() -> list[dict]:
    problems = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    for problem in problems:
        problem.setdefault("proof_region", {"start": "-- PROOF_START", "end": "-- PROOF_END"})
    return problems


def validate_retrieval_corpus() -> None:
    """在归档旧实验和调用 provider 之前拒绝与冻结题目重合的条件 C 示例。"""

    declarations: list[tuple[str, str]] = []
    source_cache: dict[Path, str] = {}
    for problem in load_benchmarks():
        source_path = ROOT / problem["file"]
        if source_path not in source_cache:
            source_cache[source_path] = source_path.read_text(encoding="utf-8")
        source = source_cache[source_path]
        declarations.append((problem["id"], theorem_scope(source, problem["theorem"])))
    leaks = find_retrieval_leaks(declarations, load_examples(ROOT / "examples"))
    if leaks:
        pairs = sorted({f"{item['benchmark_id']} <- {item['example_path']}" for item in leaks})
        raise ValueError("条件 C 检索语料与冻结题目声明重合: " + "; ".join(pairs))


def write_manual_review(conditions: list[str], experiment_id: str) -> None:
    """为每个冻结题目和条件组合建立复核台账。"""
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[tuple[str, str, str], dict[str, str]] = {}
    if REVIEW_PATH.exists():
        with REVIEW_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("experiment_id", ""), row.get("problem_id", ""), row.get("condition", ""))
                existing[key] = row
    fields = [
        "experiment_id",
        "problem_id",
        "condition",
        "kernel_pass",
        "inappropriate_assumption",
        "leakage_risk",
        "reviewer_note",
    ]
    with REVIEW_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for problem in load_benchmarks():
            for condition in conditions:
                key = (experiment_id, problem["id"], condition)
                row = existing.get(key, {})
                writer.writerow(
                    {
                        "experiment_id": experiment_id,
                        "problem_id": problem["id"],
                        "condition": condition,
                        "kernel_pass": row.get("kernel_pass", ""),
                        "inappropriate_assumption": row.get("inappropriate_assumption", ""),
                        "leakage_risk": row.get("leakage_risk", ""),
                        "reviewer_note": row.get("reviewer_note", ""),
                    }
                )


def archive_previous_run(*, keep_cache: bool = False) -> Path | None:
    """Move previous pilot state to a recoverable, timestamped directory."""

    paths = [PILOT_PATH, SOLUTIONS_PATH, REVIEW_PATH, *GENERATED_REPORTS]
    if not keep_cache:
        paths.append(CACHE_PATH)
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = ARCHIVE_PATH / f"{stamp}-{uuid.uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    for path in existing:
        shutil.move(str(path), str(destination / path.name))
    return destination


def run_pilot(
    conditions: list[str],
    provider,
    max_rounds: int,
    timeout: float,
    *,
    experiment_id: str,
) -> dict[str, int]:
    write_manual_review(conditions, experiment_id)
    counts = {"tasks": 0, "proof_failures": 0, "infrastructure_errors": 0}
    for condition in conditions:
        for problem in load_benchmarks():
            counts["tasks"] += 1
            try:
                result = solve_problem(
                    ROOT / problem["file"],
                    problem["theorem"],
                    condition,
                    provider,
                    max_rounds,
                    timeout,
                    ROOT / "examples",
                    CACHE_PATH,
                    SOLUTIONS_PATH,
                    PILOT_PATH,
                    problem["proof_region"]["start"],
                    problem["proof_region"]["end"],
                    "sorry",
                    problem["id"],
                    problem.get("tags", []),
                    problem.get("difficulty"),
                    experiment_id,
                )
                print(f"{condition}: {problem['id']} -> {'PASS' if result['compile_ok'] else 'FAIL'} ({result['round']} round(s))")
                if not result["compile_ok"]:
                    counts["proof_failures"] += 1
                category = result.get("diagnostic", {}).get("category")
                if result.get("provider_error") or category in {"compiler_unavailable", "task_error"}:
                    counts["infrastructure_errors"] += 1
            except Exception as exc:
                counts["infrastructure_errors"] += 1
                config = provider.metadata() if hasattr(provider, "metadata") else {"provider": provider.name}
                append_jsonl(
                    PILOT_PATH,
                    {
                        "experiment_id": experiment_id,
                        "run_id": f"task-error-{condition}-{problem['id']}",
                        "problem_id": problem["id"],
                        "benchmark_id": problem["id"],
                        "tags": problem.get("tags", []),
                        "difficulty": problem.get("difficulty"),
                        "source_file": str(ROOT / problem["file"]),
                        "theorem": problem["theorem"],
                        "condition": condition,
                        "round": 0,
                        "candidate": "",
                        "provider": config.get("provider"),
                        "provider_config": config,
                        "provider_error": None,
                        "usage": {},
                        "estimated_cost_usd": None,
                        "cache_hit": False,
                        "retrieved_examples": [],
                        "prompt_chars": 0,
                        "compile_ok": False,
                        "compile_elapsed_ms": 0.0,
                        "diagnostic": {"category": "task_error", "summary": str(exc)[:700], "feedback": "任务执行异常，已记录并继续后续题目。", "errors": [], "truncated": len(str(exc)) > 700},
                        "raw_diagnostics": str(exc)[:4000],
                        "compiler_command": None,
                        "candidate_policy": dict(CANDIDATE_POLICY),
                        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                )
                print(f"{condition}: {problem['id']} -> TASK_ERROR")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Lean proof-repair pilot")
    parser.add_argument("--provider", choices=["command", "openai_compatible"], required=True)
    parser.add_argument("--provider-command")
    parser.add_argument("--api-url", help="本次运行使用的 OpenAI 兼容接口地址")
    parser.add_argument("--model", help="本次运行使用的模型名称")
    parser.add_argument("--temperature", type=float, help="采样温度")
    parser.add_argument("--max-tokens", type=int, help="单次最大输出 token")
    parser.add_argument("--api-key-prompt", action="store_true", help="安全输入 API 密钥，不回显且不写入日志")
    parser.add_argument("--api-key-stdin", action="store_true", help="从标准输入读取 API 密钥，不写入日志")
    parser.add_argument("--conditions", default="A,B,C")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument(
        "--reuse-cache",
        action="store_true",
        help="archive the previous run but retain its request cache; incompatible with a strict fresh claim",
    )
    parser.add_argument("--experiment-id", help="stable identifier for this complete evaluation batch")
    args = parser.parse_args()
    conditions = [item.strip().upper() for item in args.conditions.split(",") if item.strip()]
    if not conditions:
        raise SystemExit("--conditions 不能为空")
    if any(item not in {"A", "B", "C"} for item in conditions):
        raise SystemExit("--conditions 只能包含 A、B、C")
    if len(conditions) != len(set(conditions)):
        raise SystemExit("--conditions 不能包含重复条件")
    if not 1 <= args.max_rounds <= 3:
        raise SystemExit("--max-rounds 必须在 1 到 3 之间")
    if args.reuse_cache and not args.fresh:
        raise SystemExit("--reuse-cache 只能与 --fresh 一起使用")
    api_key = None
    if args.api_key_prompt:
        api_key = getpass.getpass("API key（不会回显）：").strip()
        if not api_key:
            raise SystemExit("API key 不能为空")
        print("已读取 API key。", file=sys.stderr)
    elif args.api_key_stdin:
        api_key = sys.stdin.read().strip()
        if not api_key:
            raise SystemExit("API key 不能为空")
    provider = build_provider(
        args.provider,
        args.provider_command,
        api_url=args.api_url,
        api_key=api_key,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    if "C" in conditions:
        validate_retrieval_corpus()
    if args.fresh:
        archived = archive_previous_run(keep_cache=args.reuse_cache)
        if archived:
            print(f"已归档上一轮实验: {archived}", file=sys.stderr)
    experiment_id = args.experiment_id or f"pilot-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    counts = run_pilot(
        conditions,
        provider,
        args.max_rounds,
        args.timeout,
        experiment_id=experiment_id,
    )
    print(json.dumps({"experiment_id": experiment_id, **counts}, ensure_ascii=False))
    return 1 if counts["infrastructure_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
