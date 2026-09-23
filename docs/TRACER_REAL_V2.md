# TRACER-REAL v2：两阶段纳入与确认性因果反馈实验

## 当前状态

TRACER-REAL v2 已完成**第一阶段预注册、六项目候选历史扫描、全部固定环境筛查、最终题库组装与运行时预注册**，尚未执行任何 v2 provider 调用。原 35% 单项目集中度门禁在六项目筛查后未通过；项目在最终 manifest 和 provider 调用前追加[公开修订](../experiments/preregistrations/tracer_real_v2_share_gate_amendment2.json)，将有效上限调整为 40%，完整保留所有合格题及其余门槛。

- [纳入合同](../benchmarks/real_repairs/tracer_real_v2.enrollment.json)冻结了项目、任务与结论门槛；
- [候选项目清单](../benchmarks/real_repairs/tracer_real_v2.candidates.json)已在候选历史扫描前冻结 6 个独立上游、各自端点版本和 120 个 first-parent 提交窗口；
- [六份扫描清单](../benchmarks/real_repairs/tracer_real_v2_candidates)完整保存 1,576 个可解析纯证明变化候选：LeanAPAP 51、PhysLean 675、Equational Theories 250、FLT 270、PFR 276、SciLean 54；这些只是编译前候选，不是 1,576 道合格题；
- [LeanAPAP](../benchmarks/real_repairs/tracer_real_v2_screening/leanapap.screen.json)、[PFR](../benchmarks/real_repairs/tracer_real_v2_screening/pfr.screen.json)、[SciLean](../benchmarks/real_repairs/tracer_real_v2_screening/scilean.screen.json)、[Equational Theories](../benchmarks/real_repairs/tracer_real_v2_screening/equational_theories.screen.json)、[FLT](../benchmarks/real_repairs/tracer_real_v2_screening/flt.screen.json)与 [PhysLean](../benchmarks/real_repairs/tracer_real_v2_screening/physlean.screen.json) 的完整筛查账本覆盖全部 1,576 个候选：256 个通过旧证明失败/新证明成功门禁，1,320 个带理由拒绝，provider 调用为零。FLT 的 47 个纳入题与 PhysLean 的 94 个纳入题均已构建为公开子集并独立复编译；
- [实验配置](../experiments/causal_feedback.tracer_real_v2.json)冻结了模型、生成参数、三次重复和八个干预分支；
- [纳入预注册](../experiments/preregistrations/tracer_real_causal_v2_enrollment.json)冻结了主对比、项目等权分析、停止规则和修订政策；
- [最终 manifest](../benchmarks/real_repairs/tracer_real_v2/manifest.json)冻结 8 个项目、265 个任务，其中 test 为 5 个独立项目、254 题；[运行时预注册](../experiments/preregistrations/tracer_real_causal_v2.json)冻结精确题库、模型、分支、重复数和最大调用数；
- [`src/tracer_real_v2.py`](../src/tracer_real_v2.py)负责离线审计，并只在最终题库达到门槛后生成不可覆盖的运行时预注册；
- [`src/causal_analysis_v2.py`](../src/causal_analysis_v2.py)在看到 v2 结果前实现项目等权主估计、项目级符号翻转检验和分层重采样区间；
- 因果 runner 已支持每个上游项目各自绑定相对 Lake 根和精确 `lean-toolchain`，不允许用一个命令行项目根覆盖全部 v2 项目。

[机器可读运行计划](../experiments/tracer_real_v2_screening.plan.json)中的 SciLean 54 项、Equational Theories 250 项、FLT 270 项与 PhysLean 675 项均已完成。其余 LeanAPAP 51 项与 PFR 276 项在该计划前已完成；六份报告共 1,576 条决定，逐项保存排除理由。默认单 worker、逐候选写入续跑状态；全流程不调用 provider。

当 repair24 正式实验仍在运行时，只执行轻量状态检查：

```powershell
.\scripts\run_tracer_real_v2_screening.ps1 -Mode Status
```

入口会报告筛查是否全部完成和本地检出状态；若检测到 `src/research.py run` 或 `resume` 进程，`Prepare` 与 `Screen` 会硬拒绝，避免两个实验争用 CPU、磁盘和 Lake 缓存而污染耗时证据。以下是历史执行顺序，不应在已有完整报告上重复运行：

```powershell
$project = "physlean"
.\scripts\run_tracer_real_v2_screening.ps1 -Mode Prepare -Project $project
.\scripts\run_tracer_real_v2_screening.ps1 -Mode Screen -Project $project
.\scripts\run_tracer_real_v2_screening.ps1 -Mode Build -Project $project
```

`Prepare` 要求固定端点、干净工作树、精确工具链和已经提交的 `lake-manifest.json`。冻结 manifest 是唯一依赖锁，准备阶段禁止调用 `lake update`，因为浮动 branch 依赖可能在上游端点不变时仍发生漂移。它获取锁定缓存并以单线程执行完整 `lake build`；若上游可选本机库在当前平台链接失败，必须让冻结候选清单中的真实 Lean 源码通过项目环境探针，才允许继续，不能仅凭 `.lake/packages` 存在放行。`Screen` 固定使用 `--workers 1 --timeout 180`。中断后重复同一条 `Screen` 命令会读取逐项状态继续，不能改候选或覆盖完整报告。`Build` 只能用于已有完整公开筛查报告的指定项目，它会重新验证所有纳入题，公开任务写入 `benchmarks/real_repairs/<project>_v2/`，参考证明隔离写入被版本控制排除的 `private_references/<project>_v2/`；两类输出均拒绝覆盖。每完成一个项目，`tracer_real_v2.py audit` 会重新核对所有已发布决定。这里的运行计划与状态审计不是筛查结果。

`Status` 只基于六份已公开完整报告和公开门禁修订计算 `enrollment_projection`。六项目共有 256 个通过项；SciLean 的 2 项未达到每项目至少 5 题的门槛，因此五个合格测试项目共 254 题。PhysLean 的 94/254≈37.0% 超过原 35% 上限，但低于修订后的 40% 有效上限；当前全部纳入门禁均为 true。

最终组合另有 fail-closed 入口。它只读取完整筛查报告、公开修订和已构建子题库，不运行 Lean、不调用 provider：

```powershell
python src/tracer_real_v2_assembly.py status
python src/tracer_real_v2_assembly.py write-spec
```

只有六项目全筛完、至少五个新项目各有五题、总题数/四类错误/有效 40% 项目占比同时达标，且每个合格项目的公开子题库与报告题数和上游来源一致时，`write-spec` 才会生成 `benchmarks/real_repairs/tracer_real_v2.projects.json`。这些门禁已通过，组合器已生成最终 manifest；provider 仍只在下文 audit 和不可覆盖运行时预注册都通过后放开。

当前离线审计会核对候选项目、端点、扫描窗口、完整决定账本、最终题库和运行时预注册，并返回 `ready_for_provider_run: true`：

```powershell
python src/tracer_real_v2.py audit
```

门禁失败不是软件故障。项目没有裁剪 PhysLean 的 94 项，也没有静默重写原合同；修订记录同时保存 35% 原值、94/254 的触发证据、40% 新值、零 provider 调用和“其他规则不变”承诺。40% 是工程集中度上限，不是统计定理；任何论文或报告都必须披露这次修订，不能把它描述为原始预注册门槛。

## 为什么不直接把 v1 改名为 v2

TRACER-REAL v1 只有 Mathlib、Batteries 和 Aesop 三个项目，共 11 条真实历史修复。其中 Aesop 是唯一测试项目；实际首轮还可能直接成功，因此它不足以支持跨项目确认性结论。

v2 不通过复制题目或拆分同一仓库来凑项目数。Mathlib 保留为 development；Batteries 与已在 v1 使用的 Aesop 只可用于 validation。它们全部被禁止重新进入 v2 test。测试项目身份按规范上游仓库判断，镜像、派生仓库或不同名称不算新项目。

## 冻结纳入门槛

最终 `tracer-real-v2` 必须同时满足：

| 门槛 | 冻结值 |
| --- | ---: |
| 独立项目总数 | 至少 8 |
| 全新测试项目 | 至少 5 |
| 总任务 | 至少 51 |
| 测试任务 | 至少 40 |
| 每个测试项目任务 | 至少 5 |
| 单个测试项目占全部测试任务 | 原合同不超过 35%；provider 前公开修订后的有效上限为 40% |
| 测试错误类别 | 至少 4 |
| 合格首轮失败结论门槛 | 至少 30 |

每条任务仍须满足真实公开 Git 历史、定理陈述不变、旧证明在修复环境稳定失败、修复证明在同一环境独立通过、许可与 provenance 完整、参考证明不进入公开任务或模型上下文等要求。不得在看到 provider 结果后增删或换题。

## 两阶段冻结

### 阶段一：纳入规则预注册（已完成）

在检索新测试项目和执行 v2 provider 调用前冻结：

1. 项目与任务纳入、排除规则；
2. 最低样本量和项目平衡门槛；
3. 模型配置、三次重复、八个干预分支；
4. 唯一主对比 `true_structured - content_free_retry`；
5. 项目等权估计、单侧项目符号翻转检验和 10,000 次分层重采样区间；
6. 任何基础设施异常阻止确认性报告；
7. 最终清单冻结前 provider 调用数必须为零。

### 阶段二：最终题库与运行时预注册（已完成）

对每个候选上游项目使用 [`src/real_repairs.py`](../src/real_repairs.py) 构建子集。参考证明写入被版本控制排除的独立目录。完成候选池后，使用 `tracer-real-project-split-v2` 规范组装项目级清单；每个项目条目额外记录：

项目内候选必须先经 [`src/real_repair_inventory.py`](../src/real_repair_inventory.py) 的确定性两步流程：`scan` 固定端点与 first-parent 窗口并枚举全部可解析纯证明变化，`screen` 对每项执行旧证明失败/新证明通过门禁并保留每个接受或排除理由。筛查每完成一项即追加续跑状态；候选漂移时拒绝复用旧状态。`screen --workers N` 只并行相互隔离的临时编译，检查点仍由主线程串行追加，最终报告仍按冻结清单顺序生成。不得只把人工挑中的成功候选写进 spec。

- `compile_project_root`：仓库内相对 Lake 根；
- `lean_toolchain`：该环境的精确工具链文本。

组装器会把它们写入最终 manifest 的 `project_environments`，并验证 Lake 文件与工具链。最终清单必须先通过：

```powershell
python src/tracer_real_v2.py audit `
  --benchmark benchmarks/real_repairs/tracer_real_v2/manifest.json
```

通过后再生成最终运行时预注册；命令拒绝覆盖已有文件：

```powershell
python src/tracer_real_v2.py finalize `
  --benchmark benchmarks/real_repairs/tracer_real_v2/manifest.json `
  --experiment-id tracer-real-causal-v2-deepseek-YYYYMMDD
```

最终文件应为 `experiments/preregistrations/tracer_real_causal_v2.json`。只有该文件存在、最终题库通过门禁、逐项目环境可离线编译且全仓库测试通过，才可预览正式计划。v2 正式运行不得传统一的 `--project-root`：runner 必须从 manifest 为每题选择其所属项目环境。

## 确认性分析

实验单位仍是“模型 × 重复 × 题目”的冻结首轮候选。只有真实、非基础设施的首轮 Lean 失败进入反馈效果人群。所有分支逐字共享该首轮候选。

主终点是一次分支生成后的 Lean 内核成功。主估计先在每个测试项目内计算 structured 相对 content-free retry 的配对成功率差，再对测试项目等权平均，避免任务较多的单个仓库主导结论。唯一主假设采用项目级单侧精确符号翻转检验；其他干预、错误类别、token、时间、图状态和检索变化均为次要或探索性分析。

测试项目不超过 20 个时枚举全部项目符号组合；超过 20 个时使用冻结随机种子执行 100,000 次随机化并采用加一修正。主检验通过要求项目等权平均差为正且单侧 p 值不大于 0.05；10,000 次项目—候选两层重采样的 95% 区间必须同时报告，但不替代主检验。分析入口为：

```powershell
python src/causal_analysis_v2.py `
  --run results/causal-tracer-real-v2-YYYYMMDD `
  --out results/causal-tracer-real-v2-YYYYMMDD/confirmatory_analysis.json
```

即使题库规模达标，只要合格首轮失败少于 30、轨迹不完整、出现 provider/策略/编译基础设施异常、同首轮候选不变量失败或成功证明不能独立复编译，确认性结论仍被拒绝。

## 明确边界

- 当前已冻结纳入设计、最终 benchmark 与运行时预注册，但它们仍不是 provider 实验结果；
- v1 的 11 条任务与其运行记录保持原样，不回写成 v2；
- 五个 test 项目由冻结候选、逐项编译门禁与最小题数规则机械确定，没有按 provider 表现选题；
- 六个候选上游的 1,576 个候选已全部完成固定环境筛查并公开决定；SciLean 未达到每项目五题门槛，PhysLean 的 94/254 触发了 35%→40% 的公开修订；依赖下载或环境构建中断不计为项目或题目通过；
- 当前没有 v2 API 成本、成功率或因果增益；
- 若后续必须改变门槛或主分析，应追加带日期的修订记录，不能静默覆盖本预注册。
