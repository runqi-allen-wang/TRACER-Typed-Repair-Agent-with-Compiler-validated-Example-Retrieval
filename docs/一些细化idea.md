# LeanCapsule 细化 idea

- **安全对抗补充**：新增独立 D 类安全回归，D01 覆盖 `unsafe inductive` 绕过 positivity 检查并构造 `False`。D 类不是 A/B/C 的第四个 Agent 条件；它要求原 Agent、AxProverBase 与 Capsule 在编译前拒绝恶意候选，详见 [`security_type_d.md`](security_type_d.md)。

## 1. 提高错误保真度，同时控制验证成本

- **当前做法**：`pack` 比较原文件与 capsule 的编译状态及规范化 `diagnostic_key`；`replay/verify` 再检查状态、诊断类别和 key，并保留原始诊断供人工复核。
- **不足**：key 主要来自前两条、至多 700 字符的诊断摘要；路径、位置和 metavariable 被归一化后，不同错误可能碰巧相同。后续回放只与 manifest 比较，无法证明它仍与原项目中的真实错误一致，也未完整绑定源码和依赖状态。
- **建议**：保留目标位置、全部相关错误及 goal/local context 等结构化诊断，并保存源码、工具链版本和依赖锁文件原文。`pack` 或发布 CI 采用严格模式，对原错误与 capsule 做同环境差分复编译；日常 `replay` 重新编译，并直接比较编译状态和规范化后的完整诊断文本。每次发布重新验证全部案例；若抽取后的编译结果与原文件不一致，则退回 full-file capsule，并保留人工抽检。

## 2. 扩充 Capsule 可行性案例集

- **当前问题**：现有 24 个案例虽覆盖四类常见错误和三类来源，但大多是 3～10 行的人工校准程序；22 个使用 full-file fallback，几乎没有验证失败定理的 standalone 抽取，也缺少多错误、多文件、复杂局部上下文和跨环境案例，因此只能证明原型可回放，不能证明普遍可行。
- **快速方案**：保留现有案例作为回归集，新增约 16 组“正确模板 + 单点错误变异”，按 Name、Type、Elaboration、Goal 四类覆盖独立定理、同文件依赖、项目依赖和对抗场景。脚本自动编译两个版本、执行 `pack/replay`、在干净目录复验，并汇总诊断保真率、standalone/fallback 比例和耗时；其中 12 个作为必须通过的 core，4 个作为保留失败结果的 challenge，避免只筛选成功案例。

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

具体流程分为这3部分
### Part 1：基线准备

从一个公开 benchmark 固定抽取约 20～30 题，冻结 AxProverBase commit、Lean/Mathlib 环境、模型、工具和预算配置。先运行默认 Experience memory，时间允许时补充 Memoryless；关闭不参与证明的最终 LLM summary，并按 proposer、memory、reviewer、tool 分别记录调用次数、token、成本、编译时间和成功节点，同时缓存每题的首轮候选。

### Part 2：Capsule 封装

待 Capsule 保真度和案例集优化完成后，将其封装为轻量 `CapsuleFeedback`：直接消费 Ax 已有的编译结果，不重复编译，只输出错误类别、规范化诊断文本、重复次数、诊断变化和紧凑历史，供下一轮 Proposer 使用；重复判断直接比较规范化诊断文本。

当前状态：Part 1 runner、Part 2 核心与真实 Ax 包裹入口、逐 theorem 状态、Memoryless/`yxai` Responses 配置、遥测和严格配对门禁均已实现。FATE-M 25 题配对实验已完成，修正版正式交接结果位于 `results/handoff/part12-live-20260828-corrected/`。

### Part 3：修改后 Agent 测试

在同一批任务上配对比较原始 AxProverBase 与 `AxProverBase + CapsuleFeedback`，共享首轮候选，并固定模型、工具和总 LLM 调用/token/成本预算。主要比较最终通过率、首轮失败后的修复率、调用与成本、重复错误比例；正式结论前应在同一时间窗口重跑两组，避免模型服务变化影响结果。
