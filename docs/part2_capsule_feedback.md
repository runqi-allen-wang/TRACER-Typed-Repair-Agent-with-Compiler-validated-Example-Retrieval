# Part 2：CapsuleFeedback 制作与接入方案

当前实现与验证结果见 [`part2_阶段性完成报告.md`](part2_阶段性完成报告.md)。

## 目标与冻结约束

Part 2 把 AxProverBase 已经产生的 Builder 结果转换成下一轮 Proposer 可直接消费的紧凑反馈。它不运行 Lean、不调用模型，也不替代 Reviewer。

- AxProverBase 固定 commit：`06dfadc9ab439755af5efcfe0add95bfef2733c7`。
- Part 1/2/3 涉及 AxProverBase 的模型调用统一使用 DeepSeek Flash：Ax/LangChain 模型名 `openai:deepseek-v4-flash`，官方模型 ID `deepseek-v4-flash`，`base_url=https://api.deepseek.com`。
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
                                +-- stable fingerprint
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

1. **核心接口（已实现）**：`leancapsule.feedback.CapsuleFeedback` 负责指纹、重复次数、漂移和历史；支持状态 JSON 往返。
2. **命令行边界（已实现）**：`python -m leancapsule feedback` 从 JSON 读取已有编译结果，并可原子更新逐题 state 文件。
3. **Ax 接线（已实现）**：`leancapsule.ax_integration` 包裹固定 commit 的原 `_builder_node`，转换其返回的 `BuildFailedFeedback`/`SorriesGoalStateFeedback`，不再次调用 `check_lean_file`；每个 theorem 使用独立且有界的 session。
4. **配对 smoke 门禁（已实现）**：`scripts/validate_part2_pairing.py` 严格检查两组首轮候选、模型、endpoint、预算和题集一致，并要求 Capsule 的 Memory/额外编译/额外 LLM 调用为零。真实模型结果仍需在 Part 1 产出后运行该门禁。
5. **正式 Part 3 准备（已实现）**：JSONL 遥测包含 fingerprint、repeat count、drift kind、feedback chars、Builder/CapsuleFeedback 耗时、固定模型、Proposer/Reviewer 的真实 `LLMClient.ainvoke` 次数、token、tool calls 和零额外调用声明。provider 未返回价格时成本保持 `null`。

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

安全设置 DeepSeek Key，并指定逐题状态和遥测目录：

```powershell
$secureKey = Read-Host "请输入 DeepSeek API Key（输入不会显示）" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
$env:CAPSULE_FEEDBACK_STATE_DIR = (Join-Path $PWD "results\part2-state")
$env:CAPSULE_FEEDBACK_METRICS = (Join-Path $PWD "results\part2-metrics.jsonl")
$env:CAPSULE_FIRST_ROUND_CACHE = (Join-Path $PWD "results\part2-first-round.json")
try {
    python -m leancapsule.ax_runner prove "Module.Path:theorem_name" `
        --folder "C:\path\to\lean-project" `
        --skip-build
}
finally {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable secureKey -ErrorAction SilentlyContinue
}
```

首轮缓存由 Part 1 的 metrics 生成：

```powershell
python .\scripts\prepare_part2_first_round_cache.py `
    --baseline .\runs\baseline.jsonl `
    --out .\results\part2-first-round.json
```

设置 `CAPSULE_FIRST_ROUND_CACHE` 后，第一轮会直接构造 Ax `ProposalMessage`，不会调用 Proposer LLM；如果当前 theorem 没有精确缓存项，运行会立即失败，避免两组首轮候选失配。缓存值必须是 Ax 所需的完整更新后 theorem，而不只是 `by ...` proof body。

`ax_runner` 会自动追加 `configs/axprover_part2_capsule.yaml`，并在构造 Agent 前再次强制校验 DeepSeek Flash、Memoryless 和关闭 summary，避免其他配置意外覆盖实验条件。配置还显式提供 `max_input_tokens=65536`，防止固定 Ax 版本无法识别自定义 DeepSeek 模型名时得到空 profile。

配对 smoke 完成后执行：

```powershell
python .\scripts\validate_part2_pairing.py `
    --baseline .\runs\baseline.jsonl `
    --capsule .\runs\capsule.jsonl `
    --out .\runs\part2-pairing-report.json
```

## 验收标准

- 对相同错误的不同临时路径、行列号和 metavariable 编号生成相同指纹。
- 连续相同错误增加 repeat count；类别或指纹变化标记 drift。
- history 和 prompt 长度严格有界，疑似 Bearer/API key 不出现在输出或 state。
- 单元测试证明核心和 CLI 不调用 Lean 或任何模型。
- Ax 接线后的 trace 中，每轮至多执行原 Builder 自带的一次 `check_lean_file`；CapsuleFeedback 增加的编译次数恒为 0，处理耗时单独记录。
- `fingerprint_counts`、history、prompt 和驻留 theorem session 均有上限；未知状态 schema 会被拒绝。
- 固定 Ax commit 的源码契约和真实 Python 消息类型在 Ubuntu workflow 中独立验证。

## GitHub Actions 验证

`.github/workflows/part2.yml` 是 Part 2 的独立验证入口，不读取 API Key，也不调用 DeepSeek：

- 推送 Part 2 相关文件到 `leiteng` 时自动触发；
- Pull Request 修改 Part 2 相关文件时自动触发；
- workflow 进入默认分支后可从 Actions 页面手动触发；
- Ubuntu 执行 CapsuleFeedback、文档和 workflow 契约测试；
- 专项测试通过后，Ubuntu 执行 `lake build` 和完整 Python 回归。

由于 GitHub 只为默认分支上的 `workflow_dispatch` 显示手动运行入口，在该 workflow 尚未合并到默认分支时，应通过推送到 `leiteng` 或创建 Pull Request 触发。
