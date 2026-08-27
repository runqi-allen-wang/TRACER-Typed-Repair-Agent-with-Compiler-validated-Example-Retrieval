"""Part1 驱动：用 ax-prover Python API 进程内跑，拿到完整指标。

与 run_baseline(subprocess CLI) 不同，此脚本直接调用 ax-prover 的
ProverAgent/prove_single_item，从 ProverAgentState 提取全部指标，并统计
每次 LLM 调用的 token/usage，从而覆盖 Part1 要求的：
token、成本、逐环节调用、轮数、成功节点、首轮候选、通过率。

用法：
  python run_api.py --target FATEM.Problem01:prod_card_eq_card_pow --folder <fate_v432> --config <yaml> --out <jsonl>
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import inspect
import json
import time
import uuid
from pathlib import Path

# ---------- patch openai: tolerate betas / thinking ----------
import openai.resources.chat.completions.completions as _C  # noqa: E402


def _tol(orig):
    params = inspect.signature(orig).parameters
    has_vkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    @functools.wraps(orig)
    def w(self, *a, **kw):
        if not has_vkw:
            kw = {k: v for k, v in kw.items() if k in params}
        else:
            kw.pop("betas", None)
            kw.pop("thinking", None)
        return orig(self, *a, **kw)

    return w


for _c in (getattr(_C, "AsyncCompletions", None), getattr(_C, "Completions", None)):
    if _c:
        for _m in ("parse", "create"):
            if hasattr(_c, _m):
                setattr(_c, _m, _tol(getattr(_c, _m)))

# ---------- patch LLMClient.ainvoke to collect usage ----------
from ax_prover.utils import llm as _llmmod  # noqa: E402

_USAGE = {"prompt": 0, "completion": 0, "calls": 0}
_orig_ainvoke = _llmmod.LLMClient.ainvoke


async def _patched_ainvoke(self, messages, **kw):
    out = await _orig_ainvoke(self, messages, **kw)
    try:
        um = getattr(out, "usage_metadata", None) or (out.response_metadata or {}).get("token_usage") or {}
        _USAGE["prompt"] += int(um.get("input_tokens", um.get("prompt_tokens", 0)) or 0)
        _USAGE["completion"] += int(um.get("output_tokens", um.get("completion_tokens", 0)) or 0)
        _USAGE["calls"] += 1
    except Exception:
        pass
    return out


_llmmod.LLMClient.ainvoke = _patched_ainvoke


def _snap():
    return dict(_USAGE)


def _diff(a, b):
    return {k: b[k] - a[k] for k in a}


def extract_record(target: str, item, state, u: dict, price: dict) -> dict:
    """Extract full Part1 fields from a ProverAgentState."""
    from ax_prover.models.messages import ProposalMessage  # noqa: E402

    msgs = list(getattr(state, "messages", []) or [])
    proposals = [m for m in msgs if isinstance(m, ProposalMessage)]
    first = proposals[0].code if proposals else ""
    metrics = state.metrics.model_dump() if hasattr(state, "metrics") else {}
    prompt = u.get("prompt", 0)
    completion = u.get("completion", 0)
    total = prompt + completion
    cost = (prompt / 1000 * price.get("input_usd_per_1k", 0.0)) + (
        completion / 1000 * price.get("output_usd_per_1k", 0.0)
    )
    rounds = state.iteration_count if hasattr(state, "iteration_count") else len(proposals)
    is_proven = bool(getattr(state, "approved", False))
    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": target,
        "theorem": getattr(state.item.location, "name", None),
        "path": getattr(state.item.location, "path", None),
        "compile_ok": is_proven,
        "success_node": rounds if is_proven else None,
        "rounds": rounds,
        "iteration_count": metrics.get("number_of_iterations", rounds),
        "compilation_error_count": metrics.get("compilation_error_count", 0),
        "build_timeout_count": metrics.get("build_timeout_count", 0),
        "reviewer_rejections": metrics.get("reviewer_rejections", 0),
        "max_iterations_reached": metrics.get("max_iterations_reached", False),
        "call_count": u.get("calls", 0),
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total},
        "estimated_cost_usd": round(cost, 6),
        "first_round_candidate": first,
        "candidate_count": len(proposals),
    }


async def run_target(target: str, folder: str, config_yaml: str, price: dict) -> list[dict]:
    from ax_prover.config import Config  # noqa: E402
    from ax_prover.prover.agent import ProverAgent  # noqa: E402
    from ax_prover.runtime import Runtime  # noqa: E402
    from ax_prover.tools import create_tool_lifespans  # noqa: E402
    from ax_prover.utils import (  # noqa: E402
        load_env_secrets,
        merge_configs,
        parse_prove_target,
        prove_single_item,
    )

    load_env_secrets(folder)
    config = merge_configs([Config(), config_yaml], folder=folder)
    tool_lifespans = await create_tool_lifespans(config.prover.proposer_tools)
    records: list[dict] = []
    async with Runtime.open(config.runtime, folder, tool_lifespans) as rt:
        items = await parse_prove_target(rt.lean_interact_server, folder, target)
        for item in items:
            before = _snap()
            prover = await ProverAgent.create(config.prover, rt)
            thread_id = f"run_api_{item.location.name}_{uuid.uuid4().hex[:6]}"
            state = await prove_single_item(prover, item, thread_id=thread_id)
            used = _diff(before, _snap())
            records.append(extract_record(target, item, state, used, price))
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--price-out", type=float, default=0.0)
    ap.add_argument("--price-in", type=float, default=0.0)
    args = ap.parse_args()

    price = {"input_usd_per_1k": args.price_in, "output_usd_per_1k": args.price_out}
    recs = asyncio.run(run_target(args.target, args.folder, args.config, price))
    out = Path(args.out)
    with out.open("a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(recs)} record(s) -> {out}")
    for r in recs:
        print(
            f"  {r['theorem']}: proven={r['compile_ok']} rounds={r['rounds']} "
            f"calls={r['call_count']} tokens={r['usage']['total_tokens']} cost=${r['estimated_cost_usd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
