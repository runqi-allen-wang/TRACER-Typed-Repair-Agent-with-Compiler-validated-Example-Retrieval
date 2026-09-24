"""离线预检 Feedback Study v1 第二模型复现合同，不读取密钥或访问网络。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feedback_study import (  # noqa: E402
    apply_direct_model_config,
    build_plan,
    validate_config,
    validate_replication_reference,
)
from research import load_benchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-release", type=Path,
        default=(
            ROOT
            / "historical"
            / "feedback_study_v1"
            / "published"
            / "feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248"
        ),
    )
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/feedback_study.example.json")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "benchmarks/repair24/manifest.json")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--thinking", choices=("enabled", "disabled"))
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"))
    args = parser.parse_args()
    try:
        config = apply_direct_model_config(
            validate_config(args.config),
            api_url=args.api_url,
            model=args.model,
            model_id=args.model_id,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            thinking=args.thinking,
            reasoning_effort=args.reasoning_effort,
        )
        benchmark = load_benchmark(args.benchmark)
        contract = validate_replication_reference(config, benchmark, args.reference_release)
        tasks = build_plan(config, benchmark)
        result = {
            "ok": True,
            "network_calls": 0,
            "api_key_read": False,
            "tasks": len(tasks),
            "max_generations": len(tasks) * config.get("max_rounds", 3),
            "contract": contract,
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        result = {"ok": False, "network_calls": 0, "api_key_read": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
