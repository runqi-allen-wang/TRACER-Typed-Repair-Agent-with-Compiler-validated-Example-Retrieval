"""校验 baseline/config.yaml 是否符合 ax-prover 的配置契约（对照其 README）。

用法： python baseline/config_check.py
失败时退出码非 0。
"""

from __future__ import annotations

import sys
import yaml


def main() -> int:
    path = "baseline/config.yaml"
    d = yaml.safe_load(open(path, encoding="utf-8"))
    errors: list[str] = []

    p = d.get("prover", {})
    llm = p.get("prover_llm", {})
    model = llm.get("model", "")
    if not (model.startswith("anthropic:") or model.startswith("openai:") or model.startswith("google:")):
        errors.append("prover_llm.model 必须以 anthropic:/openai:/google: 前缀开头")
    if not isinstance(llm.get("temperature"), (int, float)):
        errors.append("prover_llm.temperature 需为数值")
    if model.startswith("anthropic:"):
        think = llm.get("thinking", {})
        if think.get("type") != "enabled":
            errors.append("prover_llm.thinking.type 应为 enabled")
        if not isinstance(think.get("budget_tokens"), int):
            errors.append("prover_llm.thinking.budget_tokens 需为整数")
    if not isinstance(p.get("max_iterations"), int):
        errors.append("prover.max_iterations 需为整数")
    mem = p.get("memory", {}).get("mode")
    if mem not in ("self_managed", "history", "none"):
        errors.append(f"prover.memory.mode 非法: {mem!r}")
    tools = p.get("tools", {})
    for k in ("lean_search", "web_search"):
        if not isinstance(tools.get(k), bool):
            errors.append(f"prover.tools.{k} 需为布尔")
    budgets = p.get("budgets", {})
    if not isinstance(budgets.get("max_llm_calls"), int):
        errors.append("prover.budgets.max_llm_calls 需为整数")

    if errors:
        print("config 契约校验失败:")
        for e in errors:
            print("  -", e)
        return 1
    print("config 契约校验通过:", model,
          "| max_iterations", p.get("max_iterations"),
          "| memory", mem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
