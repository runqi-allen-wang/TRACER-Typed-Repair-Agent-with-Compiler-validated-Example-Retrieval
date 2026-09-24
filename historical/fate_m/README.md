# FATE-M / AxProverBase 研究支线（历史）

本目录把 2026 年 8 月完成的 FATE-M Part 1–3 材料集中保存：

- `baseline/`：25 题 runner、manifest 与运行配置；
- `configs/`：冻结的 AxProverBase 模型和处理器配置；
- `docs/`：Part 2、混杂拆分臂与 Part 3 交接说明；
- `results/handoff/`：corrected 配对、Experience + CapsuleFeedback 与 Raw/Capsule 交接工件；
- `workflows/`：当时使用的 Actions 工作流快照，已退出活跃 `.github/workflows/`；
- `requirements-axprover-part2.txt`：当时固定的外部依赖。

主线 `src/leancapsule/` 中继续保留兼容解析和 CapsuleFeedback 实现，`scripts/` 与 `tests/` 中继续保留审计入口，因此历史工件仍可复核。它们不再属于当前 GitHub Actions 默认工作流，也不应与当前 repair24 六臂结果合并统计。
