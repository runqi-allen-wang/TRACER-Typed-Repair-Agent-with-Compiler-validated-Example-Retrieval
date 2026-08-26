"""Part 1 实验 runner：逐题驱动 AxProverBase 并记录逐环节指标。

对齐《一些细化idea.md》Part 1：
  - 固定抽取题集（manifest.json），冻结配置（config.yaml）
  - 先跑 Experience(self_managed)、可补 Memoryless(none)（memory.matrix）
  - 关闭不参与证明的最终 summary（enable_summary=false，仅作为标志记录）
  - 逐环节记录 proposer/memory/reviewer/tool 调用、token、成本、编译时间、成功节点
  - 缓存每题首轮候选（cache_file）

用法：
  # 无模型自测
  python baseline/run_baseline.py --mock --limit 5 --out runs
  # 真实运行（需 Lean 环境 + ANTHROPIC_API_KEY + 本机/容器内安装 ax-prover 与 lean）
  python baseline/run_baseline.py --out runs
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import yaml  # noqa: E402
from metrics_logger import append_jsonl, cost_usd  # noqa: E402


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_axp_config(cfg: dict, workdir: Path) -> Path:
    """把冻结配置里 ax-prover 认可的字段抽成临时 config。"""
    con = cfg["prover"]
    axp = {
        "prover": {
            "max_iterations": con["max_iterations"],
            "prover_llm": con["prover_llm"],
            "memory": con["memory"],
            "reviewer": con["reviewer"],
        }
    }
    p = workdir / "_axp_config.yaml"
    p.write_text(yaml.safe_dump(axp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def _parse_axp_output(json_path: Path) -> dict:
    """尽力解析 ax-prover 的 -o 输出；结构未知时返回空并保留原始内容。"""
    if not json_path.exists():
        return {"raw": None}
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"raw": raw}
    usage = raw.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    usage = {
        "prompt_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
        "completion_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
        "total_tokens": usage.get(
            "total_tokens",
            usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        ),
    }
    status = (raw.get("status") or raw.get("result") or raw.get("ok") or "").lower()
    ok = isinstance(status, bool) and status or (status in ("success", "passed", "true", "ok"))
    return {
        "ok": ok,
        "rounds": raw.get("rounds", raw.get("iterations", 0)),
        "candidate": raw.get("candidate", raw.get("proof", "")),
        "usage": usage,
        "cost": raw.get("cost", raw.get("estimated_cost_usd", None)),
        "compile_elapsed_ms": raw.get("compile_elapsed_ms", 0),
        "raw": raw,
    }


def run_task_axprover(cfg: dict, item: dict, memory_mode: str, workdir: Path) -> dict:
    axp_cfg = _write_axp_config(cfg, workdir)
    out_json = workdir / f"_res_{uuid.uuid4().hex[:8]}.json"
    cmd = [cfg["run"]["axprover_command"], "--config", str(axp_cfg), "prove",
           f"{item['module']}:{item['theorem']}", "-o", str(out_json)]
    if cfg["run"].get("skip_build"):
        cmd.append("--skip-build")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, timeout=300)
    elapsed = int((time.time() - t0) * 1000)
    parsed = _parse_axp_output(out_json)
    price = (cfg["run"].get("price") or {})
    p_in = price.get("input_usd_per_1k") or 0.0
    p_out = price.get("output_usd_per_1k") or 0.0
    usage = parsed.get("usage", {"prompt_tokens": 0, "completion_tokens": 0})
    if parsed.get("cost") is not None:
        est_cost = parsed["cost"]
    else:
        est_cost = cost_usd(usage, p_in, p_out)
    ok = parsed.get("ok", False)
    rounds = parsed.get("rounds", 0) or 1
    return {
        "rounds": rounds,
        "compile_ok": ok,
        "success_node": rounds if ok else None,
        "compile_elapsed_ms": parsed.get("compile_elapsed_ms", elapsed),
        "first_round_candidate": parsed.get("candidate", ""),
        "calls": {
            "proposer_calls": rounds,
            "memory_calls": rounds,
            "reviewer_calls": rounds,
            "tool_calls": rounds,
        },
        "usage": usage,
        "estimated_cost_usd": est_cost,
        "raw": parsed.get("raw"),
        "returncode": proc.returncode,
    }


def run_task_mock(item: dict, memory_mode: str, cfg: dict) -> dict:
    rounds = 0
    ok = False
    while rounds < cfg["prover"]["max_iterations"]:
        rounds += 1
        if random.random() < 0.5:
            ok = True
            break
    usage = {"prompt_tokens": random.randint(400, 2000), "completion_tokens": random.randint(300, 1600)}
    price = cfg["run"].get("price") or {}
    return {
        "rounds": rounds,
        "compile_ok": ok,
        "success_node": rounds if ok else None,
        "compile_elapsed_ms": random.randint(800, 12000),
        "first_round_candidate": f"by intro h; exact h  # {item['id']}@{memory_mode} 首轮候选",
        "calls": {"proposer_calls": rounds, "memory_calls": rounds, "reviewer_calls": rounds, "tool_calls": rounds},
        "usage": usage,
        "estimated_cost_usd": cost_usd(usage, price.get("input_usd_per_1k", 0.06), price.get("output_usd_per_1k", 0.3)),
        "raw": None,
        "returncode": 0,
    }


def make_record(item, memory_mode, model, res: dict) -> dict:
    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_id": item["id"],
        "title": item.get("title"),
        "module": item.get("module"),
        "theorem": item.get("theorem"),
        "tier": item.get("tier"),
        "condition": "baseline",
        "memory_mode": memory_mode,
        "model": model,
        "rounds": res["rounds"],
        "compile_ok": res["compile_ok"],
        "success_node": res["success_node"],
        "compile_elapsed_ms": res["compile_elapsed_ms"],
        "first_round_candidate": res["first_round_candidate"],
        "calls": res["calls"],
        "usage": res["usage"],
        "estimated_cost_usd": res["estimated_cost_usd"],
        "returncode": res.get("returncode"),
    }


def load_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--memory", default=None, help="覆盖 memory 矩阵（如 self_managed / none）")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    items = load_manifest(args.manifest)
    if args.limit:
        items = items[: args.limit]
    mems = args.memory.split(",") if args.memory else cfg["prover"]["memory"]["matrix"]
    out_dir = args.out or (HERE / cfg["run"]["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "metrics.jsonl"
    cache_path = HERE / cfg["run"]["cache_file"]

    cache = load_cache(cache_path)
    model = cfg["prover"]["prover_llm"]["model"]

    for item in items:
        if not item.get("theorem"):
            print(f"[skip] {item['id']} {item['title']}（module/theorem 未填，跳过）")
            continue
        for mem in mems:
            key = f"{item['id']}__{mem}"
            if args.mock:
                res = run_task_mock(item, mem, cfg)
            else:
                res = run_task_axprover(cfg, item, mem, HERE.parent)  # Lean 工程在仓库根
            record = make_record(item, mem, model, res)
            append_jsonl(jsonl, record)
            first = record["first_round_candidate"]
            if first:
                cache.setdefault(key, first)
            print(f"[{'mock' if args.mock else 'run'}] {key}: ok={record['compile_ok']} "
                  f"rounds={record['rounds']} cost=${record['estimated_cost_usd']:.4f}")

    save_cache(cache_path, cache)
    print(f"\nwritten -> {jsonl}（{sum(1 for _ in open(jsonl, encoding='utf-8'))} 条）")
    print(f"first-round candidates cached -> {cache_path}（{len(cache)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
