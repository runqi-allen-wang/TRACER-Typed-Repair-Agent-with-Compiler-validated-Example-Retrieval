# Part 2：CapsuleFeedback 制作与接入方案

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
3. **Ax 接线（待 Part 1 分支合并）**：在固定 commit 的 `_builder_node` 中，仅把现有 `(build_success, message)` 传入 `observe_ax`；禁止再次调用 `check_lean_file`。每个 theorem 创建独立 session。
4. **配对 smoke（待接线后）**：使用 Part 1 缓存的首轮候选，对同一题分别运行 Experience baseline 和 CapsuleFeedback，确认首轮输入相同、模型配置相同、Capsule 条件没有 Memory LLM 调用。
5. **正式 Part 3 准备**：日志增加 fingerprint、repeat count、drift kind、feedback chars 和 CapsuleFeedback 处理耗时，供配对分析。

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

## 验收标准

- 对相同错误的不同临时路径、行列号和 metavariable 编号生成相同指纹。
- 连续相同错误增加 repeat count；类别或指纹变化标记 drift。
- history 和 prompt 长度严格有界，疑似 Bearer/API key 不出现在输出或 state。
- 单元测试证明核心和 CLI 不调用 Lean 或任何模型。
- Ax 接线后的 trace 中，每轮只有原 Builder 的一次编译；CapsuleFeedback 处理耗时单独记录。

## GitHub Actions 验证

`.github/workflows/part2.yml` 是 Part 2 的独立验证入口，不读取 API Key，也不调用 DeepSeek：

- 推送 Part 2 相关文件到 `leiteng` 时自动触发；
- Pull Request 修改 Part 2 相关文件时自动触发；
- workflow 进入默认分支后可从 Actions 页面手动触发；
- Ubuntu 执行 CapsuleFeedback、文档和 workflow 契约测试；
- 专项测试通过后，Ubuntu 执行 `lake build` 和完整 Python 回归。

由于 GitHub 只为默认分支上的 `workflow_dispatch` 显示手动运行入口，在该 workflow 尚未合并到默认分支时，应通过推送到 `leiteng` 或创建 Pull Request 触发。
