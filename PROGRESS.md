# 当前工作进度

更新时间：2026-08-27

## 已完成

- 将 TRACER 的编译器封装扩展为可直接运行 Lean 文件的 `run_lean_file()`。
- 新增 `leancapsule pack`，支持按定理名或行区间选择输入并生成完整文件 fallback capsule。
- 新增 `leancapsule replay`，编译 `Capsule.lean` 并比较编译状态、诊断类别和规范化 `diagnostic_key`。
- 新增 `leancapsule verify` 批量验收和 `leancapsule issue` Markdown 渲染。
- 保存 `capsule.json`、工具链与 Lake 配置、原始诊断、README、PowerShell/Unix 回放脚本。
- 增加 Std、Mathlib、project-local 三类来源的公开失败 gallery，共 24 个 capsule。
- 增加单次 Agent 的 API 配置参数和本地 HTTP `/solve` 接口；密钥只在内存中使用。
- CLI 只确认密钥已读取，不显示长度、末四位或字符信息；provider 错误与 Lean 编译错误分开记录，敏感内容会在日志、元数据和异常中脱敏。
- README、Progress、核心新增代码注释统一使用中文。
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
- 正式 `run_all.ps1` 固定实验参数并请求严格 fresh 运行；旧状态由评测入口归档，复用缓存必须显式选择。
- PowerShell 入口保持 ASCII，检查每个原生命令退出码；Mathlib 脚本在 Windows 和 Unix 上设置稳定缓存目录。
- 新增 54 任务完整性、人工复核门禁与脱敏交接工具；原始路径、请求缓存和未复核草稿不会自动进入 Git。
- 正式报告按单一 `experiment_id`/题目 `run_id` 校验，要求 A/B/C 全覆盖、单一非空 provider 配置、连续轮次和严格 fresh；未知价格保持 `unknown`，不再显示为零成本。
- 同一次求解不会把失败候选从缓存中重复用于后续轮次；候选及成功工件同时拒绝 `sorry`、`sorryAx` 和 `admit`。
- 定理定位拒绝不带命名空间的重名目标，限定名不再回退到同名定理；隔离编译保留有效本地 helper，并识别 `lakefile.lean` 项目。
- 交接导出要求匹配当前实验的正式报告和每个成功证明工件，使用临时目录原子生成，并扫描常见认证 token。
- CI 增加 Windows PowerShell 5.1 语法检查和脚本/文档静态回归。
- 远程 provider 强制 HTTPS，只允许同源认证重定向，并限制成功响应和错误正文大小；非 JSON 错误正文不会写入日志。
- 模型候选使用最小化子进程环境，阻止 `run_tac`、`run_term_elab`、`#eval` 等编译期执行入口，并把候选策略写入实验记录与正式报告。
- 新增独立 D 类安全对抗回归；D01 覆盖 `unsafe inductive` 绕过 positivity 检查并构造 `False`，候选策略升级为 `tracer-candidate-v2`，原 Agent、AxProverBase 缓存/生成 ProposalMessage 与 Capsule pack/replay/audit 均在编译前拒绝不安全声明。
- 条件 C 在调用 provider 前检查检索语料与目标声明重合；示例库中的 8 项直接答案重合已替换为相关但不同的证明示例。
- 新增 Part 2 `CapsuleFeedback` 核心接口：直接消费 AxProverBase 已有编译结果，不重复编译、不调用 LLM，并输出稳定指纹、重复次数、诊断漂移和有界历史。
- 新增 `leancapsule feedback` JSON CLI、逐题状态恢复、Ax 框线诊断兼容和敏感 token 脱敏；冻结 AxProverBase commit 与 DeepSeek Flash 跨 Part 1/2/3 模型契约。
- 新增 Part 2 独立 GitHub Actions workflow：支持 `leiteng` push、Pull Request 和默认分支手动触发，在 Ubuntu 跑专项测试，再执行 Lean build 与完整 Python 回归；不读取模型密钥。
- Part 2 已增加真实 AxProverBase 包裹入口：复用原 Builder 返回值并转换成 Ax `BuildFailedFeedback`，按 theorem 隔离状态，强制 Memoryless、关闭 summary，并记录有界 JSONL 遥测。
- Part 1 Experience 与 Part 2 Capsule 均提供提交内 DeepSeek Flash 配置；新增严格配对门禁，检查共享首轮候选、模型、endpoint、预算及 Capsule 零额外调用。
- 固定 AxProverBase commit 现在由独立 Ubuntu job 拉取、静态校验、安装并执行真实消息类型 smoke；本地普通测试仍不需要安装 Ax。

## 当前验证状态

- `leancapsule verify capsules`：24/24 通过（Std 14、Mathlib 4、project-local 6）。
- `leancapsule gallery capsules --out capsules/index.json`：通过；四类 taxonomy 均不少于 3 个，三类来源均不少于 4 个。
- `leancapsule audit capsules`：24/24 通过，无发布审计错误。
- 完整 Python 测试 123/123 通过，包含 Part 2 有界状态、状态版本、逐 theorem 隔离、真实 Ax 消息桥接、首轮候选注入、零重复编译、Memoryless/DeepSeek 配置、D 类危险证明门禁、遥测、配对门禁、workflow 契约和脱敏回归，以及既有 Agent、provider、gallery、正式报告与复核账本检查；`lake build` 通过。
- 固定 AxProverBase commit 已在隔离环境完成真实 Python 类型 smoke：仓库 YAML 可解析，真实 `LLMClient` 接受 DeepSeek endpoint/profile，补丁可安装到 `ProverAgent`；全过程未调用模型或 Lean。
- Mathlib 回放在准备 `mathlib_project` 依赖缓存后通过；缓存目录不提交到仓库。

## 明确边界

- capsule gallery 验收的是失败复现协议，不等同于真实模型 A/B/C 实验；模型实验需另行配置 provider、冻结模型参数并记录 token、延迟和编译次数。
- 多文件依赖目前采用完整文件 fallback 与显式本地文件清单，不承诺任意项目的程序切片。
- 当前已覆盖 provider 的协议、重定向、响应边界和日志脱敏，也为候选编译提供静态元编程阻断与最小化环境；这仍不是通用操作系统级沙箱。项目源码、imports、依赖及自定义 tactic 必须被视为可信输入，不应在本机运行任意不受信任 Lean 项目。
- 现有 TRACER A/B/C pilot 已完成正式复核；它与待运行的 AxProverBase Experience baseline / CapsuleFeedback 配对实验是两套实验，不能互相替代。
- Part 2 接线基础设施已完成；尚未产生的只是依赖 Part 1 首轮候选和真实 API 的配对实验数据。拿到两组 JSONL 后必须通过 `scripts/validate_part2_pairing.py`，才能进入 Part 3 正式比较。
