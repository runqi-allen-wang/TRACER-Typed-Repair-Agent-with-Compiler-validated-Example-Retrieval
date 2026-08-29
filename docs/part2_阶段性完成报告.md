# Part 2 CapsuleFeedback 完成报告

## 1. 报告结论

Part 2 的代码实现与验证基础设施已经完成。当前版本能够把 AxProverBase 已有的 Builder 结果转换为确定性的紧凑反馈，并将其作为真实 Ax `BuildFailedFeedback` 交给下一轮 Proposer；整个转换过程不会额外运行 Lean，也不会调用 LLM。

本阶段还完成了逐 theorem 状态隔离、状态大小控制、AI4Math `yxai`/`gpt-5.6-sol`/Memoryless 配置冻结、共享首轮候选注入、配对实验门禁、调用与 token 遥测，以及固定 AxProverBase commit 的真实类型验证。

FATE-M 25 题真实配对实验已经完成：Part 1 与 Part 2 均为 25/25 成功，严格配对门禁 25/25 通过。修正版总轮次由 39 降至 36，编译错误由 14 降至 11，LLM calls 由 79 降至 36，tokens 由 656657 降至 274742；正式交接包位于 `results/handoff/part12-live-20260828-corrected/`。

为拆开 Memory 与反馈格式的混杂因素，随后增加了独立 B 臂
`ExperienceProcessor + CapsuleFeedback`。B 在同一 25 题、同一首轮候选下通过 20/25，
共享首轮失败中修复 4/9；完整统计和交接证据见
[`part2_capsule_feedback_confound_arm.md`](part2_capsule_feedback_confound_arm.md)及
`results/handoff/part2-experience-capsule-20260829/`。B 是补充拆分臂，不改写上述
Part 1/Part 2 历史结果，也不是 ABCD 的第四个条件。

## 2. 冻结实验条件

| 项目 | 固定值 |
|---|---|
| AxProverBase commit | `06dfadc9ab439755af5efcfe0add95bfef2733c7` |
| Ax/LangChain 模型名 | `openai:gpt-5.6-sol` |
| Provider endpoint | `https://yxai.chat/v1` |
| Wire API | `responses` |
| 推理强度 | `high` |
| 响应存储 | 关闭（`store=false`） |
| 显式输入窗口 | `65536` tokens |
| Part 1 Memory | `ExperienceProcessor` |
| Part 2 Memory | `MemorylessProcessor` |
| B Memory | `ExperienceProcessor` |
| B 失败反馈 | `CapsuleFeedback` |
| 最终 LLM summary | 关闭 |
| CapsuleFeedback 编译调用 | `0` |
| CapsuleFeedback LLM 调用 | `0` |

共享模型配置位于 `configs/axprover_yxai_gpt56_sol.yaml`；Part 1 和 Part 2 分别通过 `configs/axprover_part1_experience.yaml` 与 `configs/axprover_part2_capsule.yaml` 固定 Memory 条件。Codex CLI 的 `personality=pragmatic` 不属于 Ax/LangChain API 参数，因此不向模型请求透传。

## 3. 已解决问题

### 3.1 状态可能无限增长

原实现虽然限制了 prompt 和 history，但 `feedback_counts` 会随新错误规范化诊断文本持续增长。

现已完成：

- 使用有界 LRU 规范化诊断文本计数表，默认最多保存 64 个规范化诊断文本；
- 允许通过 `feedback_limit` 调整，上限为 1000；
- 导出状态、历史、摘要和 prompt 均有明确上限；
- 驻留的 theorem session 默认最多 128 个；
- CLI 增加 `--feedback-limit` 参数。

使用 100 个不同错误的回归测试验证后，导出状态中的规范化诊断文本数不会超过配置上限。

### 3.2 状态版本和输入边界不严格

现已完成：

- 状态中出现未知 `schema_version` 时立即拒绝恢复；
- 正确解析字符串形式的 `true/false`，避免 `bool("false")` 被当成成功；
- 扩充 Bearer、`sk-`、`key-`、`api_key`、`access_token` 和 `authorization` 的脱敏；
- 状态恢复时重新约束历史字段、计数和字符串长度。

### 3.3 缺少真实 Ax 消息桥接

新增 `leancapsule.ax_integration`：

- 在 Ax 构造 Agent 前包裹固定版本的 `ProverAgent`；
- 调用原始 `_builder_node`，不复制或替代 Builder；
- 消费原 Builder 返回的 `BuildFailedFeedback` 或 `SorriesGoalStateFeedback`；
- 使用 CapsuleFeedback 生成紧凑反馈；
- 将结果重新封装为真实 Ax `BuildFailedFeedback`；
- 保留原 Builder 返回的 metrics 和其他字段。

因此每次 Builder 执行至多保留 Ax 原有的一次 `check_lean_file` 调用，CapsuleFeedback 增加的编译次数恒为 0。

### 3.4 不同 theorem 的历史可能互相污染

新增 `CapsuleFeedbackSessions`：

- 使用 Ax 的 `module_path:theorem_name` 作为精确 session key；
- 每个 theorem 拥有独立规范化诊断文本、重复次数和历史；
- session 池使用 LRU 上限；
- 可通过 `CAPSULE_FEEDBACK_STATE_DIR` 按 theorem 哈希文件持久化；
- 状态写入采用临时文件替换，避免半写入文件。

测试证明相同错误分别出现在 theorem A 和 B 时，两者的首次 `repeat_count` 都为 1。

### 3.5 原 Part 2 Capsule 条件的 Memory 约束

原 Part 2 Capsule runner 会在 Agent 初始化前强制：

- `memory_config.class_name = MemorylessProcessor`；
- `memory_config.init_args = {}`；
- `summarize_output.enabled = false`；
- Proposer/Reviewer 模型统一为 `gpt-5.6-sol`；
- endpoint 固定为 `yxai` Responses API，推理强度为 `high`，响应存储关闭；
- endpoint 和模型 profile 使用冻结值。

即使外部配置尝试覆盖上述字段，初始化前仍会再次执行约束。

B 臂有意不使用这条 `MemorylessProcessor` 约束：它通过
`configs/axprover_experience_capsule.yaml` 选择 `ExperienceProcessor`，并让 Memory
复用与 Proposer/Reviewer 相同的冻结 `yxai` 配置。B 的 Memory 请求因此计入逐题
`memory_llm_calls`、`calls.memory_calls`、`call_count` 和 `usage`；这正是拆分
Memory 因素所需要的行为。原 Part 2 的 `memory_calls == 0` 门禁不适用于 B。

### 3.6 缺少共享首轮候选

新增首轮候选准备与注入流程：

1. `scripts/prepare_part2_first_round_cache.py` 从 Part 1 metrics 读取完整首轮 theorem；
2. 按 Ax 精确目标 `module_path:theorem_name` 生成缓存；
3. `CAPSULE_FIRST_ROUND_CACHE` 指向该缓存；
4. Part 2 第一轮直接构造真实 Ax `ProposalMessage`；
5. 第一轮不调用 Proposer LLM；
6. 如果缓存没有当前 theorem，运行立即失败，不会退回重新生成。

准备脚本还会拒绝空候选、只有 `by ...` 的 proof body、非法 imports/opens，以及同一目标的冲突候选。

### 3.7 缺少配对实验门禁

新增 `scripts/validate_part2_pairing.py`，逐题检查：

- baseline 与 Capsule 题集完全一致；
- 首轮候选逐字符相同；
- 通过任务标识与原始首轮候选逐项比对；
- 两组模型均为 `openai:gpt-5.6-sol`；
- endpoint 相同且为冻结 endpoint；
- wire API 均为 Responses、响应存储均关闭、推理强度均为 `high`；
- 总预算字段相同；
- 原 Part 2 Capsule 的 `memory_calls == 0`（B 臂允许并记录 ExperienceProcessor 的 Memory 调用）；
- CapsuleFeedback 的额外 LLM/编译调用均为 0。

任何一项不满足时，脚本退出码为 1，结果不能进入正式 Part 3 分析。

### 3.8 缺少真实调用和成本相关遥测

Part 2/B runner 直接包裹实际 `LLMClient.ainvoke`，不再用节点次数冒充模型调用次数。JSONL 遥测现在包含：

- Proposer LLM 请求次数；
- Reviewer LLM 请求次数；
- Memory LLM 请求次数；
- tool calls；
- input/output/total tokens；
- feedback_text、重复次数和连续重复次数；
- drift kind；
- 反馈字符数；
- Builder 总耗时；
- CapsuleFeedback 单独处理耗时；
- 共享首轮候选哈希；
- 固定 Ax commit、模型和 endpoint；
- CapsuleFeedback 零额外编译/LLM 调用声明。

如果 provider 没有返回价格，`estimated_cost_usd` 保持 `null`，不会错误显示为 0。

### 3.9 缺少固定 Ax 版本的真实验证

新增三层验证：

1. `scripts/validate_axprover_contract.py` 检查准确 git commit、Builder 中的 `check_lean_file` 调用点和所需类型；
2. `scripts/smoke_axprover_integration.py` 使用安装后的真实 Ax 类测试配置、消息和补丁入口；
3. `.github/workflows/part2.yml` 在独立 Ubuntu job 中拉取固定 commit、安装 Ax 并执行 smoke。

本地隔离环境已经验证：

- 仓库 YAML 能被固定 Ax 版本解析；
- 真实 `BuildFailedFeedback` 能被 CapsuleFeedback 消费；
- 真实 `LLMClient` 接受 `yxai` Responses endpoint、隐私参数、推理参数和显式 profile；
- 补丁能够安装到真实 `ProverAgent`；
- `python -m leancapsule.ax_runner --help` 正常启动。

上述 smoke 不调用 API，也不运行 Lean。

### 3.10 完整 theorem 候选可能通过 unsafe 或结构修改绕过可信性

新增 D 类编译前安全门禁并接入 AxProverBase：

- 共享首轮缓存和后续 LLM `ProposalMessage` 在进入 Builder 前统一检查；
- Builder 入口再次执行同一检查，形成纵深防御；
- 拒绝 `unsafe`、元编程执行入口、`sorry`/`sorryAx`/`admit`、额外顶层声明和命令注入；
- 要求目标名称、声明种类和规范化声明头与原 theorem 完全一致；
- imports/opens 只接受合法的 Lean 限定名，不能通过换行注入命令；
- 拒绝事件仅记录随机事件编号、候选长度、阶段和原因，不把恶意源码写入遥测；
- Part 1/Part 2 配对门禁要求两组逐题使用同一 `tracer-candidate-v2` 策略。

D01 的 `unsafe inductive` 构造 `False` 源码已由 Lean 直接验证为可接受，同时自动测试证明其在缓存、生成和 Builder 三个 Ax 入口均于编译前被拒绝。

## 4. 当前数据流

```text
Part 1 metrics
      |
      v
prepare_part2_first_round_cache.py
      |
      v
精确 target -> 完整首轮 theorem 缓存
      |
      v
Ax Proposer 第一轮直接使用缓存 ProposalMessage
      |
      v
完整 theorem D 类安全门禁
      |
      v
Ax 原 Builder -> 原有 check_lean_file（至多一次）
      |
      v
CapsuleFeedback.observe_ax（0 次额外编译，0 次 LLM）
      |
      +-- category / feedback_text
      +-- repeat / consecutive repeat
      +-- diagnostic drift
      +-- bounded history
      +-- telemetry
      |
      v
真实 Ax BuildFailedFeedback
      |
      v
下一轮 Proposer
```

## 5. 主要文件

| 文件 | 用途 |
|---|---|
| `src/leancapsule/feedback.py` | 有界 CapsuleFeedback 核心、规范化诊断文本、漂移、脱敏和状态 |
| `src/leancapsule/ax_integration.py` | 真实 Ax 消息桥接、session、首轮候选和遥测 |
| `src/leancapsule/ax_runner.py` | 安装集成后启动 Ax CLI |
| `src/leancapsule/pairing.py` | 严格配对结果校验 |
| `configs/axprover_yxai_gpt56_sol.yaml` | Part 1/2/3 共享模型条件 |
| `configs/axprover_part1_experience.yaml` | Part 1 Experience 配置 |
| `configs/axprover_part2_capsule.yaml` | Part 2 Memoryless 配置 |
| `configs/axprover_experience_capsule.yaml` | B 臂 Experience + CapsuleFeedback 配置 |
| `docs/part2_capsule_feedback_confound_arm.md` | B 臂设计、运行命令与结果 |
| `requirements-axprover-part2.txt` | 固定 AxProverBase commit |
| `scripts/prepare_part2_first_round_cache.py` | 生成首轮候选缓存 |
| `scripts/validate_part2_pairing.py` | 配对实验门禁 |
| `scripts/validate_axprover_contract.py` | 固定 Ax 源码契约检查 |
| `scripts/smoke_axprover_integration.py` | 真实 Ax 类型 smoke |
| `.github/workflows/part2.yml` | Ubuntu-only Part 2 CI |

## 6. 测试和验证结果

| 验证项 | 结果 |
|---|---|
| 完整 Python 回归 | `122/124` 通过，2 项 Windows 平台跳过 |
| `lake build` | 通过 |
| Evaluation18 | 只有已有 `sorry` 警告 |
| Capsule 有界状态 | 通过 |
| theorem 状态隔离 | 通过 |
| Ax 消息桥接 | 通过 |
| 共享首轮候选注入 | 通过 |
| 缓存缺失 fail-closed | 通过 |
| `yxai` Responses/Memoryless/summary 契约 | 通过 |
| 真实 `yxai` 直接 Agent → Lean smoke | 通过（输入 4511、输出 20、总计 4531 tokens） |
| 真实 `yxai` AxProverBase/LangChain smoke | 通过（输入 4391、输出 5、总计 4396 tokens） |
| LLM/token/tool 遥测 | 通过 |
| 固定 Ax 源码契约 | 通过 |
| 真实 Ax Python 类型 smoke | 通过 |
| D01 unsafe theorem 编译前拦截 | 通过 |
| Ax 缓存/生成/Builder 三层安全门禁 | 通过 |
| Part 1/Part 2 v2 安全策略配对 | 通过 |
| B 臂 FATE-M 25 题运行 | 20/25 成功；配对 25/25；0 API/编译超时 |
| Part 2 workflow 平台 | 仅 Ubuntu |
| `git diff --check` | 通过 |

`lake build` 的首次沙箱内执行仅因 elan 无法联网检查工具链而失败；在允许正常工具链访问的环境中重跑后构建成功。

## 7. 使用流程

安装固定 Ax：

```powershell
python -m pip install -r .\requirements-axprover-part2.txt
```

从 Part 1 metrics 准备首轮候选：

```powershell
python .\scripts\prepare_part2_first_round_cache.py `
    --baseline .\runs\baseline.jsonl `
    --out .\results\part2-first-round.json
```

安全设置 Key 并运行配对 Part 2（冒烟时可在命令末尾增加 `--limit 1`）：

```powershell
$secureKey = Read-Host "请输入 yxai API Key（输入不会显示）" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
$env:CAPSULE_FIRST_ROUND_CACHE = (Join-Path $PWD "results\part2-first-round.json")
$env:CAPSULE_FEEDBACK_STATE_DIR = (Join-Path $PWD "results\part2-state")
$env:CAPSULE_FEEDBACK_METRICS = (Join-Path $PWD "results\part2-metrics.jsonl")
try {
    python .\baseline\run_part2.py `
        --baseline .\runs\baseline.jsonl `
        --folder "C:\path\to\lean-project" `
        --config .\configs\axprover_part2_capsule.yaml `
        --out .\runs\capsule.jsonl
}
finally {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable secureKey -ErrorAction SilentlyContinue
}
```

两组结果完成后运行门禁：

```powershell
python .\scripts\validate_part2_pairing.py `
    --baseline .\runs\baseline.jsonl `
    --capsule .\runs\capsule.jsonl `
    --out .\runs\part2-pairing-report.json
```

B 臂将 `--memory-class` 改为 `ExperienceProcessor`，完整的隔离路径和验收命令见
[`B 臂设计与结果`](part2_capsule_feedback_confound_arm.md)。

## 8. 当前边界与后续工作

Part 1/2/B 实现与首批正式配对运行已经完成。复现实验时仍需满足以下条件：

- Part 1 使用 `configs/axprover_part1_experience.yaml` 并输出完整首轮 theorem；
- Part 2 使用 `configs/axprover_part2_capsule.yaml`；B 使用 `configs/axprover_experience_capsule.yaml`，两种结果都保留配对门禁要求的 provider、预算和 calls 字段；
- 真实 `yxai` 调用只通过进程环境配置 `OPENAI_API_KEY`，`auth.json` 不得进入仓库；
- 当前 Part 1/Part 2/B 数据是 25 题、单模型、单批次，不支持统计显著性、Memory/反馈因果结论或通用性能结论；完整 ABCD 和 Part 3 仍需要正式统计分析与更大规模重复实验。

## 当前合并版的状态格式

诊断状态使用 `capsule-feedback.readable.v0.2`，Ax 遥测使用 `ax-capsule-feedback.readable.v0.3`。重复检测以脱敏后的完整规范化诊断文本为键；文件名为随机 `session-<UUID>.json`，文件内保留完整 theorem key，重新载入时严格匹配。旧状态格式拒绝载入，请使用新的空状态目录；历史实验不改写为新格式。首轮配对直接比较 code、reasoning、imports 和 opens，不使用派生摘要。
