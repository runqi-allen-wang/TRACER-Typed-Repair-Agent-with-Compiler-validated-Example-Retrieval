# Causal Feedback v1：同首轮候选的诊断干预协议

## 研究问题

Feedback Study v1 比较了 raw、normalized 和 structured 三种表示，但每个表示会独立生成候选。因此，它能描述不同表示下的结果，不能排除重复采样本身带来的收益。

Causal Feedback v1 将实验单位改为“模型 × 重复 × 题目的一次冻结首轮候选”。所有干预分支必须看到完全相同的首轮候选；只有该候选形成真实、非基础设施的 Lean 编译失败时，任务才进入主分析。首轮已经成功、provider 错误、编译器不可用、超时或安全门禁拒绝都会如实记录，但不混入反馈效果估计。

机器可读协议为 [`experiments/causal_feedback.protocol.json`](../experiments/causal_feedback.protocol.json)，实现入口为 [`src/causal_feedback.py`](../src/causal_feedback.py)。项目级试点已经在 [`experiments/preregistrations/tracer_real_causal_v1.json`](../experiments/preregistrations/tracer_real_causal_v1.json) 中冻结；provider 结果必须晚于该预注册版本，且不得反向修改题库、主对比或停止规则。

## 两阶段设计

### 阶段一：冻结首轮

1. 使用同一无反馈提示生成一个完整局部证明；
2. 执行候选安全门禁和 Lean 编译；
3. 保存原始、规范化、结构化三层反馈；
4. 构造 Error-State Graph；
5. 冻结候选文本，禁止在分支之间重新生成首轮。

对超过 12,000 字符的真实源码，提示视图固定保留 imports、目标前最近局部上下文和完整目标声明，绝不以“截取文件开头”的方式丢掉目标。分支提示逐字包含完整冻结候选、干预载荷和该分支已记录的检索示例；这些内容不允许静默截短。

### 阶段二：从同一候选分叉

| 干预 | 模型收到的信息 | 用途 |
| --- | --- | --- |
| `content_free_retry` | 只说明首轮未通过 | 估计单纯重复采样的基线 |
| `true_raw` | 目标题的脱敏原始诊断 | 检查完整编译器文本的作用 |
| `true_normalized` | 目标题的规范化诊断 | 去除路径与易变噪声 |
| `true_structured` | 目标题的结构化类别与信号 | 检查提取信息的作用 |
| `irrelevant_matched` | 同模型、同重复、同错误类别的另一题原始诊断 | 检查额外诊断文本本身是否造成收益或干扰 |
| `counterfactual` | 保留目标错误类别，但替换为另一题的不同信号值 | 检查模型是否会盲从看似合理但错误的信息 |
| `retrieval_only` | 不给诊断，只给排除命题重合后的本地示例 | 分离检索与反馈 |
| `adaptive` | 由路由器依据 Error-State Graph 选择的最小反馈与检索动作 | 原型方法组 |

无关和反事实供体在同模型、同重复、同错误类别内按可读题号确定，禁止自配对。反事实还要求供体信号与目标信号不同；找不到合格供体时，分支标记为 `not_applicable`，不得偷偷换错误类别或继续调用模型。

v1 的主终点是每个分支**一次修复生成后的 Lean 内核成功**。多轮 adaptive policy 属于后续版本，不能和 v1 单步因果估计混算。

## Error-State Graph

[`src/error_state_graph.py`](../src/error_state_graph.py) 将 Compiler Feedback v1 转换为以下可审计节点和边：

- 定理、候选、错误状态与诊断类别；
- 源码位置和局部源码窗口；
- 未知标识符、实际/期望类型、目标和实例等诊断信号；
- 每个信号到原始诊断片段的 `supported_by` 边；
- 相邻轮次的类别变化、解决状态和信号增删。

图中的可读节点编号只表示一条记录内部的结构，不用作跨文件派生身份。验证器拒绝悬空边、重复节点、无证据的结构化信号和版本漂移。

## Adaptive Router 原型

[`src/adaptive_router.py`](../src/adaptive_router.py) 当前是明确标注的确定性基线：

- 基础设施错误停止生成；
- 语法错误保留原始文本；
- 未知标识符使用结构化信号并触发错误驱动检索；
- 其他证明错误先使用最小结构化反馈；
- 同类错误连续出现时，升级到原始证据加结构化信号，并刷新检索。

每次决策记录表示、检索策略、字符预算、截断状态和可读理由。它还不是学习得到的策略，也没有正式模型增益证据。后续可以在不改变 Error-State Graph 数据契约的前提下替换为 contextual bandit 或其他预算策略。

## 离线预览

```powershell
python src/causal_feedback.py plan
```

默认 repair24 示例计划包含 72 个首轮任务；若全部首轮失败，最多产生 576 个分支任务，总生成上限为 648。实际分支数由首轮失败资格和负对照供体可用性决定。`plan` 不访问网络。

当前 runner 提供真实 provider 接口，但本仓库没有执行或发布该批次。任何正式运行都必须先冻结题库、模型、费用、统计分析和复核资源，并写入全新结果目录。

TRACER-REAL v1 的预注册试点使用按上游项目互斥的 11 题清单，但主分析只打开未参与开发或验证的 Aesop test 项目：4 题 × 3 次重复，12 个首轮生成；只有真实首轮失败进入八分支干预，最大 108 次 provider 调用。唯一主对比为 `true_structured - content_free_retry`。由于 test 只有一个项目且最多 12 个合格首轮失败，预注册的 5 项目/30 合格失败结论门禁必然不满足；因此这次运行用于检验流程、方向和失败模式，不能写成正式统计显著或跨项目因果结论。

冻结计划：

```powershell
python src/causal_feedback.py plan `
  --config experiments/causal_feedback.tracer_real_v1.json `
  --benchmark benchmarks/real_repairs/tracer_real_v1/manifest.json `
  --project-root mathlib_project `
  --preregistration experiments/preregistrations/tracer_real_causal_v1.json
```

真实运行入口要求显式选择本地费用门禁。`--max-reserved-usd` 需要同时冻结输入/输出价格；`--no-cost-limit` 只表示不按本地美元估算停止，仍受 `--max-calls` 和冻结计划上限约束，不代表供应商免费。正式实验不应直接把本示例命令当作预注册。

## 主分析与结论边界

主要报告必须至少包含：

- 首轮资格率和全部排除原因；
- 每个冻结首轮候选内的配对结果；
- 相对 `content_free_retry` 的成功差；
- 无关反馈和反事实反馈的误导率；
- 按错误类别、项目、token、时间和编译次数的结果；
- 供体不可用和基础设施错误；
- 按题目和项目聚类的不确定性分析。

当前代码输出的 `descriptive_lift_over_content_free` 和逐项目效应只是描述值，不是统计显著或跨项目因果结论。`audit` 会核对计划中的 12 个首轮、所有应有分支、基础设施错误、同首轮候选和成功证明独立复编译不变量，并单独输出 `confirmatory_claim_allowed`。

## 真实修复任务

[`src/real_repairs.py`](../src/real_repairs.py) 从公开仓库的版本对构建候选任务。只有同时满足下列条件才会写入新基准：

1. 定理陈述未变化；
2. 旧证明放入修复版本上下文后稳定失败；
3. 对应修复证明在同一固定环境独立通过；
4. 来源仓库、许可、版本、文件与定理名完整；
5. 参考证明写入独立目录，公开任务和运行器不读取它。

字段示例与命令见 [`benchmarks/real_repairs/README.md`](../benchmarks/real_repairs/README.md)。当前 `tracer-real-v1` 含 Mathlib 3 题、Batteries 4 题、Aesop 4 题，开发/验证/测试按项目隔离；每题均满足陈述不变、旧证明失败、当前证明通过。运行时须显式使用 `--project-root mathlib_project`。更大规模、多 test 项目的 TRACER-REAL 扩展与独立模型复现仍是后续工作。
