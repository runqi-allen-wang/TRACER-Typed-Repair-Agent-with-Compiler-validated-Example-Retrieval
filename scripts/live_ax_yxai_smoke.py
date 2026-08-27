"""One-request live smoke test for the pinned AxProverBase yxai path.

The API key must be supplied through OPENAI_API_KEY by a short-lived parent
process. This script never prints the key, the raw response, or exception text.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ax_prover.config import Config  # noqa: E402
from ax_prover.utils.config import merge_configs  # noqa: E402
from ax_prover.utils.llm import LLMClient  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from leancapsule.ax_integration import enforce_ax_part2_config  # noqa: E402


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    pieces: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") in {"text", "output_text"} and block.get("text"):
                pieces.append(str(block["text"]))
    return "".join(pieces)


async def _run() -> dict[str, object]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    merged = merge_configs(
        [Config(), str(ROOT / "configs" / "axprover_part2_capsule.yaml")],
        folder=ROOT,
    )
    config = merged.prover
    enforce_ax_part2_config(config)
    config.prover_llm.retry_config = {
        "stop_after_attempt": 1,
        "wait_exponential_jitter": False,
    }
    config.prover_llm.provider_config["timeout"] = 120
    config.prover_llm.provider_config["max_retries"] = 0

    client = LLMClient(config.prover_llm)
    started = time.perf_counter()
    response = await client.ainvoke([HumanMessage(content="Reply with exactly OK.")])
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    output = _message_text(response).strip()
    if api_key in output:
        raise RuntimeError("provider response reflected the credential")

    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, Mapping):
        usage = {}
    return {
        "ok": bool(output),
        "model": config.prover_llm.model,
        "endpoint": config.prover_llm.provider_config["base_url"],
        "wire_api": "responses",
        "store": config.prover_llm.provider_config["store"],
        "reasoning_effort": config.prover_llm.provider_config["reasoning"]["effort"],
        "output_received": bool(output),
        "output_exact_ok": output == "OK",
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "elapsed_ms": elapsed_ms,
    }


def main() -> int:
    try:
        result = asyncio.run(_run())
    except Exception as exc:
        result = {
            "ok": False,
            "error_type": type(exc).__name__,
            "http_status": getattr(exc, "status_code", None),
        }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
