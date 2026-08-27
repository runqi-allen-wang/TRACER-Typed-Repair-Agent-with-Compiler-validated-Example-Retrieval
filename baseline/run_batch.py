"""Part1 批量驱动：逐题跑，逐题报告，按精确单价估算成本。

单价：gpt-5.6-sol 输入 $4/1M、输出 $20/1M，中转倍率 0.26
  -> 有效 input = $1.04/1M (0.00104/1k)，output = $5.20/1M (0.0052/1k)

用法： python run_batch.py <manifest> <folder> <config> <out.jsonl> [limit] [tier]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_api  # noqa: E402

PRICE_IN = 0.00104  # $4/1M * 0.26
PRICE_OUT = 0.0052  # $20/1M * 0.26


def load_manifest(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    manifest = Path(sys.argv[1])
    folder = sys.argv[2]
    config = sys.argv[3]
    out = Path(sys.argv[4])
    limit = int(sys.argv[5]) if len(sys.argv) > 5 else 5
    tier = sys.argv[6] if len(sys.argv) > 6 else "core"

    items = [x for x in load_manifest(manifest) if x.get("tier") == tier][:limit]
    price = {"input_usd_per_1k": PRICE_IN, "output_usd_per_1k": PRICE_OUT}
    n = len(items)
    print(f"batch: tier={tier} count={n}")

    with out.open("a", encoding="utf-8") as fh:
        for i, item in enumerate(items, 1):
            target = f"{item['module']}:{item['theorem']}"
            try:
                recs = asyncio.run(run_api.run_target(target, folder, config, price))
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{n}] {item['theorem']}: ERROR {e}")
                continue
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(
                    f"[{i}/{n}] {r['theorem']}: proven={r['compile_ok']} "
                    f"rounds={r['rounds']} calls={r['call_count']} "
                    f"tokens={r['usage']['total_tokens']} cost=${r['estimated_cost_usd']}"
                )
            fh.flush()
    print(f"wrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
