# 项目概览

TRACER（Typed Repair Agent with Compiler-validated Example Retrieval）是 Lean 4 局部证明修复、编译反馈实验与失败复现工具箱。它不训练模型，而是在推理阶段连接候选生成、Lean 编译、结构化反馈、错误自适应检索、有限重试与可审计发布。

## 当前三条主线

1. **证明修复**：`src/agent.py`、`compiler.py`、`provider.py` 与 `retriever.py` 在隔离临时项目中执行候选、编译、反馈和保存；原题文件不被覆盖。
2. **研究评测**：repair24 的 R-A～R-F 六臂 runner、反馈采纳分析和发布门禁已经形成 864 任务正式结果；TRACER-REAL v2 已冻结 265 题 manifest，其中确认性 test 为五个项目的 254 题，尚未运行 provider。
3. **失败与安全工件**：LeanCapsule 保存可回放失败；SP-1～SP-12 在编译前阻止冻结的危险候选，并用 CTRL-1～CTRL-8 监测正常输入误拒绝。

## 当前可核查证据

- `published/research-six-arm-313f437f/`：864 个任务、1,066 条脱敏逐轮记录、811 个成功证明和 864 行 AI 辅助复核；
- `published/security-study-tracer-sp-v2/`：12 个危险案例和 8 个正常对照；
- `capsules/`、`results/capsule_feasibility/`、`results/capsule_challenges/`：24 个 gallery 案例及 12-core / 4-challenge 回放；
- `benchmarks/real_repairs/tracer_real_v2/`：下一阶段已经冻结、尚未调用 provider 的真实修复题库。

旧 Evaluation18 pilot、两批 Feedback Study v1 和 FATE-M Part 1–3 没有删除，统一见 [`historical/`](../historical/README.md)。它们不与当前六臂结果合并统计。

## 命名与证据边界

- repair24 公开显示为 R-A～R-F，存储值保持 `A/B/C/D/C_dynamic/C_failure`；
- SP-n 是 Security Policy，不是额外实验臂；
- 重复与实验臂不能把 24 道独立题扩充为 864 道独立样本；
- mock、离线计划、Lean 编译通过和发布审计均不能单独替代真实 provider 研究结论。

当前数字、未完成事项和验收命令以 [`PROGRESS.md`](../PROGRESS.md) 为准；未来路线见 [`FUTURE_WORK_PLAN.md`](FUTURE_WORK_PLAN.md)。

## 无付费调用的核心复验

```text
lake build
python scripts/verify_compiler_feedback_v1.py --verify-only
python src/tracer_real_v2.py audit
python scripts/audit_research_release.py published/research-six-arm-313f437f
python src/security_study.py --check published/security-study-tracer-sp-v2/report.json
python scripts/run_ci_tests.py
python -m leancapsule audit capsules
python -m leancapsule verify capsules
```

最后一项需要先准备固定的 Mathlib 依赖。上述命令不调用付费模型，也不把软件测试自动解释为研究假设成立。
