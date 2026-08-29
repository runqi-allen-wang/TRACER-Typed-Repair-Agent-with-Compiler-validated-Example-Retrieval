# Results

正式评测结果写入 `real_pilot_runs.jsonl`，成功证明按 `solutions/<condition>/` 保存；实验批次由每条 JSONL 的 `experiment_id` 区分，请求缓存写入 `requests.sqlite3`。`report.py` 还会生成 token 汇总和 `pilot_topic_summary.csv`。

交互式单题运行默认写入 `agent_runs.jsonl`。其中 `provider_error` 表示接口调用失败；若该字段为空且存在 Lean `diagnostic`，说明请求已获得候选，失败发生在编译验证阶段。候选会在落盘前移除常见 Markdown 代码围栏，历史缓存命中时也会重新执行该步骤。

旧的 `pilot_runs.jsonl`、`pilot_summary.csv`、`pilot_report.json` 和 SVG 只属于历史离线脚手架演示，不得用于研究结论；重新运行正式 provider 后，应使用 `real_pilot_runs.jsonl` 和新生成的报告。

`manual_review.csv` 是逐题逐条件的人工复核台账。正式 pilot 后，应为成功候选填写 `kernel_pass`、不恰当假设、泄漏风险和复核备注；字段为空时报告会明确标记为不可发布，不会自动补值。
