# Part 1 — Baseline 可运行实验框架（对齐《一些细化idea.md》Part 1）

**现在 Part1 已到"接一个 API 即可完整运行"的状态。** 目标：把 `AxProverBase` 冻结为基线
agent，固定环境/模型/预算，逐环节记录指标，并缓存每题首轮候选，为
`AxProverBase + CapsuleFeedback` 对比做准备。

## 逐条对齐 idea Part 1

| idea 要求 | 现状（文件） |
|---|---|
| 固定抽取 20~30 题 | `manifest.json`（20 条；18 条 seed 可跑 + 2 条 challenge 待填；正式题集替换为公开 benchmark） |
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
export ANTHROPIC_API_KEY=sk-ant-...        # 或 OPENAI_API_KEY / GOOGLE_API_KEY
# Lean 环境：用 Docker 最省事（绕开本机装 Lean）
docker build -t axprover-baseline -f baseline/Dockerfile .
# 或本机已有 Lean 4.32 + 安装 ax-prover
pip install ax-prover
```
> Docker 运行：
> `docker run --rm -it -v "$PWD:/workspace" -e ANTHROPIC_API_KEY=sk-ant-... axprover-baseline python baseline/run_baseline.py --out runs`

**2. 填题集**（`manifest.json`）——`t19`/`t20` 是 challenge 占位，把 `module/theorem/file` 填成公开
benchmark（PutnamBench / FATE-X / LeanCat）的题目即可；也可整体替换。

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

## 验证
```powershell
python baseline/config_check.py
python baseline/metrics_logger.py mock --tasks 5 --jsonl "$env:TEMP\m.jsonl"; python baseline/metrics_logger.py summary --jsonl "$env:TEMP\m.jsonl"
powershell -File baseline/verify.ps1
```
CI（`.github/workflows/part1.yml`）也会自动校验 config 契约 + mock 流程 + 锁定 commit。
