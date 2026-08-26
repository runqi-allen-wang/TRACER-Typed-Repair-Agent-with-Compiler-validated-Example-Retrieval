# Part 1 — Baseline 准备（对应《一些细化idea.md》Part 1）

本目录是 Zhewen 在 `docs/一些细化idea.md` 里 Part 1 的**可复现基建**。目标：把
`AxProverBase` 冻结为基线 agent，固定环境/模型/预算，并逐环节记录指标，为后续对比
`AxProverBase + CapsuleFeedback` 做准备。

## 1. 锁定基线（外部依赖，固定 commit）

- 上游仓库：https://github.com/Axiomatic-AI/ax-prover-base
- **锁定 commit**：`06dfadc9ab439755af5efcfe0add95bfef2733c7`
- 论文：A Minimal Agent for Automated Theorem Proving（arXiv 2602.24273 / ICML 2026）
- 引入方式：**外部依赖**，不把其代码并入本仓库；只记录其 commit 并按其 README 安装。

```bash
# 安装 ax-prover（锁定版本与 commit 由上游保证；如需可 pin 到对应 tag）
pip install ax-prover

# 配置 API key（至少一个）
export ANTHROPIC_API_KEY=sk-ant-...   # Claude Opus 4.5 效果最佳
# 可选：export OPENAI_API_KEY=... / GOOGLE_API_KEY=...
# 可选：export TAVILY_API_KEY=...（web 搜索）

# 用法
cd /path/to/lean4-project
ax-prover prove MyModule:my_theorem
```

## 2. 冻结配置

见 `baseline_config.yaml`。要点（对齐 Zhewen："冻结 **AxProverBase commit、Lean/Mathlib 环境、模型、工具和预算**"）：

- `prover.prover_llm.model`：`anthropic:claude-opus-4-20250514`（默认；可按预算换）
- `prover.prover_llm.thinking.budget_tokens`：`32000`（论文：32k 优于 10k）
- `prover.max_iterations`：`50`
- `prover.tools`：LeanSearch 开 / web 搜索关（竞赛场景 web 几乎无帮助）
- `prover.memory.mode`：`self_managed`（论文最优；消融可切 `history` / `none`）

```bash
ax-prover --config baseline_config.yaml prove MyModule:theorem
```

## 3. 逐环节指标记录

`metrics_logger.py` 作为 run 的**逐环节记录层**（proposer / memory / reviewer / tool 各自
调用数、token、成本、编译时间、成功节点），并缓存每题首轮候选。不依赖真实模型即可
`--mock` 自测：

```bash
python baseline/metrics_logger.py --mock --tasks 3 --out runs --jsonl runs/metrics.jsonl
python baseline/metrics_logger.py --summary --jsonl runs/metrics.jsonl
```

## 4. 与 CapsuleFeedback 的挂接点（后续 Part 2 用）

Zhewen 建议把我们的模块替换 AxProverBase 的**两个环节**：

| AxProverBase 环节 | 我们的替换 |
|---|---|
| 失败 → 返回编译错误 / 目标状态 | **CapsuleFeedback**：错误类别 + 稳定指纹 + 重复次数 + 诊断漂移 |
| Memory 压缩失败经验 | **CapsuleFeedback**：紧凑失败历史（复用胶囊诊断，不重复编译） |

本目录先只做 Part1（基线与指标）；CapsuleFeedback 的封装在保真度与案例集优化后接入。

## 5. 题集起点

基线题集起点复用仓库现有 `benchmarks/manifest.json` 的 18 题；后续按 idea 从公开
benchmark 固定抽 20~30 题（core 12 + challenge 4）并冻结 Lean/Mathlib 版本与预算。
