# 当前工作进度

更新时间：2026-08-28

补丁明细见 [CHANGELOG.md](CHANGELOG.md)；本文件只维护当前状态和剩余边界。

## 已完成

- 修复 Bash Mathlib 安装遇到临时网络错误就立即退出的问题：依赖同步与缓存下载有限重试，残缺传递依赖备份后重试，保留原始错误并在耗尽后失败；CI 设置 30 分钟安装步骤上限。同步中英文 README，未改 PowerShell 入口或依赖固定版本。
- 新增中英文双版 README：默认首页 `README.md` 使用英文，`README.zh-CN.md` 保留完整中文，两版顶部相互链接；命令、实验数据和证据链接一致，许可说明同步为仓库现有 MIT License。
- 重构 README 为研究工具首页：补充项目价值、可核查设计贡献、双入口架构图、适用场景、真实 pilot 结果及证据链接；明确无训练、失败回放与成功证明的区别，以及实验结论和许可边界。
- 补充 `docs/API_GUIDE.md`，统一 DeepSeek / OpenAI GPT、PowerShell / Git Bash、安全密钥输入、本地 HTTP 接口与排错步骤；内置 provider 现同时支持 Chat Completions 与 Responses API，并显式控制 reasoning effort 和响应存储。
- 将 TRACER 的编译器封装扩展为可直接运行 Lean 文件的 `run_lean_file()`。
- 新增 `leancapsule pack`，支持按定理名或行区间选择输入并生成完整文件 fallback capsule。
- 新增 `leancapsule replay`，编译 `Capsule.lean` 并比较编译状态、诊断类别和规范化 `diagnostic_key`。
- 新增 `leancapsule verify` 批量验收和 `leancapsule issue` Markdown 渲染。
- 保存 `capsule.json`、工具链与 Lake 配置、原始诊断、README、PowerShell/Unix 回放脚本。
- 增加 Std、Mathlib、project-local 三类来源的公开失败 gallery，共 24 个 capsule。
- 增加单次 Agent 的 API 配置参数和本地 HTTP `/solve` 接口；密钥只在内存中使用。
- CLI 会安全确认密钥长度和末四位，区分 provider 错误与 Lean 编译错误，并清洗模型及历史缓存中的 Markdown 代码围栏。
- README 提供中英文双版；Progress、其他现有中文指南及核心新增代码注释保持中文。
- 新增 theorem standalone 抽取：保留 imports、namespace 和目标定理，并在编译不一致时自动 fallback。
- 新增有界贪心 import 删除；每次删除都重新编译并比较诊断键。
- 增加 project-local fallback 示例、Mathlib v4.32.0 依赖工程和跨平台依赖准备脚本。
- 生成 `capsules/index.json`，四类 taxonomy 和三类来源均达到 gallery 覆盖门槛。
- 同步生成 `capsules/index.csv` 和 `capsules/index.md`，便于表格分析与 GitHub 浏览。
- 增加 `capsules/MANUAL_REVIEW.csv`，逐 capsule 登记自动回放与人工复核状态。
- 新增 `leancapsule audit` 发布审计，检查布局、许可、本机路径、敏感内容、成功证明和复核台账。
- 发布审计同时使用 `capsule_schema/leancapsule-v0.1.schema.json` 执行 Draft 2020-12 结构校验。
- 清理全部公开诊断中的本机绝对路径，补齐旧案例许可，并完成 24 个案例的仓库级逐项复核。
- 将 Mathlib 冷启动回放预算调整为 180 秒，并避免环境脚本重复获取已存在的预编译缓存。
- 修正 GitHub Actions 顺序：端到端测试依赖真实 Lean 编译器，现已在运行测试前安装 Lean，并增加顺序回归测试。
- GitHub runner 的端到端 Lean 编译采用独立 120 秒预算；测试失败详情会直接写入 Actions Summary。
- Provider 只允许同来源重定向，并在错误正文中隐藏密钥；Lean 子进程使用最小环境，不继承 API 密钥或其他令牌。
- 候选拒绝显式本机元编程/IO 构造，并将 `sorryAx`、未完成证明警告视为失败；保留局部定义、严格匹配完全限定定理和 `lakefile.lean` 项目。
- A/B/C 运行使用轮次感知缓存、`--fresh` 清理 SQLite 及旁车文件，并写入 `experiment_id`；报告禁止合并不同批次，未配置价格显示为“未配置”。
- Capsule 回放脚本支持跨目录执行；审计扫描发布根目录孤立文件、标准 `auth.json` 凭据和脱敏路径；PowerShell 脚本统一 UTF-8 BOM 并检查 Mathlib 命令退出码。
- 条件 C 会排除与评测命题完全相同的本地示例，避免把原题完整答案当作检索增益。
- 吸收 leiteng 分支的临时 HOME/TMP/APPDATA 隔离、候选安全策略、严格 pilot 校验、正式报告门禁和脱敏导出流程；导出清单只记录相对路径与文件大小，不执行摘要计算。
- `results/solutions/` 会按条件保存每个成功候选，`results/real_pilot_runs.jsonl` 保存逐轮原始轨迹；`evaluate.py --fresh` 会先归档旧实验，避免不同批次混合。
- 已合入 AxProverBase Part 1 Experience baseline 与 Part 2 `MemorylessProcessor + CapsuleFeedback`：冻结 Ax commit、`yxai` Responses 模型条件、预算、首轮候选和逐题遥测；Part 2 直接消费已有 Builder 结果，不重复调用 Lean 或模型。
- 已完成 FATE-M 25 题正式配对实验：两组均 25/25 成功，严格配对 25/25 通过；修正版总轮次 39→36、编译错误 14→11、LLM calls 79→36、tokens 656657→274742，正式结果与 SHA-256 清单位于 `results/handoff/part12-live-20260828-corrected/`；旧目录保留为历史工件。
- 新增独立 D01 安全回归：`unsafe inductive` 构造 `False` 的候选在 Agent、AxProverBase 缓存/Proposal/Builder、Capsule pack/replay/audit 的 Lean 编译前拒绝；D 类不是 A/B/C 的第四个实验条件。

## 当前验证状态

- `leancapsule verify capsules`：24/24 通过（Std 14、Mathlib 4、project-local 6）。
- `leancapsule gallery capsules --out capsules/index.json`：通过；四类 taxonomy 均不少于 3 个，三类来源均不少于 4 个。
- `leancapsule audit capsules`：24/24 通过，无发布审计错误。
- 完整 Python 测试共 129 项：127 项通过，2 项 Linux 符号链接边界检查在 Windows 跳过。Part 1/2 配置、完整 Proposal 配对、重跑状态隔离、CapsuleFeedback、Ax 接入、D01 编译前门禁、双语文档、gallery、provider 和 pilot 门禁均通过；PR 的 Ubuntu `lake build` 与完整 Python 回归已通过。
- 本次网络故障测试使用命令替身，不等于已完成真实冷启动下载或远程 CI 验收；修复仍在本地，推送后需查看新的 Actions 结果。
- 中英文 README 各 43 个本地链接、3 个页内锚点、13 个 PowerShell 兼容代码块和 2 个 Bash 代码块检查通过；公开实验工件链接通过 Git 中的已提交文件核验。
- Mathlib 回放在准备 `mathlib_project` 依赖缓存后通过；缓存目录不提交到仓库。

## 明确边界

- capsule gallery 验收的是失败复现协议，不等同于真实模型 A/B/C 实验；模型实验需另行配置 provider、冻结模型参数并记录 token、延迟和编译次数。
- 多文件依赖目前采用完整文件 fallback 与显式本地文件清单，不承诺任意项目的程序切片。
- `manual_review.csv` 的 54 条人工复核仍必须由研究者逐条填写；系统不会自动伪造 kernel_pass、假设合理性或泄漏风险结论。
- 本次代码迁移没有伪造真实 provider 轨迹；若 `results/real_pilot_runs.jsonl` 尚未由真实 provider 生成，严格校验和导出会明确拒绝，不能把 smoke/mock 记录冒充正式实验。
- 本地编译隔离是环境清理和候选策略防护，不等同于操作系统级沙箱；运行不受信任项目时仍应使用容器或独立低权限环境。
- Part 1/2 的 25 题结果是单模型、单批次运行证据，不能据此声称统计显著优势或通用定理证明能力；Part 3 仍需正式统计解释与更大规模重复实验。
