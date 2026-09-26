# TRACER 当前进度与证据登记

更新时间：2026-09-26。

本文登记 repair24 正式六臂结果、SP v2、LeanCapsule 与 TRACER-REAL v2 筛查证据，是仓库内“完成到哪一步”的唯一当前口径。被取代但仍可复核的发布包、交接材料和报告集中在 [`historical/`](historical/README.md)；历史变更过程见 `CHANGELOG.md`，未来工作见 `docs/FUTURE_WORK_PLAN.md`。当旧报告与本文冲突时，以各批次原始工件和本文的证据分层为准。

## 口径规则

每项工作只归入以下一种状态：

1. **已发布证据**：当前仓库同时包含协议、原始或脱敏轨迹、结果文件及所需复核，可以独立检查。
2. **可复验实现**：代码、冻结输入和离线门禁已存在，但还没有足够的正式模型或真人结果。
3. **历史说明**：文档记录曾在本地运行，但当前仓库缺少原始工件，不能作为发布结论。
4. **未来计划**：只有研究设计或路线图，不得写成已实现能力或实验结果。

“测试通过”只说明对应软件门禁通过，不等于研究假设成立；“Lean 编译通过”“人工复核通过”“发布审计通过”也是彼此独立的证据。

## 已发布证据

| 编号 | 工件 | 当前证据 | 可以支持的结论 | 不能支持的结论 |
| --- | --- | --- | --- | --- |
| E-02 | LeanCapsule gallery | `capsules/`：24 个公开案例，Std 14、Mathlib 4、project-local 6，含元数据、许可、索引和复核台账 | 固定工具链下可以保存并复现这些失败 | 能自动封装任意 Lake 项目；完整安全沙箱 |
| E-03 | Capsule feasibility | `results/capsule_feasibility/` 与 `results/capsule_challenges/`：12/12 core、4/4 challenge 回放成功 | 所选合成矩阵中编译状态、错误类别和规范化诊断可以保持 | 普遍的最小化能力；真实项目上的时间收益 |
| E-07 | SP v2 安全回归 | `published/security-study-tracer-sp-v2/`：SP-1～SP-12、CTRL-1～CTRL-8、检测器核对、正常对照真编译和双向错误区间；SP-1 另有 Agent、Ax、Capsule 跨入口回归 | 12 个冻结危险案例均在编译前拒绝，8 个正常对照均放行并由 Lean 编译通过 | 系统已形成完整沙箱、未知攻击已覆盖，或观察到 0 次错误等于零风险 |
| E-10 | repair24 正式六臂实验 | `published/research-six-arm-313f437f/`：864 个任务、1,066 条脱敏逐轮记录、811 个成功证明、864 行复核记录与机器可读 AI 辅助复核报告 | 同一模型族、24 题、三重复下 R-A～R-F 的描述性配对结果、动态检索变化和完整证据链可复查 | 编译反馈必然增益、R-E/R-F 稳定胜出、统计显著性、跨供应商泛化、纯人工复核或 SOTA |
| E-11 | SP 单平台操作系统隔离证据 | `published/security-isolation-tracer-sp-v1/`：GitHub-hosted Ubuntu Docker Engine 报告、14/14 项冻结控制、手动 Actions 运行来源与发布审计 | 在该次 Linux 运行中观察到非 root、只读根/工作区、禁网、零 effective capabilities、`no-new-privileges`、seccomp、资源限制和 noexec 临时目录 | 双平台一致、完整沙箱、未知逃逸不存在、恶意依赖安全或任意 Lean 元程序安全；Windows Docker Desktop 尚未实测 |

## 历史已发布证据（已归档）

以下工件完整保留，但已经退出当前首页、`published/` 和主线 CI。统一索引见 [`historical/README.md`](historical/README.md)。

| 编号 | 工件 | 归档位置 | 边界 |
| --- | --- | --- | --- |
| E-01 | Evaluation18 真实 provider smoke pilot | `historical/evaluation18_pilot/` | 工程链路证据，不支持反馈或检索增益 |
| E-04～E-06 | FATE-M Part 1–3 | `historical/fate_m/` | 单批次描述性结果，不与 repair24 合并 |
| E-08～E-09 | Feedback Study v1 与第二模型复现 | `historical/feedback_study_v1/` | 同供应商模型族辅助证据，不是当前主结果 |

## 可复验实现，但尚未完成研究验收

| 编号 | 已有实现 | 仍缺什么 |
| --- | --- | --- |
| I-04 | `src/capsule_metrics.py` 和跨环境记录合并 | 独立机器、受控冷热缓存和仓库内可交付原始轨迹 |
| I-05 | `src/human_study.py`、8 对合成材料和互补分组 | 真实参与者回答、计时、知情说明和人工判分 |
| I-06 | [Compiler Feedback v1](docs/COMPILER_FEEDBACK_V1.md) 与 [Feedback Adoption v1](docs/FEEDBACK_ADOPTION_V1.md)：三层诊断、原文证据、错误转移、候选相关修改、缓存状态及动态 query/Top-k 变化；早期 Pro/Flash 结果已归档 | 独立供应商模型复现与按题聚合的不确定性分析，才能讨论更广跨模型效应或更强比较结论 |
| I-07 | 最小环境、版本化 SP v2 威胁模型、SP-1～SP-12、CTRL-1～CTRL-8、检测器核对和 Wilson 双向错误区间 | 未知攻击评估、外部安全复核；文本策略本身仍不是操作系统沙箱 |
| I-08 | `tracer-sp-isolation-v1`：Docker 非 root、只读根与仓库、noexec 临时目录、禁网、清空 capabilities、`no-new-privileges`、seccomp、内存/CPU/PID/墙钟限制，共 14 项 fail-closed 探针；Linux 实测见 E-11 | Windows Docker Desktop 尚无真实运行报告；未知容器逃逸与恶意依赖不在已验证范围 |
| I-09 | `tracer-causal-feedback-v1`：冻结无反馈首轮候选后分叉到空反馈、三种真实反馈、同类无关反馈、反事实反馈、只检索和 adaptive；负对照禁止自配对，所有分支保留同一首轮候选；TRACER-REAL 试点已冻结机器可读预注册 | provider 批次与结果审计尚待完成；单 test 项目且最多 12 个合格失败，预注册明确禁止正式统计或跨项目因果结论 |
| I-10 | Error-State Graph、确定性 Adaptive Router 与 TRACER-REAL v1：结构化信号保留原始证据边；Mathlib 3、Batteries 4、Aesop 4 共 11 题按 development/validation/test 上游项目互斥划分，均经旧证明失败与修复证明通过门禁，参考证明单独存放 | 当前 Router 尚未学习；11 题/3 项目仍是试点，确认性结论门禁要求至少 5 个 test 项目与 30 个合格首轮失败 |
| I-11 | [TRACER-REAL v2](docs/TRACER_REAL_V2.md) 的六个候选上游、端点和 120 提交窗口在扫描前冻结；1,576 个候选全部筛查，公开 256 个通过、1,320 个拒绝的完整决定账本。SciLean 2/54 低于项目门槛，最终 test 划分为五个独立项目、254 题。原 35% 占比门禁被 PhysLean 94/254≈37.0% 触发；provider 前公开修订为 40%，其他门槛与全部合格题保持不变。最终 265 题 manifest 与运行时预注册已生成并通过审计，`ready_for_provider_run` 为 true | 尚未运行 v2 provider，因此没有 v2 成功率、反馈因果效应、成本或统计结论；40% 是公开修订后的工程门槛，报告必须同时披露原 35% 阈值与修订理由 |
| I-12 | [ACL 2027 因果实验](docs/ACL2027_EXPERIMENT_PROTOCOL.md)：冻结 DeepSeek/GLM 八臂与 MiniMax 三臂的嵌套设计；三个独立模型家族与一方 API 来源、精确运行参数、同首轮候选、反事实负对照、项目等权主分析和两份运行时预注册已固化。离线审计确认 5 个 test 项目、254 题、6 类错误、检索声明重合 0，最大调用上限 16,764；正式脚本提供独立批次目录、严格断点续跑、完成批次审计跳过和失败工件保留 | 三 provider 的合成预检已由操作者运行，但正式付费批次及其仓库内发布证据尚不存在；不得把连接预检、配置、预注册或上限数字表述为模型结果 |

repair24 的不联网测试可以证明 runner 会执行“候选→Lean 编译→保存→独立复编译→报告校验”，但 mock 或参考候选不得计作模型实验结果。

### E-10 的数值与发布边界

正式批次 `research-313f437f-70cf-49ad-82ea-6fed676c2602` 完成 24 题 × 2 模型配置 × 3 重复 × 6 臂的 864/864 任务，基础设施错误为 0。Flash 的 R-A～R-F 三轮内成功数依次为 69、69、69、68、70、70；Pro 依次为 67、65、67、65、67、65。预注册主比较 R-B−R-A 对 Flash 为 0/72，对 Pro 为 −2/72；不能据此声称编译反馈产生稳定正增益。动态检索的查询变化率在 R-E/R-F 中非零，但最高成功数只出现在 Flash，未在 Pro 复现。

本批共有 811 个成功证明、53 个失败任务和 1,066 条有效逐轮记录，记录 5,116,954 tokens；按冻结价格字段估算约 13.39 美元，但该数值不是供应商账单。811 个证明均通过运行期独立编译、AI 辅助复核和发布包独立复编译；27 个证明仅有非致命 linter 风格警告。运行期报告 5 次归档重试，发布扫描实测 6 个归档尝试目录和 10 条失败轮次，另有 1 次调用预留没有对应轮次；两套计数均公开保留。题库只有 24 道独立题，重复与实验臂不能扩充为 864 道独立样本；当前结果也不构成因果、显著性、跨供应商或 SOTA 结论。

## 仅有历史说明、当前仓库不能独立核验

- 2026-08-28 的 DeepSeek Flash/Pro R-B 预跑曾记录 48 个任务、69 次请求和 39 个成功证明；当前仓库不包含对应原始轨迹、成功证明目录和研究复核表，因此不作为发布结果，也不能用于模型排名。
- Windows 11 与 Ubuntu WSL2 的 24 案例双次回放曾有本地记录；当前仓库不包含两端完整原始记录。即使复现，也只能说明同一物理机上的跨 OS 行为，不能说明独立硬件或性能收益。
- 当前仓库没有真人参与者的有效回答、诊断计时或完成的研究复核结果。人工研究入口存在不等于人工研究已完成。

缺失工件不得通过汇总数字、旧截图或重新生成的 mock 数据补造。

## 当前工程验收状态

当前分支保留 TRACER-REAL v2 筛查证据，并完成 repair24 正式六臂预注册、付费批次、AI 辅助复核、脱敏导出和发布审计。实验结果只按 E-10 的边界解释，不把配置、预注册或重复数单独当作模型能力证据。

当前文档基线的本地 Windows 全量复审记录：

- Python：共发现 363 项测试，361 项通过，2 项因仅在 Linux 验证符号链接边界而跳过。在既有 Compiler Feedback、TRACER-REAL、Feedback Study、Capsule 与 SP 门禁上，新增 ACL 2027 的 DeepSeek/GLM/MiniMax 三模型嵌套协议、三臂/八臂预注册、三一方来源审计、检索泄漏门禁、隐藏密钥合成预检，以及正式入口的独立输出、显式预算、严格续跑、完成批次跳过和失败工件保留合同；同时继续覆盖隔离发布包、AI 辅助复核、脱敏发布合同、README 结果图与正式 `summary.json` 的逐柱一致性、v2 公开筛查账本、双语 README 计数一致性和交互 Demo 的 24 组公开验证修复。
- `python demo/serve.py`：零依赖静态网页在本机完成桌面端视觉与交互验收；两轮真实脱敏轨迹、中英文切换和本地真实编译命令均可用。网页不调用 provider，不能把回放视为一次新的模型生成。
- `lake build`：通过；冻结 Evaluation18 输入中的 18 个 `sorry` 是预期占位警告，不代表题目已在原文件中修复。
- `python -m leancapsule audit capsules`：24/24 通过。
- `python -m leancapsule verify capsules`：24/24 通过，包含 4 个 Mathlib 案例。
- `python scripts/run_capsule_feasibility.py --verify-only`：12 个 core 与 4 个 challenge 全部通过。
- `python scripts/verify_compiler_feedback_v1.py --verify-only`：15/15 通过，其中 12 个真实 Lean 失败、3 个基础设施事件；API 调用为 0，未改写已有实验。
- `python src/research.py plan --config experiments/research.deepseek.six_arm_20260920.json --benchmark benchmarks/repair24/manifest.json --preregistration experiments/preregistrations/repair24_six_arm_deepseek_20260920.json`：离线核对 2 模型 × 3 重复 × 6 臂 × 24 题 = 864 任务、2,592 次最大生成，网络调用为 0；这不是模型结果。
- `python src/security_study.py --check published/security-study-tracer-sp-v2/report.json`：SP-1～SP-12 误放行 0/12、CTRL-1～CTRL-8 策略误拒绝 0/8、正常对照 Lean 编译失败 0/8、拒绝前编译 0/12、检测器不一致 0/12；Wilson 95% 上界约为 24.3% 与 32.4%，只适用于当前案例集。
- `python src/security_isolation.py plan`：离线核对 `tracer-sp-isolation-v1` 的 14 项容器控制，网络调用为 0。
- `python scripts/audit_security_isolation_release.py published/security-isolation-tracer-sp-v1`：GitHub-hosted Ubuntu Docker Engine 报告通过发布审计，14/14 项冻结控制为 true，危险 Lean 夹具未执行；证据状态为 `single_platform_observed`，Windows Docker Desktop 仍待完成。
- `python scripts/audit_research_release.py published/research-six-arm-313f437f --compile-solutions`：六臂发布包的 864 任务、1,066 条有效轮次、864 行复核和 811 个公开证明一一对应；811/811 独立复编译通过。
- `python src/tracer_real_v2.py audit --benchmark benchmarks/real_repairs/tracer_real_v2/manifest.json`：六个项目的 1,576 个候选、256 个纳入与 1,320 个拒绝均与公开决定账本一致；最终 8 项目/265 题 manifest 与运行时预注册一致，provider 门禁可开启但尚未发生 v2 调用。
- `python src/tracer_real_v2_assembly.py status`：五个合格 test 项目共 254 题，全部公开子集均已构建并验证；PhysLean 94/254≈37.0% 低于公开修订后的 40% 有效上限，最终 spec 已冻结。
- `python src/acl2027.py audit`：ACL 嵌套协议的 5 个 test 项目、254 题、6 类错误、3 个独立模型家族/API 来源、两份运行时预注册与 0 条检索声明重合通过纯离线审计；网络调用为 0。

这些结果是软件与工件验收，不自动转化为反馈增益、安全完备性或通用证明能力结论。

## 命名体系

| 层级 | 名称 | 用途 |
| --- | --- | --- |
| 发布 smoke pilot | P-A、P-B、P-C | 对应历史存储值 A/B/C |
| repair24 研究臂 | R-A～R-F | 对应存储值 `A/B/C/D/C_dynamic/C_failure` |
| 安全策略 | SP-1～SP-12，后续继续 SP-n | 非实验臂；SP-1 有既有跨入口回归，完整 v2 套件含 12 个危险案例与 8 个正常对照 |
| FATE-M 拆分条件 | 使用完整处理器组合名称 | 不再简称为新的 A/B/C/D 组 |

历史 JSON 的存储值保持不变，避免破坏已有工件；新文档与图表使用公开显示名。

## 下一阶段

优先顺序见 `docs/FUTURE_WORK_PLAN.md`：

1. **已完成离线第一阶段：** 冻结 Compiler Feedback v1 原始、规范化、结构化三层表示和 15 个失败夹具。
2. **已完成首批真实测量：** 六臂发布包已记录反馈采纳、重复错误、候选相关修改和动态 query/Top-k 变化；下一步应在独立供应商和更难的项目级题库上预注册复现，而不是把当前描述性差异写成因果收益。
3. **已完成 SP v2 离线实现：** SP-1～SP-12、8 个正常对照、检测器核对、正常对照真编译及 Wilson 双向错误区间；这不是完整安全结论。
4. **已完成第二模型模型族内复现：** DeepSeek Flash 的 216 任务、209 个证明、AI 辅助复核、脱敏发布包与 Pro/Flash 配对报告均已通过门禁；尚无独立供应商模型复现。
5. **隔离原型与 Linux 首次实测已完成：** 已冻结 14 项 Docker/低权限控制，GitHub-hosted Ubuntu Docker Engine 报告 14/14 通过并完成脱敏发布审计；下一步补齐 Windows Docker Desktop 报告，不把单平台结果称为完整沙箱或双平台隔离通过。
6. **已完成公开导出：** raw/normalized/structured DeepSeek 批次已脱敏发布；保留 AI 辅助复核标识，未上传逐请求完整 prompts、历史归档原文或认证字段。
7. 真人计时与独立机器跨环境研究单独立项，不与模型结果混算。
8. **TRACER-REAL v2 已完成离线冻结，下一步是严格按预注册运行：** 六个上游共 1,576 个候选均已处理，256 条通过、1,320 条拒绝。SciLean 低于项目门槛，五个 test 项目共 254 题。PhysLean 的 37.0% 占比触发原 35% 门禁后，项目在 provider 调用前公开修订为 40%，没有删题、换题或改变其他门槛；最终 manifest 和运行时预注册已冻结。下一步不得再更换题库、模型、提示、分支或分析方法，只能按冻结对象运行并发布完整证据链。

新结果只有在包含冻结配置、原始轨迹、成功证明、独立重编译、明确标注的复核模式和发布审计后，才能从“可复验实现”升级为“已发布证据”。AI 辅助复核不能表述为纯人工复核。
