# Part 1 — Baseline 可运行实验框架（对齐《一些细化idea.md》Part 1）

**现在 Part1 已到"接一个 API 即可完整运行"的状态。** 目标：把 `AxProverBase` 冻结为基线
agent，固定环境/模型/预算，逐环节记录指标，并缓存每题首轮候选，为
`AxProverBase + CapsuleFeedback` 对比做准备。

## 逐条对齐 idea Part 1

| idea 要求 | 现状（文件） |
|---|---|
| 固定抽取 20~30 题 | `manifest.json`（**25 题，全部来自公开 benchmark FATE-M**，15 core + 10 challenge） |
| 冻结 AxProverBase commit | 锁定 `06dfadc9...`（见 `config.yaml environment` / README 说明） |
| 冻结 Lean/Mathlib 环境 | `config.yaml environment.*` + `Dockerfile`（lean4:v4.32.0） |
| 冻结模型、工具、预算 | `config.yaml prover.*` |
| 先跑 Experience(memory)，补 Memoryless | `memory.matrix: [self_managed, none]`；可 `--memory` 覆盖 |
| 关闭不参与证明的最终 summary | `enable_summary: false` |
| 逐环节记录调用/token/成本/编译时间/成功节点 | `metrics_logger.py` + `run_baseline.py` |
| 缓存每题首轮候选 | `run_baseline.py` 写 `run.cache_file` |

## 只需三步即可运行

**1. 准备 API 与 Lean 环境**
```bash
export OPENAI_API_KEY=sk-...        # DeepSeek key（OpenAI 兼容端点）
# Lean 环境：用 Docker 最省事（绕开本机装 Lean，见 baseline/Dockerfile）
docker build -t axprover-baseline -f baseline/Dockerfile .
# 或本机已有 Lean 4.32 + 安装 ax-prover
pip install ax-prover
```
> Docker 运行：
> `docker run --rm -it -v "$PWD:/workspace" -e OPENAI_API_KEY=sk-... axprover-baseline python baseline/run_baseline.py --out runs`

**2. 题集** —— `manifest.json` 已从公开 benchmark **FATE-M** 抽 25 题（15 core / 10 challenge），无需再填。

**3. 运行**
```bash
# 自测（无模型，验证流程）
python baseline/run_baseline.py --mock --limit 5 --out runs
# 真实运行（需 API key + Lean）
python baseline/run_baseline.py --out runs
```

## 产物
- `runs/metrics.jsonl`：每题×记忆模式的逐环节记录（proposer/memory/reviewer/tool 调用、
  token、成本、编译耗时、成功节点、首轮候选）。
- `.baseline_cache.json`：每题首轮候选缓存（供复现/后续 A/B 共享首轮候选）。
- `baseline/config_check.py`：校验 config 与 ax-prover 契约一致（CI 亦执行）。

## 成本与正确性说明（诚实边界）
- `estimated_cost_usd` 由 `run.price` 单价 × usage 估算；若 ax-prover 返回真实 `cost` 则优先用。
  **想精确请把 `run.price` 改成你的真实账单单价。**
- 逐环节调用数在真实模式按"每轮各视为一次"近似（ax-prover 若不逐环节上报）；精确值需解析其详细日志。
- 本框架保证**可复现、可记录、配置与依赖对齐**；**"结果是否正确/作弊与否"仍需真实模型 +
  人工 Reviewer 把关**。

## 题库与来源（重要）
- **题集**：`manifest.json` 的 25 题全部取自 **FATE-M**（Formal Algebra Theorem Evaluation-Medium，
  https://github.com/frenzymath/FATE-M ），选取其前 25 个定理，15 core / 10 challenge。
- **依赖**：FATE-M 依赖 **mathlib4 @ v4.28.0**（见其 lakefile），构建较重。
- **模型**：DeepSeek `deepseek-v4-flash`（`openai:` 前缀 + `base_url=https://api.deepseek.com/v1`，
  key 用 `OPENAI_API_KEY` 环境变量，**不写进仓库**）。
- **基线**：AxProverBase，锁定 commit `06dfadc9ab439755af5efcfe0add95bfef2733c7`。
- **记录**：`runs/metrics.jsonl` 每题×记忆模式的逐环节指标；`.baseline_cache.json` 首轮候选缓存。

## 在 GitHub 上跑（真实数据）
`.github/workflows/part1_run.yml`（手动触发）会在 runner 上：安装 ax-prover → lean toolchain →
clone FATE-M → `lake build`（构建 mathlib v4.28.0，**耗时/易超时**）→ 临时把 config 切到
`openai:deepseek-v4-flash` + FATE-M → `run_baseline.py --limit 3` → 上传 `runs/metrics.jsonl` 为 artifact。

**前提**：在仓库 **Settings → Secrets and variables → Actions** 添加 secret **`OPENAI_API_KEY`**
= 你的 DeepSeek key；然后在 Actions 里手动 **Run workflow**。
> 现在跑的是 **3 题 smoke**（验证全流程）；把 `--limit 3` 去掉即可跑全部 25 题。

## 验证
```powershell
python baseline/config_check.py
python baseline/metrics_logger.py mock --tasks 5 --jsonl "$env:TEMP\m.jsonl"; python baseline/metrics_logger.py summary --jsonl "$env:TEMP\m.jsonl"
powershell -File baseline/verify.ps1
```
CI（`.github/workflows/part1.yml`）也会自动校验 config 契约 + mock 流程 + 锁定 commit。
