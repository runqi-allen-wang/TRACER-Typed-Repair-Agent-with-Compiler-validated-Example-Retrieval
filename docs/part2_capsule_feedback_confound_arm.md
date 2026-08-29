# B 臂：Experience + CapsuleFeedback

## 目的

现有 Part 1 和 Part 2 同时改变了 Memory 与失败反馈格式：

| 条件 | Memory | 失败反馈 |
| --- | --- | --- |
| Part 1 `baseline` | `ExperienceProcessor` | Ax 原生反馈 |
| Part 2 `capsule` | `MemorylessProcessor` | `CapsuleFeedback` |
| **B `capsule_experience`** | **`ExperienceProcessor`** | **`CapsuleFeedback`** |

B 固定 Memory 为 Part 1 的 `ExperienceProcessor`，只把失败反馈替换成
`CapsuleFeedback`。因此可以分别观察：

- `capsule_experience - baseline`：反馈格式变化的影响；
- `capsule_experience - capsule`：Memory 策略变化的影响。

B 不是新的首轮候选生成实验。它逐题复用 Part 1 的完整首轮
`code`、`reasoning`、`imports` 和 `opens`，并使用与现有 Part 2 相同的
模型、endpoint、预算和候选安全策略。

## 运行

下面命令只运行 B；`--limit` 可用于先做单题 smoke。正式运行应使用独立的输出、状态和
metrics 路径，避免覆盖已有 Part 1/2/3 结果：

```powershell
$env:CAPSULE_FIRST_ROUND_CACHE = (Resolve-Path ".\results\work\part3-after-main-20260829\part2-first-round.json")
$env:CAPSULE_FEEDBACK_STATE_DIR = (Join-Path $PWD "results\work\part2-experience-capsule-20260829\state")
$env:CAPSULE_FEEDBACK_METRICS = (Join-Path $PWD "results\work\part2-experience-capsule-20260829\metrics.jsonl")

python .\baseline\run_part2.py `
  --baseline .\results\handoff\part12-live-20260828-corrected\baseline-full.jsonl `
  --folder "C:\path\to\FATE-M-v4.28.0" `
  --config .\configs\axprover_experience_capsule.yaml `
  --memory-class ExperienceProcessor `
  --out .\results\work\part2-experience-capsule-20260829\capsule-experience.jsonl
```

程序会把记录标记为：

- `condition=capsule_experience`；
- `feedback_mode=capsule`；
- `memory_mode=experience_capsule_feedback`；
- `memory_processor=ExperienceProcessor`。

`ExperienceProcessor` 的 LLM 调用记录在 `calls.memory_calls`、顶层
`memory_llm_calls` 和 `call_count` 中，并计入 `usage`。首轮成功题可能没有 memory 调用；这
是正常的，因为 Memory 只在需要重试时处理上一次尝试。

## 验收

```powershell
python .\scripts\validate_part2_pairing.py `
  --baseline .\results\handoff\part12-live-20260828-corrected\baseline-full.jsonl `
  --capsule .\results\work\part2-experience-capsule-20260829\capsule-experience.jsonl `
  --capsule-condition capsule_experience `
  --out .\results\work\part2-experience-capsule-20260829\pairing.json
```

该门禁仍要求任务身份、完整首轮候选、Ax commit、`yxai` Responses 配置、预算和候选安全策略
与 baseline 一致；它只放宽原 Part 2 对 `memory_calls == 0` 的要求，并要求 B 的
Memory/feedback 标记正确。运行过程不需要重新下载已经存在的 Lean、Ax 或 Python 依赖。

## 本次正式运行结果

2026-08-29 已在合并后的 `leiteng` 工作区完成一次完整 B 运行。运行使用已有的 WSL
Lean 4.28、FATE-M `.lake` 缓存、Ax 和 Python 虚拟环境，没有重新下载依赖，也没有启动
第二个 runner。Lean 工作副本为 `/opt/fatem-b-20260829`，从干净的 Git 提交创建，避免
把之前运行留下的证明修改带入本批次。

| 指标 | B `capsule_experience` |
| --- | ---: |
| 任务数 | 25 |
| 最终通过 | 20/25 (80.0%) |
| 总轮次 | 47 |
| LLM 请求 | 69 |
| 其中 `proposer` / `reviewer` / `ExperienceProcessor` | 22 / 20 / 27 |
| Lean 编译调用 | 47 |
| 总 token | 659,791 |
| 编译错误 | 27 |
| 编译超时 | 0 |
| 达到 4 轮上限 | 5 |

B 的 16 个任务首轮通过；与 Part 1 共享的 9 个首轮失败任务中，B 修复了 4 个
（`fate04`、`fate17`、`fate18`、`fate24`），修复率为 4/9（44.4%）。
`fate10`、`fate16`、`fate19`、`fate23` 和 `fate25` 在 4 轮后仍未通过。

逐题结果保存在
`results/work/part2-experience-capsule-20260829/capsule-experience.jsonl`，遥测在同目录
的 `metrics.jsonl`，配对门禁输出在 `pairing.json`。结果 JSONL 恰好包含 25 个唯一任务，
77 条遥测事件，所有行均为 `capsule_experience`、`ExperienceProcessor` 和
`experience_capsule_feedback`；`memory_llm_calls` 与逐行 `calls.memory_calls` 一致，
API 错误为 0。`validate_part2_pairing.py` 已通过，并确认 25/25 对的首轮
`code`、`reasoning`、`imports`、`opens` 完全一致。

配置中的模型字段 `openai:gpt-5.6-sol` 是 Ax 的模型命名空间；本次实际请求 endpoint
是 `https://yxai.chat/v1`，使用 Responses API、`store=false` 和 `high` reasoning，不能
把该字段前缀误解为切换回 OpenAI provider。

上述是单模型、单批次的 B 结果，只用于和已有 Part 1/Part 2 结果做描述性比较，不足以
支持统计显著性或因果结论。完整 ABCD 实验本次按要求没有运行。
