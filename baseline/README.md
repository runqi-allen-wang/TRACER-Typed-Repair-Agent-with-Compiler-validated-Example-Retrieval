# Part 1 — Baseline 可运行实验框架（对齐《一些细化idea.md》Part 1）

**现在 Part1 已到"接一个 API 即可完整运行"的状态。** 目标：把 `AxProverBase` 冻结为基线
agent，固定环境/模型/预算，逐环节记录指标，并缓存每题首轮候选，为
`AxProverBase + CapsuleFeedback` 对比做准备。

## 逐条对齐 idea Part 1

| idea 要求 | 现状（文件） |
|---|---|
| 固定抽取 20~30 题 | `manifest.json`（**25 题，全部来自公开 benchmark FATE-M**，15 core + 10 challenge） |
| 冻结 AxProverBase commit | 锁定 `06dfadc9...`（见 `config.yaml environment` / README 说明） |
| 冻结 Lean/Mathlib 环境 | `fate_v432/` 锁定 lean/mathlib **v4.32.0** |
| 冻结模型、工具、预算 | `config.yaml prover.*` |
| 先跑 Experience(memory)，补 Memoryless | `memory.matrix: [self_managed, none]`；可 `--memory` 覆盖 |
| 关闭不参与证明的最终 summary | `enable_summary: false` |
| 逐环节记录调用/token/成本/编译时间/成功节点 | `metrics_logger.py` + `run_baseline.py` |
| 缓存每题首轮候选 | `run_baseline.py` 写 `run.cache_file` |

## 只需三步即可运行

**1. 准备 API 与 Lean 环境**
```bash
export OPENAI_API_KEY=sk-...        # 你的 OpenAI 兼容 key（gpt-5.6-sol 走 spacetimeai）
# 本机已有 Lean 4.32 + 安装 ax-prover
pip install ax-prover pyyaml

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
- **版本对齐**：本基线锁定 **Lean/Mathlib v4.32.0**，与仓库 capsule 的 `mathlib_project/` 环境一致。
  FATE-M 上游 `main` 为 v4.33.0、tag 只到 v4.28.0，**没有 v4.32.0 版本**；因此不直接 clone FATE-M 上游，
  而是用 **`fate_v432/`** 工程（`lean-toolchain` + `lakefile.lean` 均锁 mathlib v4.32.0），把 FATE-M 的
  25 题（`FATEM/1.lean`~`FATEM/25.lean`）放进该工程，使题源与 capsule 版本一致。
- **依赖**：题集依赖 **mathlib4 @ v4.32.0**，构建较重（可用 `lake exe cache get` 拉预编译缓存加速）。
- **模型**：`openai:gpt-5.6-sol`（`base_url=https://spacetimeai.cc/v1`，key 用 `OPENAI_API_KEY` 环境变量，**不写进仓库**）。
- **基线**：AxProverBase，锁定 commit `06dfadc9ab439755af5efcfe0add95bfef2733c7`。
- **记录**：`runs/metrics.jsonl` 每题×记忆模式的逐环节指标；`.baseline_cache.json` 首轮候选缓存。

## 在 GitHub 上跑（真实数据）
`.github/workflows/part1_run.yml`（手动触发）会在 runner 上：安装 ax-prover → lean toolchain →
切到锁 mathlib **v4.32.0** 的 `fate_v432/` 工程 → `lake build`（构建 mathlib v4.32.0，**耗时/易超时**）
→ 临时把 config 切到 `openai:gpt-5.6-sol` + 该工程 → `run_baseline.py --limit 3` → 上传
`runs/metrics.jsonl` 为 artifact。

**前提**：在仓库 **Settings → Secrets and variables → Actions** 添加 secret **`OPENAI_API_KEY`**
= 你的 DeepSeek key；然后在 Actions 里手动 **Run workflow**。
> 现在跑的是 **3 题 smoke**（验证全流程）；把 `--limit 3` 去掉即可跑全部 25 题。

## 题库构建与版本说明

### 版本口径（与 capsule 一致）
本基线把 **Lean / Mathlib 冻结为 v4.32.0**，与仓库 `capsules/`（`mathlib_project/` 依赖工程、`capsule.json` 的
`environment.lean_toolchain`）完全一致：
- `fate_v432/lean-toolchain` → `leanprover/lean4:v4.32.0`
- `fate_v432/lakefile.lean` → `require mathlib ... @ "v4.32.0"`

### 题库来源与构建（如何把 FATE 换成 v4.32.0）
题集沿用公开 benchmark **FATE-M**（https://github.com/frenzymath/FATE-M ）的**前 25 个定理**
（`FATE-M.json` 中 id 1~25，即 `manifest.json` 的 fate01~fate25）。但 FATE-M 上游**没有 v4.32.0 版本**
（tag 只到 v4.28.0，main 为 v4.33.0），因此**不直接 clone 上游**，而是：
1. 从 `FATE-M.json` 的 `formal_statement`（`import Mathlib` + 定理 + `sorry`）逐条取出前 25 条；
2. 按要求 `mathlib @ v4.32.0` 写入本工程 `fate_v432/FATEM/{1..25}.lean`；
3. 使题集与 capsule 版本一致，`manifest.json` 的 `module FATEM.1` / `file FATEM/1.lean` 对应不变。

**重建题库**（无源码时）：
```bash
python - <<'PY'
import json
d = json.load(open('FATE-M.json', encoding='utf-8'))   # 从上游下载的 FATE-M.json
byid = {x['id']: x for x in d}
for i in range(1, 26):
    open(f'fate_v432/FATEM/{i}.lean', 'w', encoding='utf-8').write(byid[i]['formal_statement'])
PY
```

### 构建（Linux / Docker 推荐，mathlib 可靠且可用预编译缓存）
```bash
cd fate_v432
lake update          # 拉取 mathlib 源码与依赖
lake exe cache get   # 拉 mathlib 预编译 .olean（几十分钟->几十秒，Windows 上通常拉不到）
lake build           # 编译题目（依赖已就绪则很快）
```
（本机构建即可，无需 Docker。）

### 运行与产物
```bash
# 自测（无模型）
python baseline/run_baseline.py --mock --limit 5 --out runs
# 真实（需本机 lean 4.32 + mathlib v4.32 已 build + ax-prover + OPENAI_API_KEY）
python baseline/run_baseline.py --out runs          # 或 --limit 3 先 smoke
python baseline/metrics_logger.py summary --jsonl runs/metrics.jsonl
```
- `runs/metrics.jsonl`：每题 × 记忆模式（`self_managed`/`none`）的 proposer/memory/reviewer/tool 调用、
  token、成本、编译耗时、成功节点、首轮候选。
- `.baseline_cache.json`：每题首轮候选缓存（A/B 共享用）。

### 依赖与环境冻结一览
| 项 | 冻结值 |
|---|---|
| Lean | `leanprover/lean4:v4.32.0` |
| Mathlib | `v4.32.0`（git `db584c6...`@manifest） |
| 题集 | FATE-M 前 25 题，`fate_v432/FATEM/` |
| agent | AxProverBase commit `06dfadc9ab439755af5efcfe0add95bfef2733c7` |
| 模型 | `openai:gpt-5.6-sol`（`base_url=https://spacetimeai.cc/v1`，key 用 `OPENAI_API_KEY`） |
| 记忆模式 | `[self_managed, none]`（先 Experience、补 Memoryless） |

### 当前运行配置与单价（冻结说明）
| 项 | 值 |
|---|---|
| 模型 | `openai:gpt-5.6-sol` @ `https://spacetimeai.cc/v1` |
| max_iterations | `4` |
| lean_search / web_search | 关闭（`null`） |
| summarize_output | 关闭（`enabled=false`） |
| memory | `ExperienceProcessor`（`init_args.llm_config` 用同模型） |
| 单价（官方） | 输入 `$4/1M`、输出 `$20/1M` |
| 中转倍率 | `0.26` |
| 有效单价 | 输入 `$1.04/1M`、输出 `$5.20/1M` |
| cost 公式 | `prompt/1000*0.00104 + completion/1000*0.0052` |
| 驱动 | `run_api.py`（单题）/ `run_batch.py`（批量，5 题一批，逐题报告） |

说明：由于 ax-prover 开发版(06dfadc9) 的结构化输出会向 openai `parse/create` 传 `betas/thinking`，
需用 `run_patched.py` 或 `run_api.py`（内置 patch）在运行前给 openai 打补丁剔除这些字段。

## 验证
```powershell
python baseline/config_check.py
python baseline/metrics_logger.py mock --tasks 5 --jsonl "$env:TEMP\m.jsonl"; python baseline/metrics_logger.py summary --jsonl "$env:TEMP\m.jsonl"
powershell -File baseline/verify.ps1
```
CI（`.github/workflows/part1.yml`）也会自动校验 config 契约 + mock 流程 + 锁定 commit。
