"""No-network/API smoke test against the installed, pinned AxProverBase package."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ax_prover.config import Config  # noqa: E402
from ax_prover.models.messages import BuildFailedFeedback  # noqa: E402
from ax_prover.utils.config import merge_configs  # noqa: E402
from ax_prover.utils.llm import LLMClient  # noqa: E402

from leancapsule.ax_integration import (  # noqa: E402
    CapsuleFeedbackSessions,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
)


def main() -> int:
    merged = merge_configs(
        [Config(), str(ROOT / "configs" / "axprover_part2_capsule.yaml")],
        folder=ROOT,
    )
    config = merged.prover
    enforce_ax_part2_config(config)
    previous_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "part2-smoke-placeholder-not-a-real-key"
    try:
        llm_client = LLMClient(config.prover_llm)
    finally:
        if previous_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_key
    source_feedback = BuildFailedFeedback(error_output="Demo.lean:1:1: error: type mismatch")
    capsule = CapsuleFeedbackSessions().observe("Demo.lean:target", source_feedback, round_no=1)
    agent_class = install_axproverbase_capsule_feedback()
    checks = {
        "model": config.prover_llm.model,
        "base_url": config.prover_llm.provider_config["base_url"],
        "max_input_tokens": config.prover_llm.provider_config["profile"]["max_input_tokens"],
        "llm_profile_max_input_tokens": llm_client.profile.get("max_input_tokens"),
        "memory": config.memory_config.class_name,
        "summary_enabled": config.summarize_output.enabled,
        "category": capsule["category"],
        "agent_class": agent_class.__name__,
    }
    ok = checks == {
        "model": "openai:deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "max_input_tokens": 65536,
        "llm_profile_max_input_tokens": 65536,
        "memory": "MemorylessProcessor",
        "summary_enabled": False,
        "category": "type_mismatch",
        "agent_class": "ProverAgent",
    }
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
