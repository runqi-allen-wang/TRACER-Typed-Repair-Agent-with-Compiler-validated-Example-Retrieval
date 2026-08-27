"""Part 1 逐环节指标记录器（对应 Zhewen idea Part 1）。

- 记录 proposer / memory / reviewer / tool 各环节调用数、token、成本、编译时间、成功节点；
- 缓存每题首轮候选；
- --mock 无需真实模型即可自测；
- --summary 汇总 JSONL。

用法：
    python baseline/metrics_logger.py --mock --tasks 5 --out data --jsonl data/metrics.jsonl
    python baseline/metrics_logger.py --summary --jsonl data/metrics.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
import uuid
from collections import defaultdict
from pathlib import Path

# 仅供 mock 的占位价格；真实实验请传入或由 provider 返回
DEFAULT_INPUT_USD_PER_1K = 0.015
DEFAULT_OUTPUT_USD_PER_1K = 0.075
MOCK_MAX_ITERATIONS = 4


def cost_usd(usage: dict, in_usd: float, out_usd: float) -> float:
    return (usage.get("prompt_tokens", 0) / 1000 * in_usd) + (
        usage.get("completion_tokens", 0) / 1000 * out_usd
    )


def make_run(
    task_id: str,
    *,
    model: str = "openai:gpt-5.6-sol",
    condition: str = "baseline",
    first_round_candidate: str | None = None,
) -> dict:
    """构造一条 run 记录（mock 或真实都走这个结构）。"""
    round_no = 0
    compile_ok = False
    while round_no < MOCK_MAX_ITERATIONS:
        round_no += 1
        # 模拟：proposer / tool / memory / reviewer 各一次调用
        first_round_candidate = first_round_candidate if round_no == 1 else None
        if random.random() < 0.45:
            compile_ok = True
            break
    usage = {
        "prompt_tokens": random.randint(400, 2000),
        "completion_tokens": random.randint(300, 1600),
    }
    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_id": task_id,
        "condition": condition,
        "model": model,
        "rounds": round_no,
        "compile_ok": compile_ok,
        "success_node": round_no if compile_ok else None,
        "compile_elapsed_ms": random.randint(800, 12000),
        "first_round_candidate": first_round_candidate,
        "calls": {
            "proposer_calls": round_no,
            "memory_calls": round_no,
            "reviewer_calls": round_no,
            "tool_calls": round_no,
        },
        "usage": usage,
        "estimated_cost_usd": cost_usd(usage, DEFAULT_INPUT_USD_PER_1K, DEFAULT_OUTPUT_USD_PER_1K),
    }


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def summary(jsonl: Path) -> None:
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    n = len(rows)
    ok = sum(1 for r in rows if r.get("compile_ok"))
    # 每个环节的总调用数
    agg = defaultdict(int)
    for r in rows:
        for k, v in r.get("calls", {}).items():
            agg[k] += v
    avg_prompt = sum(r["usage"].get("prompt_tokens", 0) for r in rows) / max(1, n)
    avg_complete = sum(r["usage"].get("completion_tokens", 0) for r in rows) / max(1, n)
    known_costs = [
        r.get("estimated_cost_usd")
        for r in rows
        if isinstance(r.get("estimated_cost_usd"), (int, float))
    ]
    total_cost = sum(known_costs) if len(known_costs) == n else None
    print(json.dumps({
        "tasks": n,
        "passed": ok,
        "pass_rate": round(ok / max(1, n), 4),
        "avg_prompt_tokens": round(avg_prompt, 1),
        "avg_completion_tokens": round(avg_complete, 1),
        "total_cost_usd": round(total_cost, 4) if total_cost is not None else None,
        "calls_total": dict(agg),
    }, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("mock")
    run.add_argument("--tasks", type=int, default=3)
    run.add_argument("--jsonl", type=Path, required=True)

    summ = sub.add_parser("summary")
    summ.add_argument("--jsonl", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "mock":
        tasks = [f"task-{i:02d}" for i in range(1, args.tasks + 1)]
        existing = args.jsonl.read_text(encoding="utf-8").splitlines() if args.jsonl.exists() else []
        n_existing = len(existing)
        for i, task in enumerate(tasks):
            append_jsonl(args.jsonl, make_run(task, condition="baseline",
                                              first_round_candidate=f"by intro h; exact h  # 第{i}题首轮候选"))
        print(f"appended {len(tasks)} runs (existing lines={n_existing}) -> {args.jsonl}")
        return 0
    if args.cmd == "summary":
        summary(args.jsonl)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
