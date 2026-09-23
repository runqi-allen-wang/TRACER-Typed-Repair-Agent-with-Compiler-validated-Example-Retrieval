# TRACER 当前进度与证据登记

更新时间：2026-09-21。

本分支在当前 `main` 基线上登记 repair24 正式六臂结果和 TRACER-REAL v2 筛查证据。本文是仓库内“完成到哪一步”的唯一当前口径；历史变更过程见 `CHANGELOG.md`，未来工作见 `docs/FUTURE_WORK_PLAN.md`。当旧报告、历史批次说明与本文冲突时，以各批次原始工件和本文的证据分层为准。

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
| E-01 | Evaluation18 真实 provider pilot | `published/pilot-20260826T122354Z-d628742d/`：18 题 × P-A/P-B/P-C，56 条逐轮记录，54 个成功证明，54/54 人工复核完整，缓存命中 0 | provider、Lean 编译、保存、复核与脱敏导出链路可运行 | 反馈或检索提高成功率；通用证明能力；模型排名 |
| E-02 | LeanCapsule gallery | `capsules/`：24 个公开案例，Std 14、Mathlib 4、project-local 6，含元数据、许可、索引和复核台账 | 固定工具链下可以保存并复现这些失败 | 能自动封装任意 Lake 项目；完整安全沙箱 |
| E-03 | Capsule feasibility | `results/capsule_feasibility/` 与 `results/capsule_challenges/`：12/12 core、4/4 challenge 回放成功 | 所选合成矩阵中编译状态、错误类别和规范化诊断可以保持 | 普遍的最小化能力；真实项目上的时间收益 |
| E-04 | FATE-M Part 1/2 corrected | `results/handoff/part12-live-20260828-corrected/`：25/25 严格配对，两组均 25/25；轮次 39→36，编译错误 14→11，LLM 调用 79→36，token 656,657→274,742 | 该单批次交接工件和逐题配对关系成立 | 单独归因于 CapsuleFeedback；统计显著优势 |
| E-05 | Experience + CapsuleFeedback 拆分臂 | `results/handoff/part2-experience-capsule-20260829/`：20/25，47 轮，69 次 LLM 请求，659,791 token；严格配对 25/25 | 该配置在单批次中的描述性结果 | 它优于其他条件；可外推到 repair24 或其他模型 |
| E-06 | Part 3 Raw/Capsule | `results/handoff/part3-after-main-90ba62b-20260829/`：25/25 配对，Raw 22/25、Capsule 19/25 | 该交错批次的结果与配对门禁可复查 | Capsule 带来增益；跨模型或跨数据集结论 |
| E-07 | SP v2 安全回归 | `published/security-study-tracer-sp-v2/`：SP-1～SP-12、CTRL-1～CTRL-8、检测器核对、正常对照真编译和双向错误区间；SP-1 另有 Agent、Ax、Capsule 跨入口回归 | 12 个冻结危险案例均在编译前拒绝，8 个正常对照均放行并由 Lean 编译通过 | 系统已形成完整沙箱、未知攻击已覆盖，或观察到 0 次错误等于零风险 |
| E-08 | Feedback Study v1 DeepSeek 批次 | `published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248/`：216 个任务、283 条脱敏逐轮记录、199 个成功证明、216 行 AI 辅助复核和可读文件清单 | 当前模型、24 题、三重复下三种反馈表示的描述性结果及完整证据链可复查 | 统计显著性、因果增益、跨模型泛化或纯人工复核 |
| E-09 | Feedback Study v1 第二模型复现 | `published/feedback-study-562ad440-3446-4138-801e-59726ed0e108/`：DeepSeek Flash 的 216 个任务、245 条脱敏逐轮记录、209 个成功证明与 216 行 AI 辅助复核；`published/feedback-cross-model-8ccb89dd-562ad440/`：与 Pro 基线的完整任务配对 | 同供应商 Pro/Flash 两模型在冻结题库与公共预算下的描述性结局一致性可复查 | 跨供应商泛化、模型等价、统计显著性或反馈表示的因果收益 |
| E-10 | repair24 正式六臂实验 | `published/research-six-arm-313f437f/`：864 个任务、1,066 条脱敏逐轮记录、811 个成功证明、864 行复核记录与机器可读 AI 辅助复核报告 | 同一模型族、24 题、三重复下 R-A～R-F 的描述性配对结果、动态检索变化和完整证据链可复查 | 编译反馈必然增益、R-E/R-F 稳定胜出、统计显著性、跨供应商泛化、纯人工复核或 SOTA |

### E-01 的数值解释

发布 pilot 的 pass@1 为 P-A 18/18、P-B 16/18、P-C 18/18；三组 pass@3 均为 18/18。P-A 首轮已经达到满分，存在明显天花板效应，因此这批结果是工程 smoke test，不是反馈或检索增益实验。P-C 的平均 token 更高，也不能据此声称更高效。

根目录 `results/manual_review.csv` 和发布目录内的复核表均有 54 行，四个复核字段无空值。正式可移交版本始终以 `published/pilot-20260826T122354Z-d628742d/` 为准。

## 可复验实现，但尚未完成研究验收

| 编号 | 已有实现 | 仍缺什么 |
| --- | --- | --- |
| I-04 | `src/capsule_metrics.py` 和跨环境记录合并 | 独立机器、受控冷热缓存和仓库内可交付原始轨迹 |
| I-05 | `src/human_study.py`、8 对合成材料和互补分组 | 真实参与者回答、计时、知情说明和人工判分 |
| I-06 | [Compiler Feedback v1](docs/COMPILER_FEEDBACK_V1.md) 与 [Feedback Adoption v1](docs/FEEDBACK_ADOPTION_V1.md)：三层诊断、原文证据、错误转移、候选相关修改、缓存状态及动态 query/Top-k 变化；Pro/Flash 模型族内结果已作为 E-08/E-09 发布 | 独立供应商模型复现与按题聚合的不确定性分析，才能讨论更广跨模型效应或更强比较结论 |
| I-07 | 最小环境、版本化 SP v2 威胁模型、SP-1～SP-12、CTRL-1～CTRL-8、检测器核对和 Wilson 双向错误区间 | 未知攻击评估、外部安全复核；文本策略本身仍不是操作系统沙箱 |
| I-08 | `tracer-sp-isolation-v1`：Docker 非 root、只读根与仓库、noexec 临时目录、禁网、清空 capabilities、`no-new-privileges`、seccomp、内存/CPU/PID/墙钟限制，共 14 项 fail-closed 探针；含手动 Actions 工作流 | 当前机器没有 Docker，尚无 Windows Docker Desktop 或原生 Linux 的真实运行报告；未知容器逃逸与恶意依赖不在已验证范围 |
| I-09 | `tracer-causal-feedback-v1`：冻结无反馈首轮候选后分叉到空反馈、三种真实反馈、同类无关反馈、反事实反馈、只检索和 adaptive；负对照禁止自配对，所有分支保留同一首轮候选；TRACER-REAL 试点已冻结机器可读预注册 | provider 批次与结果审计尚待完成；单 test 项目且最多 12 个合格失败，预注册明确禁止正式统计或跨项目因果结论 |
| I-10 | Error-State Graph、确定性 Adaptive Router 与 TRACER-REAL v1：结构化信号保留原始证据边；Mathlib 3、Batteries 4、Aesop 4 共 11 题按 development/validation/test 上游项目互斥划分，均经旧证明失败与修复证明通过门禁，参考证明单独存放 | 当前 Router 尚未学习；11 题/3 项目仍是试点，确认性结论门禁要求至少 5 个 test 项目与 30 个合格首轮失败 |
| I-11 | [TRACER-REAL v2](docs/TRACER_REAL_V2.md) 的六个候选上游、端点和 120 提交窗口在扫描前冻结；1,576 个候选全部筛查，公开 256 个通过、1,320 个拒绝的完整决定账本。SciLean 2/54 低于项目门槛，最终 test 划分为五个独立项目、254 题。原 35% 占比门禁被 PhysLean 94/254≈37.0% 触发；provider 前公开修订为 40%，其他门槛与全部合格题保持不变。最终 265 题 manifest 与运行时预注册已生成并通过审计，`ready_for_provider_run` 为 true | 尚未运行 v2 provider，因此没有 v2 成功率、反馈因果效应、成本或统计结论；40% 是公开修订后的工程门槛，报告必须同时披露原 35% 阈值与修订理由 |

repair24 的不联网测试可以证明 runner 会执行“候选→Lean 编译→保存→独立复编译→报告校验”，但 mock 或参考候选不得计作模型实验结果。

### E-08 的数值与发布边界

`feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248` 使用 DeepSeek、repair24、raw/normalized/structured 三种表示和三次重复，共 216 个任务。Raw、Normalized、Structured 的三轮内成功数分别为 67/72、65/72、67/72；首轮成功数分别为 56/72、56/72、60/72。199 个成功证明均再次独立编译通过，并完成明确标注的 AI 辅助复核。公开包保存 283 条有效逐轮记录；预算账本共有 286 次调用预留，另披露 2 条归档传输失败轮次和 1 次没有对应轮次记录的预留。价格未冻结，因此只能报告 1,538,045 个已记录 token，不能报告美元成本。

公开导出删除逐请求完整 prompt、供应商响应 ID、认证字段、本机绝对路径和传输失败归档原文，同时保留静态模板、反馈载荷、候选、诊断、usage 与重试计数。AI 辅助复核不得改写为纯人工复核。当前结果支持单模型描述性比较，不支持统计显著性、因果增益或跨模型泛化。

### E-09 的数值与发布边界

第二模型批次使用 DeepSeek Flash，在同一 repair24、任务顺序、三表示、三重复、三轮预算、编译时限、温度与最大输出上限下完成 216/216 个任务，无基础设施错误。Raw、Normalized、Structured 的首轮成功数分别为 67/72、63/72、66/72，三轮内成功数分别为 69/72、69/72、71/72，共 245 条有效逐轮记录和 948,466 个已记录 token。209 个成功证明均完成运行期独立复编译、AI 辅助复核和发布包再次独立复编译；7 个失败任务保持失败，不补跑挑选结果。

与 Pro 基线逐任务配对后，三种表示的最终结局一致率分别为 94.4%、88.9%、91.7%。Structured−Normalized 的模型内平均成功差在两个模型中均为 +2/72，但 72 个任务重复对中只有 1 对为同向非零，61 对为共同零差，另有 2 对相反、8 对仅一个模型非零。因此不能把总体均值同号直接表述为稳定处理增益。Pro 显式记录 `thinking=enabled`、`reasoning_effort=high`，Flash 对应字段为空；二者同属 DeepSeek 模型族。这些差异是残余混杂，E-09 只支持模型族内描述性一致性，不支持跨供应商泛化。

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

- Python：共发现 342 项测试，340 项通过，2 项因仅在 Linux 验证符号链接边界而跳过。在既有 Compiler Feedback、TRACER-REAL、Feedback Study、Capsule 与 SP 门禁上，新增覆盖六臂预注册、AI 辅助复核、脱敏发布合同、当前正式配置一致性、合成 provider 预检、PowerShell 密钥清理、失败工件保留式续跑、README 结果图与正式 `summary.json` 的逐柱一致性、v2 公开筛查账本、双语 README 计数一致性，以及原 35% 合同与公开 40% 修订的 fail-closed 行为。
- `lake build`：通过；冻结 Evaluation18 输入中的 18 个 `sorry` 是预期占位警告，不代表题目已在原文件中修复。
- `python -m leancapsule audit capsules`：24/24 通过。
- `python -m leancapsule verify capsules`：24/24 通过，包含 4 个 Mathlib 案例。
- `python scripts/run_capsule_feasibility.py --verify-only`：12 个 core 与 4 个 challenge 全部通过。
- `python scripts/verify_compiler_feedback_v1.py --verify-only`：15/15 通过，其中 12 个真实 Lean 失败、3 个基础设施事件；API 调用为 0，未改写已有实验。
- `python src/feedback_study.py plan`：离线生成 repair24 × raw/normalized/structured × 三重复的 216 任务计划，网络调用为 0；这不是模型结果。
- `python src/research.py plan --config experiments/research.deepseek.six_arm_20260920.json --benchmark benchmarks/repair24/manifest.json --preregistration experiments/preregistrations/repair24_six_arm_deepseek_20260920.json`：离线核对 2 模型 × 3 重复 × 6 臂 × 24 题 = 864 任务、2,592 次最大生成，网络调用为 0；这不是模型结果。
- `python src/security_study.py --check published/security-study-tracer-sp-v2/report.json`：SP-1～SP-12 误放行 0/12、CTRL-1～CTRL-8 策略误拒绝 0/8、正常对照 Lean 编译失败 0/8、拒绝前编译 0/12、检测器不一致 0/12；Wilson 95% 上界约为 24.3% 与 32.4%，只适用于当前案例集。
- `python src/security_isolation.py plan`：离线核对 `tracer-sp-isolation-v1` 的 14 项容器控制，网络调用为 0；当前机器未安装 Docker，因此没有生成或发布真实隔离 PASS。
- `python scripts/audit_feedback_study.py published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248 --compile-solutions`：发布静态审计通过，199/199 个公开证明独立复编译通过。
- `python scripts/audit_feedback_study.py published/feedback-study-562ad440-3446-4138-801e-59726ed0e108 --compile-solutions`：第二模型发布审计通过，209/209 个公开证明独立复编译通过。
- `python scripts/audit_feedback_comparison.py published/feedback-cross-model-8ccb89dd-562ad440`：Pro/Flash 的 216 个任务完整配对，比较包脱敏审计通过。
- `python scripts/audit_research_release.py published/research-six-arm-313f437f --compile-solutions`：六臂发布包的 864 任务、1,066 条有效轮次、864 行复核和 811 个公开证明一一对应；811/811 独立复编译通过。
- `python src/tracer_real_v2.py audit --benchmark benchmarks/real_repairs/tracer_real_v2/manifest.json`：六个项目的 1,576 个候选、256 个纳入与 1,320 个拒绝均与公开决定账本一致；最终 8 项目/265 题 manifest 与运行时预注册一致，provider 门禁可开启但尚未发生 v2 调用。
- `python src/tracer_real_v2_assembly.py status`：五个合格 test 项目共 254 题，全部公开子集均已构建并验证；PhysLean 94/254≈37.0% 低于公开修订后的 40% 有效上限，最终 spec 已冻结。
- `python scripts/validate_b_handoff.py` 与 `python scripts/validate_part3_handoff.py`：通过。
- 已发布 54 个成功证明逐个独立重编译通过。

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
5. **隔离原型已完成、实测待完成：** 已冻结 14 项 Docker/低权限控制与手动 workflow；下一步分别生成 Windows Docker Desktop 和原生 Linux 报告并脱敏审计，不把计划、环境标签或静态参数称为隔离通过。
6. **已完成公开导出：** raw/normalized/structured DeepSeek 批次已脱敏发布；保留 AI 辅助复核标识，未上传逐请求完整 prompts、历史归档原文或认证字段。
7. 真人计时与独立机器跨环境研究单独立项，不与模型结果混算。
8. **TRACER-REAL v2 已完成离线冻结，下一步是严格按预注册运行：** 六个上游共 1,576 个候选均已处理，256 条通过、1,320 条拒绝。SciLean 低于项目门槛，五个 test 项目共 254 题。PhysLean 的 37.0% 占比触发原 35% 门禁后，项目在 provider 调用前公开修订为 40%，没有删题、换题或改变其他门槛；最终 manifest 和运行时预注册已冻结。下一步不得再更换题库、模型、提示、分支或分析方法，只能按冻结对象运行并发布完整证据链。

新结果只有在包含冻结配置、原始轨迹、成功证明、独立重编译、明确标注的复核模式和发布审计后，才能从“可复验实现”升级为“已发布证据”。AI 辅助复核不能表述为纯人工复核。
