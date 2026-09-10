# Feedback Study v1：第二模型复现

本流程复用已发布 DeepSeek 批次的 repair24 题库、raw/normalized/structured 三种反馈表示、三次重复、三轮修复预算、编译时限、任务顺序与静态提示模板。第二模型使用独立的模型标识、输出目录、API 密钥输入和公开发布包。

冻结协议位于 `experiments/feedback_replication.protocol.json`。当前文档与代码只提供可执行流程；在第二模型 216 个任务全部完成、成功证明复编译、AI 辅助复核和发布审计通过前，不得声称跨模型复现已经完成。

## 1. 运行前离线检查

```powershell
python src/feedback_study.py plan
python scripts/audit_feedback_study.py published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248
```

两条命令均不调用模型。基线审计必须通过，计划必须仍为 24 题 × 3 表示 × 3 重复，共 216 个任务。

## 2. 第二模型运行

以下模板适用于兼容 Chat Completions 的 HTTPS 服务。将端点、模型名和 `model-id` 改成实际值；`model-id` 只用于目录与报告，不能与基线的 `deepseek` 重复。API key 仅在隐藏输入中提供。

```powershell
$run = "results/feedback-study-second-model-" + (Get-Date -Format "yyyyMMdd-HHmmss")

python src/feedback_study.py run `
  --reference-release "published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248" `
  --model-id "second_model" `
  --api-url "https://REPLACE_WITH_TRUSTED_HOST/v1/chat/completions" `
  --model "REPLACE_WITH_ACTUAL_MODEL" `
  --temperature 0 `
  --max-tokens 12000 `
  --api-key-prompt `
  --auto-resume-network 20 `
  --no-cost-limit `
  --out $run
```

`--reference-release` 是硬门禁。它会在第一次付费请求前逐项核对题库全文、任务顺序、协议、提示模板、三种表示、重复数、轮数、编译时限、温度和最大输出 token；任何公共控制漂移都会停止。模型专属的思考模式或推理强度可以不同，但必须由 CLI 显式传入并进入非敏感配置记录，跨模型报告会披露这一限制。

如果服务明确支持相应参数，可额外加入 `--thinking enabled` 和 `--reasoning-effort high`。不支持时不要强行发送。跨供应商相同的 `max-tokens=12000` 只表示相同输出上限；tokenizer、推理 token 计量和服务端默认值仍可能不同。

网络中断后使用完全相同的参数、同一个 `$run`，再加 `--resume`。不要创建新目录补跑，也不要删除失败归档。

## 3. 报告、复核与发布

完成 216 个任务后先生成本地报告：

```powershell
python src/feedback_study.py report --run $run
```

对所有成功证明执行独立 Lean 编译与 AI 辅助语义复核，填写 `$run/ai_assisted_review.csv`。`review_mode` 必须保持 `ai_assisted`；不得写成纯人工复核。随后再次运行报告，确认 `release_ready=true`。

```powershell
$release = "published/feedback-study-second-model-" + (Get-Date -Format "yyyyMMdd-HHmmss")
python scripts/export_feedback_study.py --run $run --out $release
python scripts/audit_feedback_study.py $release
python scripts/audit_feedback_study.py $release --compile-solutions --timeout 180
```

导出器按实际成功数发布证明，不要求第二模型复制基线的 199 个成功；但必须完整覆盖 216 个任务且至少有一个成功证明。公开包仍排除逐请求完整 prompt、认证字段、供应商响应 ID、本机绝对路径与 `retry_history` 原文。

## 4. 跨模型一致性报告

只有两个发布包都通过审计后才运行：

```powershell
$comparison = "published/feedback-cross-model-" + (Get-Date -Format "yyyyMMdd-HHmmss")
python scripts/compare_feedback_models.py `
  --baseline "published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248" `
  --replication $release `
  --out $comparison
python scripts/audit_feedback_comparison.py $comparison
```

报告按表示给出两个模型的 pass@1、三轮内成功数、逐任务结局一致率和成功差，并比较 normalized−raw、structured−raw、structured−normalized 三种表示差方向是否一致。方向一致率会单列 `both_zero`；两个模型都没有表示差异不能被写成“处理增益得到复现”。

## 5. 结论边界

- 三次重复是同一数学题的重复生成，不能当成 72 道独立题。
- 单个第二模型只能增加一份跨模型证据，不能证明对所有模型或供应商泛化。
- 任务一致率不等于模型行为等价；表示差方向一致也不等于统计显著。
- tokenizer、隐藏系统提示、模型别名更新和推理接口差异必须随报告披露。
- 不为追求一致而挑选重复、修改失败结果或在观察结果后改变公共控制。
