# 当前工作进度

更新时间：2026-08-28

补丁明细见 [CHANGELOG.md](CHANGELOG.md)；本文件只维护当前状态和剩余边界。

## 已完成

- 本轮已在最新 `origin/main@f6a684f` 基础上合并本地研究与 `tracer-proof-v2` 补丁，保留上游 AxProverBase Part 1/2、Responses、D01 和 CI。更新停留在 `runqi` 工作区，未提交/推送；未纳入尚未合入 main 的 stage3 分支。
- 合并前本地 64 份公开源码/文档均已备份，备份根目录为本次 Codex 工作目录下 `tracer-merge-backup-20260828-v2-complete`，含 base/remote/local/merged 与逐文件合并计划；所有原有补丁文件仍存在。两份上游交接包只清理派生元数据，原始运行/候选不变。
- 保留无派生摘要约束：诊断按可读全文比较，Ax 状态使用随机会话文件名及完整定理键，首轮 Proposal 直接逐字段配对。新旧状态格式隔离；DeepSeek 研究不继承终端的 Responses/推理配置。已修复 Responses 截断与空输出处理和 Windows 测试输出解码。
- 完成真实 DeepSeek 预跑审计：批次 research-80be2a1f-c253-4b1b-a3cc-b901e9d120b7，48 个 B 组任务、69 次请求；Flash 20/24、Pro 19/24，首轮均 18/24，39/39 成功文件独立复编译并检查公理依赖。保留原始旧协议成绩与未完成的人工复核表，详细观察见 docs/RESEARCH_PROTOCOL.md。
- 修订为 tracer-proof-v2：统一完整证明区域输出契约、冻结提示模板、单独标记截断（不自动增加额度）、修正 null content 解析、区分内核验证和普通警告，未完成证明与本机执行防护保持。协议写入计划、逐轮日志及可读缓存键，新报告拒绝混合口径；旧日志不改写。同步双语 README、API 指南和 JSONL 字段文档。
- 已完成本机 Windows 11 ↔ Ubuntu WSL2 的原生 Lean 4.32.0 配对回放：两端各 24 案例 × 2 次，48/48 匹配；合计 96/96。保留 Linux 首次缺少原文映射的 38 条预检记录，不混入完整比较。完整轨迹与 comparison.json 在 results/research-cross-os-20260828。
- 为 Linux 创建公开源码白名单副本，固定 Mathlib 依赖从本地公开 Git 源码复制并在 Linux 准备必要预编译模块，没有复制 Windows 构建产物。Lean/Mathlib 的外部工具链内部构建缓存留在独立研究目录，不作为 TRACER 发布内容；本项目未新增摘要或指纹实现。
- 新建 8 对合成人工研究材料，真实 pack 抽取且原文/精简版失败诊断一致；7 个参考修正通过编译，1 个假设不足案例不伪造证明。真人入口采用互补分组、开始后显示、定位/录入分时、放弃/超时记录、独立 AI/真人复核字段。2026-08-28 按用户要求将 results/research-human-20260828-155046 与 results/human-study-v1 移入回收站（可恢复），包括旧预演、新的未完成会话和汇总；研究材料与代码保留，人工计时研究暂停。
- 提供 DeepSeek Flash/Pro 48 任务预跑及 864 任务完整配置、隐藏内存密钥输入、显式思考参数、调用数与保守费用预留门禁，研究请求禁止自动重试。用户明确同意外发必要源码/上下文/候选/诊断后自行输入 Key 完成预跑；10 美元上限内保守预留 $2.32262492，usage 估算 $1.22602172，实际费用以平台账单为准。未读取历史 Key。
- 本轮收费前预检：60 秒预算下 stitch_assoc 出现工具链超时；统一提高预跑的编译预算至 180 秒后，24/24 输入得到有效初始编译失败。原题、输出上限及轮数未改，超时不计为数学失败。无凭据 GET /models 返回 401，证明服务可达但不验证用户密钥；没有进行模型生成。
- 迁移比较已完成，保留现有 TRACER：源码除两版 README 正文及换行差异外相同，但本地多出 246 个实验文件并保有 Git。未删除/替换目录；详细差异及发布目录读取限制见 docs/MIGRATION_COMPARISON.md。
- 新增冻结 repair24-v1：24 个带具体错误证明的修复任务，5 类主题；原有 18 题、真实 pilot 与成功证明保持不变。测试参考证明与运行路径隔离。
- 新增独立研究矩阵：A/B/C/D 因子实验、C_dynamic 动态查询、C_failure 失败上下文消融，多模型重复运行、随机任务序、禁止缓存、全文快照、独立重编译、配对描述统计及发布门禁。配置预览默认 864 任务/最多 2592 次生成，不调用 API。
- 检索按错误类别、标识符、类型与目标组织有界查询；修复声明重合过滤被覆盖的问题，使用完整可读声明比较，不引入摘要或指纹机制。
- 新增 Capsule 回放/源码缩减指标、跨环境记录合并、人工定位计时及待复核标记。失败上下文来自已公开 Capsule，不伪造模型轨迹。
- 更新双语 README，增加研究协议及 8 项相关工作（MathForm、APOLLO、Baldur、LeanDojo、LeanAgent、Lean Copilot、miniF2F、Delta Debugging）；不宣称首创反馈修复或已测得增益。
- 集成测试发现并修复路径脱敏将 HTTPS 的 s:// 误判为 Windows 路径的问题；修复原始 Mathlib 案例度量时未使用依赖项目的问题。
- 修复多文件 Capsule 的干净环境回放：按本地 Lean import 闭包复制源码与顶层库入口，在隔离环境中先执行限定的 `lake build` 目标再回放；不再依赖或打包本机生成的 `.olean` / `.ilean` 文件。
- 新增 12 core + 4 challenge 可行性实验。core 按 4 类错误 × 3 类上下文覆盖并作为硬门槛；当前 core 12/12、challenge 4/4、全部 16/16 均保持诊断键和完整有序规范化诊断，并在全新临时目录回放成功。
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
- 已完成 FATE-M 25 题正式配对实验：两组均 25/25 成功，严格配对 25/25 通过；修正版总轮次 39→36、编译错误 14→11、LLM calls 79→36、tokens 656657→274742，上游交接结果与可读文件清单位于 `results/handoff/part12-live-20260828-corrected/`；旧目录保留为历史工件。
- 新增独立 D01 安全回归：`unsafe inductive` 构造 `False` 的候选在 Agent、AxProverBase 缓存/Proposal/Builder、Capsule pack/replay/audit 的 Lean 编译前拒绝；D 类不是 A/B/C 的第四个实验条件。

## 当前验证状态

- `python scripts/run_capsule_feasibility.py`：core 硬门槛 12/12，challenge 干净回放 4/4，全部案例诊断键、完整有序规范化诊断和干净回放 16/16；core standalone/fallback 为 5/7，challenge 为 2/2。
- `leancapsule verify capsules`：24/24 通过（Std 14、Mathlib 4、project-local 6）。
- `leancapsule gallery capsules --out capsules/index.json`：通过；四类 taxonomy 均不少于 3 个，三类来源均不少于 4 个。
- `leancapsule audit capsules`：24/24 通过，无发布审计错误。
- 合并版全量回归 187 项：185 项通过，2 项 Windows 不适用的 Linux 符号链接测试跳过。含 15 项证明协议、8 项合并专项、Ax/Proposal/D01 与研究矩阵回归。`lake build` 本轮通过；18 题输入保留预期的 sorry 占位警告，不能将此构建当作完成证明。
- 新修复集：24 个初始候选失败，24 个测试参考证明通过；不联网六组矩阵完成候选生成替身→真实 Lean 编译→保存→独立重编译→报告验证。此测试数据不是模型实验结果。
- Windows 首次度量：24 案例 × 2 次，共 47/48 匹配；mathlib/elab-prime-instance 首次 60 秒超时，第二次通过。修正原文件 Mathlib 项目选择后，独立热缓存复测 24/24；23 对原始/精简源码诊断匹配，行数与字节缩减中位数均为 0。两批原始记录均保留于 results/research-capsule-windows-20260828 和 results/research-capsule-windows-warm-20260828。
- 新的 Windows/Linux 比较已取得两套不同 OS 的实际记录，均为同一物理机上的本地/WSL2 环境，非独立硬件或 macOS 验证。23 对原文诊断在两端均匹配，现有 gallery 的精简率中位数仍为 0。准备、缓存和背景进程未作严格性能控制，不从耗时差推导 OS 加速收益；人工计时暂停，多模型仅完成一次 B 组预跑。
- 本轮只读核对：DeepSeek 原批次 48 任务、69 请求、39 成功文件，轨迹校验 0 错误；上游 corrected FATE-M 首轮严格配对 25/25。上游曾完成的 Ubuntu CI 属于历史版本，本地合并补丁尚未推送，不能据此声称新的远程 CI 已通过。
- Capsule 专项验证覆盖多文件依赖预构建、12 core + 4 challenge 矩阵、CI 硬门槛及 Bash 重试变量边界；合并后的当前测试结果以本节记录和最新 CI 为准，不沿用合并前的固定测试总数。
- 本次网络故障测试使用命令替身，不等于已完成真实冷启动下载或远程 CI 验收；修复仍在本地，推送后需查看新的 Actions 结果。
- 双语文档回归检查覆盖语言导航、运行命令一致性、旧 pilot 数字与证据链接、研究协议及相关工作入口；不再把新增章节数量写死。
- Mathlib 回放在准备 `mathlib_project` 依赖缓存后通过；缓存目录不提交到仓库。

## 明确边界

- capsule gallery 验收的是失败复现协议，不等同于真实模型 A/B/C 实验；模型实验需另行配置 provider、冻结模型参数并记录 token、延迟和编译次数。
- 多文件依赖目前按可解析的本地 Lean import 闭包与顶层 Lake 构建目标打包，仍不承诺任意 Lake 项目的程序切片、非 Lean 构建步骤或动态依赖都可自动迁移。
- 已有 54 任务 pilot 及其人工复核不改写；新矩阵的人工复核表必须另行逐题填写，不能将旧复核转移为新实验验收。
- 预跑已由用户在本地完成；本次 v2 修复没有新增 API 调用、没有改写原始结果、没有提交或推送。864 任务仍只是计划；没有跨 OS 性能收益、反馈/检索增益、失败复用收益或人工时间节省证据。下一批需独立目录与重新确认预算，不自动续用本次余额；修订发生在观察预跑之后，不能冒充原批次预注册设计。
- `manual_review.csv` 的 54 条人工复核仍必须由研究者逐条填写；系统不会自动伪造 kernel_pass、假设合理性或泄漏风险结论。
- 本次代码迁移没有伪造真实 provider 轨迹；若 `results/real_pilot_runs.jsonl` 尚未由真实 provider 生成，严格校验和导出会明确拒绝，不能把 smoke/mock 记录冒充正式实验。
- 本地编译隔离是环境清理和候选策略防护，不等同于操作系统级沙箱；运行不受信任项目时仍应使用容器或独立低权限环境。
- Part 1/2 的 25 题结果是单模型、单批次运行证据，不能据此声称统计显著优势或通用定理证明能力；Part 3 仍需正式统计解释与更大规模重复实验。
- 新增 Part 3 交接清单与轻量校验入口：`docs/part3_experiment_handoff.md`、`scripts/validate_part3_handoff.py` 和 `.github/workflows/part3.yml` 只检查 corrected handoff 的配对协议和公开数字，不调用模型 API。
