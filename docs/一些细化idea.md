# LeanCapsule 实施状态与后续研究

- **安全对抗（已实现）**：独立安全策略案例 SP-1 覆盖 `unsafe inductive` 绕过 positivity 检查并构造 `False`。SP 不是实验组；它要求 Agent、AxProverBase 与 Capsule 在编译前拒绝恶意候选，详见 [`security_policy.md`](security_policy.md)。

## 1. 提高错误保真度，同时控制验证成本

- **当前做法**：`pack` 比较原文件与 capsule 的编译状态及规范化 `diagnostic_key`；`replay/verify` 再检查状态、诊断类别和 key，并保留原始诊断供人工复核。
- **已补强**：12-core / 4-challenge 可行性运行额外直接比较完整有序的规范化诊断文本，并保留源码、工具链与依赖清单原文；若抽取后的状态或诊断变化则退回 full-file capsule。该严格比较是分析指标，不替代现有 `diagnostic_key`，也不等于语义等价。
- **仍待研究**：目前不是完整的 goal/local-context 捕获或任意项目依赖绑定。后续可扩展结构化诊断，但不能把 16 个合成案例外推为普遍保真。

## 2. 扩充 Capsule 可行性案例集

- **已完成**：在 24 个公开 gallery 回归之外，新增 16 组“正确模板 + 单点错误变异”。12 个 core 覆盖四类错误 × 三种上下文，4 个 challenge 保留同文件依赖、项目多文件、命名空间和多诊断边界。自动运行会编译两个版本、执行 `pack/replay`、复制到干净目录复验并汇总结果。
- **当前证据**：core 门禁 12/12、challenge 干净回放 4/4，全部 16 个案例保留诊断键和完整有序规范化诊断。core standalone/fallback 为 5/7，challenge 为 2/2。结果见 [`CAPSULE_FEASIBILITY.md`](CAPSULE_FEASIBILITY.md)。这些是有限合成案例，不包含任意 Lake 动态依赖或真实大型维护故障。

## 3. 给Capsule 加入接口，加入基线agent后比对效果

实验场景：预算受限下的agent证明定理成功率


AxProverBase的工作流程（考虑作为baseline）
读取目标定理和完整 Lean 文件
            ↓
Proposer LLM 生成整份新证明
            ↓
临时替换进原文件，运行 lake build
            ↓
失败：返回编译错误或 sorry 处的目标状态
            ↓
Memory 把失败经验压缩成“实验笔记”
            ↓
下一轮 LLM 根据错误和笔记修改证明
            ↓
编译成功：检查作弊，再交 Reviewer
            ↓
审核通过：正式写回 Lean 文件

把以下两个环节替换成我们自己创建的模块
失败：返回编译错误或 sorry 处的目标状态
            ↓
Memory 把失败经验压缩成“实验笔记”

该工作流分为以下三部分。Part 1/2 已完成一批正式配对运行；Part 3 目前只有后续复验清单，不是新增结果。
### Part 1：基线准备

从一个公开 benchmark 固定抽取约 20～30 题，冻结 AxProverBase commit、Lean/Mathlib 环境、模型、工具和预算配置。先运行默认 Experience memory，时间允许时补充 Memoryless；关闭不参与证明的最终 LLM summary，并按 proposer、memory、reviewer、tool 分别记录调用次数、token、成本、编译时间和成功节点，同时缓存每题的首轮候选。

### Part 2：Capsule 封装

待 Capsule 保真度和案例集优化完成后，将其封装为轻量 `CapsuleFeedback`：直接消费 Ax 已有的编译结果，不重复编译，只输出错误类别、规范化诊断文本、重复次数、诊断变化和紧凑历史，供下一轮 Proposer 使用；重复判断直接比较规范化诊断文本。

当前状态：Part 1 runner、Part 2 核心与真实 Ax 包裹入口、逐 theorem 状态、Memoryless/`yxai` Responses 配置、遥测和严格配对门禁均已实现。FATE-M 25 题配对实验已完成，修正版正式交接结果位于 `results/handoff/part12-live-20260828-corrected/`。

### Part 3：后续重复与扩展（尚未执行）

已完成的 Part 1/2 批次在同一批任务上配对比较原始 AxProverBase 与 `AxProverBase + CapsuleFeedback`，共享首轮候选并固定模型和配置。若开展新的 Part 3，应在独立目录中重复两组、扩大模型或批次，并按 task id 做配对分析；现有 [交接清单](part3_experiment_handoff.md) 只校验已有 handoff，不调用模型，也不构成新的实验。
