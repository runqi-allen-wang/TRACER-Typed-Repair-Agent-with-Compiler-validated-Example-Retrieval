# Part 2：CapsuleFeedback 制作与接入方案

当前实现与验证结果见 [`part2_阶段性完成报告.md`](part2_阶段性完成报告.md)；拆分 Memory/反馈混杂因素的 B 臂结果见 [`part2_capsule_feedback_confound_arm.md`](part2_capsule_feedback_confound_arm.md)。

## 目标与冻结约束

Part 2 把 AxProverBase 已经产生的 Builder 结果转换成下一轮 Proposer 可直接消费的紧凑反馈。它不运行 Lean、不调用模型，也不替代 Reviewer。

- AxProverBase 固定 commit：`06dfadc9ab439755af5efcfe0add95bfef2733c7`。
- Part 1/2/3 涉及 AxProverBase 的模型调用统一使用 AI4Math `yxai` 中转站：Ax/LangChain 模型名 `openai:gpt-5.6-sol`，模型 ID `gpt-5.6-sol`，`base_url=https://yxai.chat/v1`，wire API 为 `responses`。
- 响应存储关闭（`store=false`），推理强度固定为 `high`；Codex CLI 的 `personality=pragmatic` 不属于 Ax/LangChain API 参数，不向模型请求透传。
- Experience baseline 的 Proposer、Memory、Reviewer 必须共享上述模型配置；最终 summary 关闭。
- CapsuleFeedback 条件仅 Proposer、Reviewer 使用该模型；CapsuleFeedback 本身是确定性代码，LLM 调用数为 0。

## 数据流

```text
Ax Builder: check_lean_file(...) -> (build_success, message)
                                |
                                v
CapsuleFeedback.observe_ax((build_success, message))
                                |
                                +-- category
                                +-- stable feedback_text
                                +-- repeat / consecutive repeat count
                                +-- diagnostic drift
                                +-- bounded recent history
                                v
Ax BuildFailedFeedback(error_output=result["prompt_feedback"])
                                |
                                v
next Proposer
```

输入是 Ax 已有的 `(bool, str)` 编译结果，或含 `compile_ok`、`diagnostics/error_output`、`returncode`、`timed_out`、`goal_state` 的 JSON object。输出不保留原始完整日志，只保留脱敏、规范化且有长度上限的摘要。

## 分步实现

1. **核心接口（已实现）**：`leancapsule.feedback.CapsuleFeedback` 负责规范化诊断文本、重复次数、漂移和历史；支持状态 JSON 往返。
2. **命令行边界（已实现）**：`python -m leancapsule feedback` 从 JSON 读取已有编译结果，并可原子更新逐题 state 文件。
3. **Ax 接线（已实现）**：`leancapsule.ax_integration` 包裹固定 commit 的原 `_builder_node`，转换其返回的 `BuildFailedFeedback`/`SorriesGoalStateFeedback`，不再次调用 `check_lean_file`；每个 theorem 使用独立且有界的 session。
4. **配对门禁（已实现并完成正式运行）**：`scripts/validate_part2_pairing.py` 严格检查两组题目身份、Ax commit、完整首轮 Proposal（code/reasoning/imports/opens）、模型、endpoint、Responses wire API、响应存储、推理强度、预算和题集一致；原 Part 2 Capsule 还要求 Memory/额外编译/额外 LLM 调用为零，B 臂则显式允许并记录 `ExperienceProcessor` 的 Memory 调用。FATE-M 25 题修正版正式结果与配对报告位于 `results/handoff/part12-live-20260828-corrected/`，B 臂结果位于 `results/handoff/part2-experience-capsule-20260829/`。
5. **正式 Part 3 准备（已实现）**：JSONL 遥测包含 feedback_text、repeat count、drift kind、feedback chars、Builder/CapsuleFeedback 耗时、固定模型、Proposer/Reviewer 的真实 `LLMClient.ainvoke` 次数、token、tool calls 和零额外调用声明。provider 未返回价格时成本保持 `null`。
6. **D 类候选安全门禁（已实现）**：缓存和后续 LLM 的完整 theorem 都在 Builder 前检查 `unsafe`、占位符、额外声明、目标名和声明头；Builder 入口再次校验。配对门禁要求 Part 1/Part 2 都记录 `tracer-candidate-v2`。

## Python 接口

```python
from leancapsule.feedback import CapsuleFeedback

capsule = CapsuleFeedback(history_limit=4, max_feedback_chars=1600)

# 直接复用 Ax Builder 的返回值；此处不会再次编译。
build_success, message = await check_lean_file(...)
result = capsule.observe_ax((build_success, message), round_no=iteration)

if not build_success:
    feedback = BuildFailedFeedback(error_output=result["prompt_feedback"])
```

如 Ax 运行器为每轮单独启动进程，可保存并恢复状态：

```python
state = capsule.export_state()
capsule = CapsuleFeedback.from_state(state)
```

## JSON CLI

输入示例：

```json
{
  "compile_ok": false,
  "returncode": 1,
  "diagnostics": "FATEM/1.lean:12:7: error: application type mismatch",
  "round": 1
}
```

运行：

```powershell
python -m leancapsule feedback `
  --input .\compile-result.json `
  --state .\results\capsule-feedback\fate01.json
```

## 运行真实 AxProverBase Part 2

安装固定版本（不会把 Ax 变成仓库的普通测试依赖）：

```powershell
python -m pip install -r .\requirements-axprover-part2.txt
```

首轮缓存由 Part 1 的逐题 JSONL 生成：

```powershell
python .\scripts\prepare_part2_first_round_cache.py `
    --baseline .\runs\baseline.jsonl `
    --out .\results\part2-first-round.json
```

安全设置 `yxai` Key，并指定逐题状态、遥测目录和配对结果输出。正式运行必须使用全新的路径；如果指定路径中已有上一轮工件，runner 会在任何 Lean/API 调用前拒绝。确认要完整重跑时可传 `--overwrite`，它会清空主输出、telemetry 和专用 state 目录中格式明确的 Capsule 状态文件；state 目录包含其他文件时仍会拒绝删除：

```powershell
$secureKey = Read-Host "请输入 yxai API Key（输入不会显示）" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
$env:CAPSULE_FEEDBACK_STATE_DIR = (Join-Path $PWD "results\part2-state")
$env:CAPSULE_FEEDBACK_METRICS = (Join-Path $PWD "results\part2-metrics.jsonl")
$env:CAPSULE_FIRST_ROUND_CACHE = (Join-Path $PWD "results\part2-first-round.json")
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

设置 `CAPSULE_FIRST_ROUND_CACHE` 后，第一轮会直接构造 Ax `ProposalMessage`，不会调用 Proposer LLM；如果当前 theorem 没有精确缓存项，运行会立即失败。缓存会原样保留并逐字段校验 `code`、`reasoning`、`imports` 和 `opens`，包括合法的空 reasoning，避免两组首轮上下文失配。`code` 必须是 Ax 所需的完整更新后 theorem，而不只是 `by ...` proof body。

`baseline/run_part2.py` 在任何 Lean 或 API 调用前检查全部 task ID、target/module/theorem、完整首轮 Proposal、缓存和旧实验工件的一致性，然后保留完整 Ax 状态并输出配对门禁所需的逐题 JSONL。冒烟测试可附加 `--limit 1`；正式实验不要加该参数。

该 runner 会安装 CapsuleFeedback 接入，并在构造 Agent 前再次强制校验 `gpt-5.6-sol`、Responses API、`store=false`、`reasoning.effort=high` 和关闭 summary，避免其他配置意外覆盖实验条件。默认 Part 2 使用 Memoryless；B 臂通过 `--memory-class ExperienceProcessor` 显式选择 Experience，并将 Memory 的真实调用计入预算与遥测。配置还把实验输入预算显式固定为 `max_input_tokens=65536`，避免自定义模型别名没有 LangChain profile 时得到空值；该数字是实验预算，不宣称中转站模型的官方上下文上限。`python -m leancapsule.ax_runner` 仍可用于交互式单题调试，但它的上游 `-o` 只包含 `success/error/summary`，不能代替正式配对 JSONL。

配对 smoke 完成后执行：

```powershell
python .\scripts\validate_part2_pairing.py `
    --baseline .\runs\baseline.jsonl `
    --capsule .\runs\capsule.jsonl `
    --out .\runs\part2-pairing-report.json
```

B 臂的独立配置、输出目录和验收命令见
[`part2_capsule_feedback_confound_arm.md`](part2_capsule_feedback_confound_arm.md)。

## 验收标准

- 对相同错误的不同临时路径、行列号和 metavariable 编号生成相同规范化诊断文本。
- 连续相同错误增加 repeat count；类别或规范化诊断文本变化标记 drift。
- history 和 prompt 长度严格有界，疑似 Bearer/API key 不出现在输出或 state。
- 单元测试证明核心和 CLI 不调用 Lean 或任何模型。
- Ax 接线后的 trace 中，每轮至多执行原 Builder 自带的一次 `check_lean_file`；CapsuleFeedback 增加的编译次数恒为 0，处理耗时单独记录。
- `feedback_counts`、history、prompt 和驻留 theorem session 均有上限；未知状态 schema 会被拒绝。
- 固定 Ax commit 的源码契约和真实 Python 消息类型在 Ubuntu workflow 中独立验证。
- D01 `unsafe inductive` 构造 `False` 在共享缓存、后续 ProposalMessage 和 Builder 三个入口均于 Lean 编译前拒绝。

## GitHub Actions 验证

`.github/workflows/part2.yml` 是 Part 2 的独立验证入口，不读取 API Key，也不调用 `yxai`：

- 推送 Part 2 相关文件到 `main` 时自动触发；
- Pull Request 修改 Part 2 相关文件时自动触发；
- workflow 进入默认分支后可从 Actions 页面手动触发；
- Ubuntu 执行 CapsuleFeedback、文档和 workflow 契约测试；
- 专项测试通过后，Ubuntu 执行 `lake build` 和完整 Python 回归。

GitHub 只为默认分支上的 `workflow_dispatch` 显示手动运行入口；合并前可通过 Pull Request 触发，合并后也可在 Actions 页面手动运行。

## 当前合并版的状态格式

诊断状态使用 `capsule-feedback.readable.v0.2`，Ax 遥测使用 `ax-capsule-feedback.readable.v0.3`。重复检测以脱敏后的完整规范化诊断文本为键；文件名为随机 `session-<UUID>.json`，文件内保留完整 theorem key，重新载入时严格匹配。旧状态格式拒绝载入，请使用新的空状态目录；历史实验不改写为新格式。首轮配对直接比较 code、reasoning、imports 和 opens，不使用派生摘要。
