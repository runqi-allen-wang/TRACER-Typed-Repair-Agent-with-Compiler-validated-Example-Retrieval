# 三臂归因方案：Experience × CapsuleFeedback 对照臂

> 配套代码见 `baseline/run_part2.py`、`src/leancapsule/ax_integration.py` 与
> 配置 `configs/axprover_experience_capsule.yaml`。

## 问题：现有 Part1 / Part2 不能归因 CapsuleFeedback

当前实验把 Memory 与 Feedbalance 同时改动：

| 臂 | Memory | Feedback |
|---|---|---|
| Part 1 `baseline` | Experience（调 LLM） | 原生（Proposer 自带） |
| Part 2 `capsule` | Memoryless（0 LLM） | CapsuleFeedback |

Part1→Part2 的差值（如 LLM calls 79→34）**同时混入了 Memory 与 Feedback 两个变量**，无法把差值归因给 CapsuleFeedback。同一个 LLM 调用数的下降可能只是 Memoryless 削掉了 memory node 调用，与反馈内容无关。

## 方案：新增"Experience + CapsuleFeedback"对照臂

让 Memory 固定为 Experience（与 Part 1 相同，memory 仍走 yxai），只把 Feedback 换成 CapsuleFeedback：

| 臂 | memory | feedback | 用途 |
|---|---|---|---|
| `baseline` | Experience | 原生 | 基准 |
| **`capsule_experience`（新）** | **Experience** | **CapsuleFeedback** | 归因 Feedback |
| `capsule`（Part2） | Memoryless | CapsuleFeedback | 归因 Memory |

- **Feedback 归因**：`capsule_experience − baseline`。两端 memory 都是 Experience，只差 Feedback。
- **Memory 归因**：`capsule_experience − capsule`。两端都是 CapsuleFeedback，只差 Memory。

## 归因读法（关注点）

- **CapsuleFeedback 效果** = `baseline → capsule_experience`（LLM calls / rounds / 成功率的变化）。
- **Experience/Memory 效果** = `capsule → capsule_experience`。
- 若 `baseline` 与 `capsule_experience` 几乎一致、而 `capsule` 明显更省，则说明**此前的 79→34 主要来自去掉 Memory**，而非 CapsuleFeedback。这会让"Part2 归因于 CapsuleFeedback"的说法降级。

## 运行（同一 yxai 配置、同一题集、同一首轮缓存）

对照臂复用 Part 1 的首轮候选缓存（`CAPSULE_FIRST_ROUND_CACHE`），保证三种条件的首轮上下文完全一致：

```powershell
$env:OPENAI_API_KEY = "<yxai key>"
$env:CAPSULE_FEEDBACK_STATE_DIR = (Join-Path $PWD "results\capsule-experience-state")
$env:CAPSULE_FEEDBACK_METRICS = (Join-Path $PWD "results\capsule-experience-metrics.jsonl")
$env:CAPSULE_FIRST_ROUND_CACHE = (Join-Path $PWD "results\part2-first-round.json")
python .\baseline\run_part2.py `
    --baseline .\runs\baseline.jsonl `
    --folder "C:\path\to\lean-project" `
    --config .\configs\axprover_experience_capsule.yaml `
    --memory-class ExperienceProcessor `
    --out .\runs\capsule-experience.jsonl
```

- `--memory-class ExperienceProcessor` 会把记录的 `condition` 标为 `capsule_experience`、
  `memory_mode` 为 `experience_capsule_feedback`、`memory_processor` 为 `ExperienceProcessor`。
- 其余校验（模型 `gpt-5.6-sol`、`responses` wire API、`store=false`、`reasoning.effort=high`、
  关闭 summary、正 budget）与 Part 2 完全一致，故三种条件除 Memory 类型外无差异。
- **重要**：对照臂的 Memory 节点会调用 LLM，因此 `memory_llm_calls` / `calls.memory_calls` **不再为 0**；
  这部分调用计入 `call_count` 与 token，勿与 Part 2 的 0-memory 条件混排。

## 配对门禁

现有 `scripts/validate_part2_pairing.py` 仍适合 `baseline ↔ capsule`；对比
`baseline ↔ capsule_experience` 时，请务必核对两端的 `memory_processor` 都是
`ExperienceProcessor`（它只接受 `condition=baseline` / `capsule`，需要为
`capsule_experience` 补一个允许的 condition 集合后再跑，或直接比对
`baseline.jsonl` 与 `capsule-experience.jsonl` 的同题 metrics）。

## 待办

- [ ] 在 `main` 上真正跑出 `capsule_experience`（需 yxai key + 已构建题集工程）。
- [ ] 更新 `scripts/validate_part2_pairing.py` 接受 `capsule_experience` 条件。
- [ ] 在 Part 3 统计中把三臂放进来，用 `baseline↔capsule_experience` 与
      `capsule↔capsule_experience` 两个对照分别归因。
