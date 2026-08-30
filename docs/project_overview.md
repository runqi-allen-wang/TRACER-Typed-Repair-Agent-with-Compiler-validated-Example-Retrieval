# 项目概览

TRACER（Typed Repair Agent with Compiler-validated Example Retrieval）是 Lean 4 局部证明修复、失败复现与实验审计工具箱。它不训练模型，而是在推理阶段连接模型候选、Lean 编译反馈、本地示例检索、受控重试和可追踪结果。

## 三条工作流

1. **Agent 修复**：`src/agent.py`、`compiler.py`、`provider.py` 与 `retriever.py` 组成最多三轮的局部修复环；原文件不被覆盖，成功证明和逐轮记录分别落盘。
2. **LeanCapsule 复现**：`src/leancapsule/` 负责定理抽取、full-file fallback、有界 import 精简、回放、gallery、issue 文本和发布审计。
3. **研究评测**：旧 18×3 pilot、repair24 六臂 runner、AxProverBase Part 1/2 配对入口和 Capsule 价值测量彼此隔离，不能混合日志或结论。

## 命名约定

- 已发布 smoke pilot 使用 P-A/P-B/P-C 表示历史 A/B/C 条件。
- repair24 公开显示为 R-A～R-F；存储值保持 `A/B/C/D/C_dynamic/C_failure`。
- SP-n 表示非实验性的 Security Policy 回归；当前案例为 SP-1。

## 当前可核查工件

- 18 个冻结 smoke 题与已发布 54 个题目×条件成功证明。
- 24 个公开失败 Capsule 及其索引和人工复核台账。
- 12-core / 4-challenge 可行性结果：core 12/12，challenge 干净回放 4/4。
- FATE-M 25 题 Part 1/2 corrected 配对 handoff。
- repair24 题库、六臂 runner 和离线门禁；完整多模型结果尚未完成。

证据与未完成事项以 [当前进度](../PROGRESS.md) 为准；历史改动见 [补丁记录](../CHANGELOG.md)。

## 后续研究重点

根据 2026 年 8 月 30 日来自 [subfish-zhou](https://github.com/subfish-zhou) 与 [Fulcrum-Nebula](https://github.com/Fulcrum-Nebula) 的社区反馈，下一阶段优先研究两项问题：

1. 深化 Lean 编译诊断反馈：比较不同反馈表示，跟踪错误类别跨轮次变化，并验证模型是否真正采纳诊断，而不是只统计最终通过率。
2. 将 SP-1 扩展为版本化 SP-n 安全计划：补充威胁模型、对抗案例、误放行/误拒绝指标与操作系统级隔离实验。

这两项均为待完成工作，不改变当前 R-A～R-F 或 SP-1 的既有证据。详细约束见 [研究实验操作与预注册协议](RESEARCH_PROTOCOL.md#7-社区评审驱动的后续工作)。

## 无付费调用的复验

```text
lake build
python scripts/run_capsule_feasibility.py --verify-only
python scripts/run_ci_tests.py
python -m leancapsule audit capsules
python -m leancapsule verify capsules
```

最后一项需先准备固定的 Mathlib 依赖。上述命令不产生模型实验结果，也不能代替成功证明的人工数学复核。
