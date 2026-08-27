"""校验 baseline/config.yaml 是否符合 ax-prover 的配置契约（对照其 README）。

用法： python baseline/config_check.py
失败时退出码非 0。
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

import yaml


EXPECTED_MODEL = "openai:gpt-5.6-sol"
EXPECTED_BASE_URL = "https://yxai.chat/v1"
ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _check_provider(provider: object, errors: list[str], prefix: str) -> None:
    if not isinstance(provider, Mapping):
        errors.append(f"{prefix} 必须为 mapping")
        return
    if provider.get("base_url") != EXPECTED_BASE_URL:
        errors.append(f"{prefix}.base_url 必须为 {EXPECTED_BASE_URL}")
    if provider.get("use_responses_api") is not True:
        errors.append(f"{prefix}.use_responses_api 必须为 true")
    if provider.get("store") is not False:
        errors.append(f"{prefix}.store 必须为 false")
    reasoning = provider.get("reasoning")
    if not isinstance(reasoning, Mapping) or reasoning.get("effort") != "high":
        errors.append(f"{prefix}.reasoning.effort 必须为 high")
    if provider.get("output_version") != "responses/v1":
        errors.append(f"{prefix}.output_version 必须为 responses/v1")
    profile = provider.get("profile")
    if not isinstance(profile, Mapping) or profile.get("max_input_tokens") != 65536:
        errors.append(f"{prefix}.profile.max_input_tokens 必须为 65536")


def main() -> int:
    d = _load(ROOT / "baseline" / "config.yaml")
    shared = _load(ROOT / "configs" / "axprover_yxai_gpt56_sol.yaml")
    part1 = _load(ROOT / "configs" / "axprover_part1_experience.yaml")
    errors: list[str] = []

    p = d.get("prover", {})
    llm = p.get("prover_llm", {})
    model = llm.get("model", "")
    if model != EXPECTED_MODEL:
        errors.append(f"prover_llm.model 必须为 {EXPECTED_MODEL}")
    provider = llm.get("provider_config", {})
    _check_provider(provider, errors, "baseline provider_config")
    if p.get("max_iterations") != 4:
        errors.append("prover.max_iterations 必须冻结为 4")
    mem = p.get("memory", {}).get("mode")
    if mem not in ("self_managed", "history", "none"):
        errors.append(f"prover.memory.mode 非法: {mem!r}")
    tools = p.get("tools", {})
    for k in ("lean_search", "web_search"):
        if tools.get(k) is not False:
            errors.append(f"prover.tools.{k} 必须关闭")
    budgets = p.get("budgets", {})
    if not isinstance(budgets.get("max_llm_calls"), int):
        errors.append("prover.budgets.max_llm_calls 需为整数")
    environment = d.get("environment", {})
    if environment.get("benchmark_ref") != "v4.28.0":
        errors.append("environment.benchmark_ref 必须为 v4.28.0")
    if environment.get("lean_toolchain") != "leanprover/lean4:v4.28.0":
        errors.append("environment.lean_toolchain 必须为 leanprover/lean4:v4.28.0")

    shared_prover = shared.get("prover", {})
    shared_llm = shared_prover.get("prover_llm", {})
    if shared_llm.get("model") != EXPECTED_MODEL:
        errors.append(f"共享 Ax 配置 model 必须为 {EXPECTED_MODEL}")
    _check_provider(
        shared_llm.get("provider_config", {}),
        errors,
        "共享 Ax provider_config",
    )
    if shared_prover.get("max_iterations") != 4:
        errors.append("共享 Ax 配置 max_iterations 必须为 4")
    shared_tools = shared_prover.get("proposer_tools", {})
    if shared_tools != {"search_lean": None, "search_web": None}:
        errors.append("共享 Ax 配置必须关闭 search_lean/search_web")
    if shared_prover.get("summarize_output", {}).get("enabled") is not False:
        errors.append("共享 Ax 配置必须关闭最终 summary")
    if shared.get("runtime", {}).get("max_tool_calling_iterations") != 1:
        errors.append("共享 Ax 配置 max_tool_calling_iterations 必须为 1")

    if part1.get("import") != ["axprover_yxai_gpt56_sol.yaml"]:
        errors.append("Part 1 Ax 配置必须导入共享 yxai 配置")
    part1_memory = part1.get("prover", {}).get("memory_config", {})
    if part1_memory.get("class_name") != "ExperienceProcessor":
        errors.append("Part 1 Ax 配置必须使用 ExperienceProcessor")

    if errors:
        print("config 契约校验失败:")
        for e in errors:
            print("  -", e)
        return 1
    print("config 契约校验通过:", model, "@", provider.get("base_url"),
          "| max_iterations", p.get("max_iterations"),
          "| memory", mem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
