# TRACER 历史归档 / Historical Archive

本目录保存已经被当前主线取代、但仍有复核价值的实验、发布包、配置与交接材料。整理只改变目录位置，没有删除项目或改写原始结果。

This directory preserves experiments, releases, configurations, and handoff material that have been superseded by the current research line. The reorganization changes locations only: it does not delete a project or rewrite its recorded outcomes.

## 当前主线与归档边界 / Active–historical boundary

当前主线保留在仓库根目录：

- `published/research-six-arm-313f437f/`：当前 repair24 六臂主结果；
- `published/security-study-tracer-sp-v2/`：当前 SP v2 安全回归；
- `benchmarks/real_repairs/tracer_real_v2/` 及相关筛查账本：下一阶段冻结题库；
- `src/`、`scripts/`、`tests/`：当前实现，以及继续复核历史工件所需的兼容与审计代码；
- `capsules/`、`results/capsule_feasibility/`、`results/capsule_challenges/`：当前 LeanCapsule 案例和回放证据。

The repository root keeps the current six-arm release, SP v2 release, frozen TRACER-REAL v2 inputs, active implementation, audit utilities, and current LeanCapsule evidence. Historical evidence lives below.

## 归档索引 / Archive index

| 目录 | 内容 | 状态 |
| --- | --- | --- |
| [`evaluation18_pilot/`](evaluation18_pilot/) | 18 题 × P-A/P-B/P-C smoke pilot、54 个证明、人工复核、报告与旧入口 | 工程链路历史证据；不用于反馈增益结论 |
| [`feedback_study_v1/`](feedback_study_v1/) | 两批 216 任务反馈表示实验、跨模型配对、408 个证明及协议文档 | 六臂实验之前的辅助研究 |
| [`fate_m/`](fate_m/) | AxProverBase/FATE-M Part 1–3 配置、runner、工作流快照和交接结果 | 已结束的独立研究支线 |
| [`MIGRATION_COMPARISON.md`](MIGRATION_COMPARISON.md) | 早期本地目录迁移核对记录 | 只用于追溯 |
| [`early_research_notes.md`](early_research_notes.md) | 早期细化想法 | 只用于追溯，不代表当前计划 |

## 复核规则 / Review rules

1. 历史数值必须引用对应归档工件，不得与当前六臂结果合并。
2. 历史 JSON 的条件值、候选和诊断保持原样；公开显示名只在说明文档中解释。
3. `scripts/` 中保留的审计器和 `tests/` 中保留的兼容回归仍可读取本目录，目的是防止归档工件失效，不代表旧研究重新成为当前主线。
4. 新实验不得写入本目录，应使用独立结果目录并通过当前发布门禁。

Historical numbers must be cited from their own artifacts and must not be pooled with the current six-arm result. Compatibility tests may continue to read this directory solely to prevent archived evidence from silently decaying.
