"""Part1 批量驱动：逐题跑，逐题报告；仅在已配置单价时估算成本。

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

PRICE_IN = None
PRICE_OUT = None


def load_manifest(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    if len(sys.argv) < 5:
        print("usage: run_batch.py <manifest> <folder> <config> <out.jsonl> [limit] [tier]")
        return 2
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
    out.parent.mkdir(parents=True, exist_ok=True)
    failures = 0

    with out.open("a", encoding="utf-8") as fh:
        for i, item in enumerate(items, 1):
            target = f"{item['module']}:{item['theorem']}"
            try:
                recs = asyncio.run(
                    run_api.run_target(target, folder, config, price, task_metadata=item)
                )
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{n}] {item['theorem']}: ERROR {e}")
                failures += 1
                continue
            if not recs:
                print(f"[{i}/{n}] {item['theorem']}: ERROR no result record")
                failures += 1
                continue
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                cost = r["estimated_cost_usd"]
                cost_text = "unknown" if cost is None else f"${cost:.6f}"
                print(
                    f"[{i}/{n}] {r['theorem']}: proven={r['compile_ok']} "
                    f"rounds={r['rounds']} calls={r['call_count']} "
                    f"tokens={r['usage']['total_tokens']} cost={cost_text}"
                )
            fh.flush()
    print(f"wrote -> {out}")
    if failures:
        print(f"failed targets: {failures}/{n}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
