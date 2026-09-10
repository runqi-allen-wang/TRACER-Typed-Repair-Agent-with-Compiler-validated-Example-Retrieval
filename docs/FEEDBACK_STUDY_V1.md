# Feedback Study v1：三种编译反馈表示对照

该子研究在同一修复条件下只改变编译反馈表示，不复用 R-A～R-F 的名称，也不回写旧轨迹。

## 冻结对照

三组为：

1. `raw`：仅脱敏后的原始 Lean 诊断；
2. `normalized`：规范位置、空白和易变元变量后的诊断；
3. `structured`：类别与结构化信号，每项保留原始证据片段。

题目、模型、温度、输出上限、最多轮数、编译时限和随机任务顺序保持一致。默认示例计划为 repair24、一个模型、三次重复，共 216 个任务，最多 648 次生成。配置只是实验设计，不是结果。

## 离线预览

```powershell
python src/feedback_study.py plan
```

该命令不访问网络。冻结协议位于 `experiments/feedback_study.protocol.json`，示例配置位于 `experiments/feedback_study.example.json`。

## 正式运行入口

可直接在 CLI 中指定 DeepSeek 端点和模型，无需改动 JSON。API key 只在本地隐藏输入，不回显、不写入配置、不保存到轨迹。下例显式取消本地美元门禁，但仍固定为 216 个任务、最多 648 次请求：

```powershell
$out = "results/feedback-study-deepseek-" + (Get-Date -Format "yyyyMMdd-HHmmss")

python src/feedback_study.py run `
  --api-url "https://api.deepseek.com/chat/completions" `
  --model "deepseek-v4-pro" `
  --temperature 0 `
  --max-tokens 12000 `
  --thinking enabled `
  --reasoning-effort high `
  --api-key-prompt `
  --show-key-confirmation `
  --no-cost-limit `
  --out $out
```

`--show-key-confirmation` 只在终端显示密钥长度和末四位，不显示完整值，不写入轨迹。`--no-cost-limit` 表示本地不根据美元预估停止，不代表供应商免费或账户无限额。若需要保守的本地费用门禁，可改用 `--max-reserved-usd` 并在配置中填写当日价格。模型名必须以你账户实际可用的 DeepSeek 模型为准。上例显式冻结 DeepSeek 思考模式和推理强度；在该模式下 `temperature` 作为披露字段保留，但供应商可能忽略它。

原有配置文件入口仍保留。先复制示例配置并填写真实模型名、当日价格和独立输出目录。不要把 API key 写入 JSON。

```powershell
python src/feedback_study.py run `
  --config experiments/feedback_study.local.json `
  --benchmark benchmarks/repair24/manifest.json `
  --out results/feedback-study-001 `
  --api-key-prompt `
  --max-calls 648 `
  --max-reserved-usd 10
```

费用参数是本地保守预留，不是供应商账单硬上限。任何新运行都需要用户另行确认模型、任务规模和费用；仓库实现与 CI 本身不会调用 API。

完成成功证明的逐项 AI 辅助复核后运行。新批次的复核表为 `ai_assisted_review.csv`；旧批次的 `manual_review.csv` 仅作兼容读取：

```powershell
python src/feedback_study.py report --run results/feedback-study-001
```

### 网络中断后续跑

如果任务因 `IncompleteRead`、连接重置或 provider 5xx 等基础设施错误停止，不要从头消费已完成任务。使用与原批次完全相同的模型参数和输出目录，额外加入 `--resume`。运行器会：

- 跳过已完成任务；
- 将原始失败工件移入 `retry_history/`，不删除或伪装为未发生；
- 从 `budget.json` 恢复已尝试请求数；
- 仅重跑失败任务并继续冻结顺序。

```powershell
python src/feedback_study.py run `
  --resume `
  --api-url "https://api.deepseek.com/chat/completions" `
  --model "deepseek-v4-pro" `
  --temperature 0 `
  --max-tokens 12000 `
  --thinking enabled `
  --reasoning-effort high `
  --api-key-prompt `
  --show-key-confirmation `
  --auto-resume-network 20 `
  --no-cost-limit `
  --out $run
```

`--auto-resume-network 20` 会在同一进程内对连接重置、响应截断、超时和 provider 500/502/503/504 最多自动续跑 20 次，因此密钥只需输入一次。每次失败仍先写入当前任务目录，并在下一次续跑时归档；HTTP 4xx、Lean 编译失败、安全门禁失败和普通证明 `FAIL` 不会被自动重试。默认值为 0，以保留严格的遇错停止行为。

报告中的 `archived_transport_retry_attempts` 单独披露已保留的网络失败尝试数。

## 当前已发布批次

[发布包](../published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248)对应批次 `feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248`，已完成 216/216 个任务。raw、normalized、structured 的首轮通过数分别为 56、56、60，三轮预算内通过数分别为 67、65、67；总计记录 1,538,045 tokens。199 个成功证明通过独立 Lean 复编译和显式标注的 AI 辅助复核，当前没有残留基础设施错误。

公开包包含 283 条当前有效逐轮记录；预算账本的 286 次调用预留还包括 2 条归档传输失败轮次和 1 次没有对应轮次记录的预留。逐请求完整 prompt、供应商响应 ID、认证字段、本机路径及失败归档原文不公开；静态模板、反馈、候选、诊断和计数仍可审计。价格未冻结，因此不报告美元成本。这里的比较只适用于一个模型、24 道题和三次重复；不得把 216 行当作 216 道独立题，也不得声称统计显著、因果增益或跨模型泛化。

正式门禁检查完整矩阵、连续轮次、禁用缓存、统一 provider 配置、成功证明独立复编译和 AI 辅助复核。报告显式写入 `review_mode=ai_assisted`、`review_complete` 与 `ai_assisted_review_complete`，不得把它描述为纯人工复核。报告按模型与表示给出 pass@1、有界成功数、轮数、时间、token、费用、相关改动率和重复错误类别率。

## 脱敏导出与发布审计

本地报告门禁通过后，用专用导出器创建一个此前不存在的发布目录：

```powershell
python scripts/export_feedback_study.py `
  --run results/feedback-study-001 `
  --out published/feedback-study-001
```

导出器不会复制逐请求完整 prompt、供应商响应 ID、认证字段或 `retry_history` 原文。随后先执行静态审计，再独立编译全部公开证明：

```powershell
python scripts/audit_feedback_study.py published/feedback-study-001
python scripts/audit_feedback_study.py published/feedback-study-001 --compile-solutions
```

公开 `MANIFEST.json` 使用相对路径和字节数核对文件集合；不产生派生摘要。目录已存在、任务数不完整、复核模式不符、清单漂移、绝对路径或疑似认证值都会使导出或审计失败。

## 结论边界

runner、冻结计划和 mock 端到端测试属于可复验实现。只有完整真实轨迹、成功证明和明确复核模式都通过时，本地 `release_ready` 才能为 `true`；该字段不替代脱敏发布审计。README 必须区分本地结果与已发布证据，不得把当前描述性差异写成性能定论。
