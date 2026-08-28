# Results

正式评测结果写入 `real_pilot_runs.jsonl`，成功证明写入 `solutions/`，请求缓存写入 `requests.sqlite3`。`report.py` 还会生成 token 汇总和 `pilot_topic_summary.csv`。`evaluate.py --fresh` 会先把上一轮日志、缓存、solutions、复核表和报告工件移入带时间戳的 `archive/`，不会静默删除旧运行。

交互式单题运行默认写入 `agent_runs.jsonl`。其中 `provider_error` 表示接口调用失败；若该字段为空且存在 Lean `diagnostic`，说明请求已获得候选，失败发生在编译验证阶段。候选会在落盘前移除常见 Markdown 代码围栏，历史缓存命中时也会重新执行该步骤。

旧的 `pilot_runs.jsonl`、`pilot_summary.csv`、`pilot_report.json` 和 SVG 只属于历史离线脚手架演示，不得用于研究结论；重新运行正式 provider 后，应使用 `real_pilot_runs.jsonl` 和新生成的报告。运行结束时带 `DRAFT` 标记的报告只说明执行完成，不说明人工复核完成。

`manual_review.csv` 是逐题逐条件的人工复核台账。正式 pilot 后，应为每个成功候选人工填写 `kernel_pass`、不恰当假设、泄漏风险和复核备注。前三列使用 `yes` 或 `no`；正式结果要求依次为 `yes`、`no`、`no`，工具不会生成复核结论。最终门禁为：

```powershell
python scripts/validate_pilot.py --require-manual-review
python src/report.py
```

原始日志、缓存、solutions、archive 和 handoff 都默认被 `.gitignore` 排除。原始 JSONL 可能包含本机绝对路径，不能直接提交；请求缓存也不属于交接工件。复核完成后生成脱敏包：

```powershell
python scripts/export_pilot.py --out results/handoff/pilot-reviewed
```

导出器解析 JSONL、替换仓库/用户/临时目录、拒绝明显凭据、不复制 SQLite，并为文件生成 SHA-256 清单。检查导出内容后，如需要通过 Git 交接，必须显式选择：

```powershell
git add -f results/handoff/pilot-reviewed
```

### Part 3 Raw/Capsule 交接包

`results/handoff/part3-minimal/` 是 Part 3 的选择性正式交接包，包含 Raw/Capsule 两组逐题 JSONL、严格配对报告、逐题 CSV、汇总报告和 SHA-256 清单。它们使用同一批首轮候选；Raw 与 Capsule 都是 `MemorylessProcessor`，区别仅为失败反馈是否经过确定性 `CapsuleFeedback`。本次 25 题 pilot 的结果和限制见 [`docs/part3_raw_capsule_experiment.md`](../docs/part3_raw_capsule_experiment.md)。

该目录也默认被忽略；确认内容不含凭据和本机路径后，若需要提交实验原始结果，必须显式执行：

```powershell
git add -f results/handoff/part3-minimal
```

不要提交 `results/work/part3-minimal/` 中的 metrics、Capsule state 或请求缓存。
