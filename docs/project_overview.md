# 项目概览

TRACER（Typed Repair Agent with Compiler-validated Example Retrieval）是 Lean 4 局部证明修复、失败复现与实验审计工具箱。它不训练模型，而是在推理阶段连接模型候选、Lean 编译反馈、本地示例检索、受控重试和可追踪结果。

## 三条工作流

1. **Agent 修复**：`src/agent.py`、`compiler.py`、`provider.py` 与 `retriever.py` 组成最多三轮的局部修复环；原文件不被覆盖，成功证明和逐轮记录分别落盘。
2. **LeanCapsule 复现**：`src/leancapsule/` 负责定理抽取、full-file fallback、有界 import 精简、回放、gallery、issue 文本和发布审计。
3. **研究评测**：旧 18×3 pilot、repair24 六臂 runner、AxProverBase Part 1/2 配对入口和 Capsule 价值测量彼此隔离，不能混合日志或结论。

## 命名约定

- 已发布 smoke pilot 使用 P-A/P-B/P-C 表示历史 A/B/C 条件。
- repair24 公开显示为 R-A～R-F；存储值保持 `A/B/C/D/C_dynamic/C_failure`。
- SP-n 表示非实验性的 Security Policy 回归；当前离线套件为 SP-1～SP-6，并配有 CTRL-1～CTRL-3 正常对照。

## 当前可核查工件

- **已发布证据**：Evaluation18 的 56 条逐轮记录、54 个成功证明与完整人工复核；24 个公开失败 Capsule；12-core / 4-challenge 可行性结果；FATE-M Part 1/2、拆分臂与 Part 3 交接工件。
- **可复验实现**：repair24 题库、R-A～R-F 六臂 runner、反馈采纳/query 变化审计、raw/normalized/structured 对照 runner、SP 双向指标、动态查询、失败 Capsule 上下文、跨环境与真人研究入口；这些功能不等于相应研究结论已经获得。
- **当前不含原始证据**：历史 DeepSeek R-B 预跑、Windows/WSL 比较和真人计时数据，不作为公开结果。
- **未来计划**：运行并复核真实 provider 三表示对照，扩大 SP 案例覆盖，并验证操作系统级隔离。

证据与未完成事项以带日期的[当前进度与证据登记](../PROGRESS.md)为准；历史改动见[补丁记录](../CHANGELOG.md)。

## 后续研究重点

根据 2026 年 8 月 30 日来自 [subfish-zhou](https://github.com/subfish-zhou) 与 [Fulcrum-Nebula](https://github.com/Fulcrum-Nebula) 的社区反馈，下一阶段优先研究两项问题：

1. 深化 Lean 编译诊断反馈：离线三表示和采纳指标已经实现，下一步在冻结预算下运行真实 provider 配对实验并完成证明复核。
2. 深化 SP-n 安全计划：第一版威胁模型、6 个恶意案例和 3 个正常对照已经实现，下一步扩大案例并验证容器或低权限隔离。

这些新增内容目前仍是可复验实现，不改变 R-A～R-F 或已发布 SP-1 证据，也不构成模型增益或完整安全结论。详细约束见 [研究实验操作与预注册协议](RESEARCH_PROTOCOL.md#7-社区评审驱动的后续工作)，执行顺序见 [编译反馈与 SP-n 后续工作方案](FUTURE_WORK_PLAN.md)。

## 无付费调用的复验

```text
lake build
python scripts/run_capsule_feasibility.py --verify-only
python scripts/verify_compiler_feedback_v1.py --verify-only
python src/feedback_study.py plan
python src/security_study.py
python scripts/run_ci_tests.py
python -m leancapsule audit capsules
python -m leancapsule verify capsules
```

最后一项需先准备固定的 Mathlib 依赖。上述命令不产生模型实验结果，也不能代替成功证明的人工数学复核。
