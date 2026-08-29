# Results 目录说明

本目录同时包含已保存研究工件和本地运行默认输出。判断一项结果是否可发布，必须查看其协议、原始轨迹、证明文件和人工复核，不能只看汇总表。

## 当前纳入源码导出版的工件

- `capsule_feasibility/`：12-core / 4-challenge 合并可行性结果与生成的 Capsule。
- `capsule_challenges/`：4 个 challenge 的逐项结果与生成的 Capsule。
- `handoff/part12-live-20260828-corrected/`：FATE-M 25 题 AxProverBase Part 1/2 corrected 配对交付；同级旧目录是历史版本。
- `handoff/part2-experience-capsule-20260829/`：FATE-M 25 题 B 臂（`ExperienceProcessor + CapsuleFeedback`）的原始逐题结果、遥测、首轮缓存、配对报告和状态快照。
- `manual_review.csv`：已发布 18×3 pilot 的 54 个题目×条件人工复核副本。
- 根目录 `pilot_*` 与 SVG：旧 18×3 pilot 的汇总视图；正式可移交证据以 `published/pilot-20260826T122354Z-d628742d/` 为准。

## 本地运行时可能生成但当前导出版未包含

- `real_pilot_runs.jsonl`、`solutions/<experiment_id>/`、`requests.sqlite3`：旧 18×3 真实 provider 批次。
- `agent_runs.jsonl` 与 `solutions/`：交互式单题运行。
- `research-*/`：repair24 多臂研究、跨环境度量或人工研究材料。

缺少这些目录时，表示当前源码导出版不携带对应原始轨迹，不能根据文档中的历史说明反推出结果已被发布。系统不会自动填造人工复核、费用或成功证明。

B 臂交接包中的 `capsule-experience.jsonl` 和 `metrics.jsonl` 是运行原始记录；`state/` 保存
CapsuleFeedback 的最终状态快照，不是 Lean、Mathlib 或 Python 依赖缓存。交接清单记录相对路径和
文件大小，发布前可从仓库根目录运行下面的离线门禁（不会调用模型 API）：

```text
python scripts/validate_b_handoff.py
```

## 结果判读

- `provider_error` 表示请求未产生可编译候选；Lean 的 syntax/type/goal 诊断表示请求已经获得候选，失败发生在编译阶段。
- 请求缓存只适合本地调试；正式独立运行不得把缓存命中当作新采样。
- 未配置 token 价格时成本是 unknown/null，不是零。
- 可行性实验使用规范化可读文本直接比较诊断，不保存派生摘要字段。

已发布 18×3 pilot 使用历史 `tracer-candidate-v1`。只读复核该归档时必须显式增加 `--allow-legacy-candidate-policy`；新实验不得使用该兼容开关，仍必须满足当前 v2 门禁。
