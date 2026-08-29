# 研究实验操作与预注册协议

与旧 [18 题 pilot 指南](REAL_PILOT_GUIDE.md) 分离。不覆盖旧日志、成功证明、人工复核表或已发布结果。新运行必须使用新输出目录。

## 1. 两层题库

- Smoke：原有 benchmarks/manifest.json 与 lean_project/Benchmarks/Evaluation18.lean，18 题及旧 A/B/C 结果保留。
- 修复研究：benchmarks/repair24/manifest.json，24 个独立 Lean 文件，5 个主题（递归列表、量词、函数、Option、递归自然数）。输入包含错误证明，不只是占位符。
- 冻结版本 repair24-v1：清单保存完整源码文本，运行时逐字比较（Python 文本读取统一换行）。改题时新增版本，不在观察结果后悄悄修改当前版本。
- 参考证明只在 tests/fixtures/repair24_reference.json；生产运行器不加载它。不得把 tests 或整个仓库交给模型。
- 初始错误须得到真实编译失败，不能用超时、缺失编译器或语法损坏冒充。测试另行验证参考证明。难度是设计目标，模型难度待测。

~~~powershell
python src/research.py check-benchmark
python -m unittest discover -s tests -p test_research_benchmark.py -v
~~~

## 2. 组间控制

| 组 | 初始/后续诊断进入 prompt | 成功示例检索 | 查询策略 | 失败上下文 |
| --- | --- | --- | --- | --- |
| A | 否 | 否 | 无 | 否 |
| B | 是 | 否 | 无 | 否 |
| C | 是 | 是 | 固定查询 | 否 |
| D | 否 | 是 | 固定查询 | 否 |
| C_dynamic | 是 | 是 | 题目＋当前诊断，错误词额外加权 | 否 |
| C_failure | 是 | 是 | 同 C_dynamic | 是 |

A/D 仍编译以判定停止，但不把结果送回生成器；重试不等于使用反馈。B/C 家族在第一次生成前可读取原始错误证明的诊断，后续还包含上一轮候选。各组固定 imports、局部定义和声明。

动态查询包含未知标识符、类型信息及 ⊢ 目标的有界文本。这是启发式排序，不是训练式检索；不保证每次错误变化都更换示例。query、snippet、prompt 均记录。

失败语料 experiments/failure_notes.json 来自已有公开 Capsule。注释在排序后追加，因此 C_dynamic/C_failure 的基础语料和排序算法相同。后续候选分叉会使诊断与结果集合不同，这是处理效应的一部分。映射是人工构造；推广前应扩大覆盖并增加等长度无关上下文控制，不能只凭胜出就归因于错误语义。

## 3. 多模型重复运行

复制示例配置，编辑实际模型和预算，不要填写 Key：

~~~powershell
Copy-Item experiments/research.example.json experiments/research.local.json
notepad experiments/research.local.json
python src/research.py plan --config experiments/research.local.json
~~~

修改 id、实际 model、受信任的 Chat Completions api_url、api_key_env、temperature、max_tokens。冻结研究矩阵显式使用 Chat 协议，不继承终端的接口或推理参数；单题 provider 另支持 Responses。支持当前请求参数不等于所有 GPT/推理模型协议都兼容；详见 [API 指南](API_GUIDE.md)。

默认：24 题 × 2 模型 × 3 重复 × 6 组 = 864 任务，最多 2592 次生成。plan 不联网、不读取 Key。研究入口禁用自动 HTTP 重试；单题/旧 pilot 保留自己的重试设置，不得混为一谈。

先用单模型、单重复、少数组调试，不能把它混入正式矩阵。正式配置运行前冻结，不按中途分数更换模型或挑选最佳重复。

使用隐藏输入，不把 Key 写入配置、命令历史或持久环境。下面是待用户批准的 48 任务预跑，不是正式六条件实验：

~~~powershell
python src/research.py plan --config experiments/research.deepseek.preflight.json
python src/research.py run --config experiments/research.deepseek.preflight.json --out results/research-deepseek-preflight-001 --api-key-prompt --max-calls 144 --max-reserved-usd 5
~~~

run 才调用付费 API；执行即授权指定来源、任务数及预算。价格字段是每千输入/输出 token 的美元估计。CLI 的预算模式要求价格已配置，不能使用 null。每次调用前按输入字节数＋封装余量与最大输出额度保守预留，失败或超时不退回该预留、不自动重试；达到任一上限停止并保留部分批次。这是本地估算保护，不是服务方硬账单上限；价格变更、额外收费需另行核对。需要硬消费限制时使用服务方账号限额。密钥只在进程内使用，同服务共享变量只询问一次，不显示后缀，不使用历史对话中的 Key。

完整配置 [research.deepseek.json](../experiments/research.deepseek.json) 是 Flash/Pro 两模型、三重复、六组。预跑结果不可混入完整实验；完整运行前重新批准预算并选择新目录。两种模型来自同一模型家族，不代表跨厂商泛化。

当前 48 任务预跑的编译时限统一为 180 秒：本机曾在 60 秒预检时发生工具链超时，180 秒复检后 24 题均形成有效修复输入。该调整发生在任何收费生成之前；它不是放宽证明正确性，也不修改 Lean 声明。完整矩阵仍需单独核准配置，不能混合不同编译预算的运行。

截至 2026-08-28，[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/) 的峰时每百万输入未命中/输出美元价格分别为 Flash 0.44/1.32、Pro 1.32/3.96。配置按峰时且全部输入未命中估算，未减去缓存与低谷折扣，所以不是实际账单。完整矩阵若每次输出均达 12000 token，仅输出按此价格约 82.11 美元，另加输入；不是预测实际花费。

两模型显式固定 thinking=enabled、reasoning_effort=high。官方说明[思考模式会忽略 temperature](https://api-docs.deepseek.com/guides/thinking_mode/)，因此不能把配置中的 0 写成确定性生成保证。日志同时保存请求参数与服务端返回的 model/id/finish_reason；别名版本仍可能随供应商更新。

每个模型在组间保持温度、输出上限、轮数、编译时限和基础语料一致。order_seed 随机排列模型/题目/组别/重复以减轻时段偏差；不是供应商采样 seed，温度 0 也不保证完全确定。

每任务独立，禁用请求缓存；保存源码、语料和配置快照。发生 provider/任务基础设施错误即停止后续付费调用，保留未完成批次；不将其算成纯证明失败。改配置时使用新目录，不补写旧批次冒充连续运行。

## 4. 轨迹与报告

### 证明协议 v2（预跑后修订）

新运行在 `plan.json` 和每轮日志记录 `tracer-proof-v2`，并在计划中保存各组提示模板全文。运行始终使用这份模板快照，不受之后编辑文件影响；缓存请求文本包含可读协议字段。题库仍为 repair24-v1，未改题或加入答案。

- 所有组共享完整区域替换契约：输出直接放在目标定理的 `:=` 后；tactic 证明必须含 `by`、所有引入及分支，不能只补最后几行。纯证明项不强行加 `by`，系统不擅自补全模型答案。
- `finish_reason=length` 单独记为 `generation_truncated`；即使含部分代码，也不编译、不计成功。这消耗一次既定轮次，usage 与费用照常记录，不自动增加输出额度。空但未标记截断的答案仍为 `invalid_candidate`。
- 编译不再将全部普通警告提升为错误。`kernel_pass`、`compile_has_warnings`、`warning_free` 分别记录验证与风格情况；未编译时为 null。`sorry`、`sorryAx`、`admit` 和未完成证明诊断仍拒绝。源文件显式设置的检查选项仍由 Lean 处理。
- 报告增加截断次数、空候选次数、失败尝试分类、带警告成功及无警告成功。成功率衡量既定预算和协议内的任务成功，不把生成截断当成数学能力失败。
- 没有协议字段的历史轨迹按 `legacy-strict-warnings-v1` 解释，保留原始 `compile_ok`；未知新协议或混合字段拒绝汇总。不得将旧成绩按新规则回填，或把两种协议合成同一实验。

### 2026-08-28 已完成预跑及审计

用户明确授权向 DeepSeek 官方 API 发送 24 道题的必要源码、上下文、候选与诊断，并在本地隐藏输入 Key，执行 48 个 B 组任务；上限 10 美元。原始批次为 `research-80be2a1f-c253-4b1b-a3cc-b901e9d120b7`，保存在 `results/research-deepseek-preflight-20260828-183413`，仍是本地未发布材料。

| 模型 | 首轮 | 三轮内 | 请求数 | 按该批配置估算费用 |
| --- | --- | --- | --- | --- |
| DeepSeek Flash | 18/24 | 20/24 | 34 | $0.27831452 |
| DeepSeek Pro | 18/24 | 19/24 | 35 | $0.94770720 |

这是旧严格警告协议的真实观察值，不改成 v2 成绩。69 次请求均无基础设施错误、本地答案缓存命中为 0；预算保守预留 $2.32262492，usage 估算合计 $1.22602172，不是账单。39 个成功文件独立复编译并检查公理依赖，未发现未完成证明公理。

21 次请求以 length 结束且没有最终证明，记录的输出额度基本全部用于推理；另有 3 次拒绝仅因普通 linter 警告（离线以普通警告规则复编译均通过），其中 Pro 的 tri_lower 是最终失败。两个模型在 exists_and 上输出了证明尾部而非整个替换区域，促成上述协议修订。后续轮次成功的 3 题中，2 题消除了警告，1 题从生成截断恢复，不能据此宣称数学反馈修复增益。

这只是 B 组一次预跑；Flash 多通过一题不构成更强模型的结论。人工复核和完整消融未完成，release_ready=false 合理。v2 修复只做离线验证，未新增 API 调用；下一批必须独立目录、提前固定配置并重新确认预算，不自动复用本次预算余额。以上观察用于探索性协议改进，不把观察后修订称为原批次的预注册设计。

~~~text
results/research-run-001/
  plan.json                   模型、随机化计划、平台、工具链、协议及提示模板快照
  benchmark.json              题库全文快照
  examples.json               基础语料快照
  failure_notes.json          失败上下文快照
  initial_compilation.json    初始错误的编译记录
  trials/model/repeat/arm/id/
    runs.jsonl                prompt、query、候选、usage、诊断
    trial.json                独立重编译、任务耗时和状态
    solutions/                成功文件或最后失败候选
  manual_review.csv           模型/重复/组别/题目逐项复核
  completion.json
  budget.json                 请求前写入的次数与保守费用预留（不含密钥）
~~~

~~~powershell
python src/research.py report --run results/research-run-001
~~~

门禁检查缺失任务、混合批次、模型配置、跨任务复用 run_id、缓存命中、轮次及成功证明。编译超时或补丁/工具链错误同样停止批次，不能作为纯证明失败。不完整批次只能用 --allow-partial 生成带错误标记的诊断汇总，不作正式结果。

summary.json / summary.csv 包含首轮/三轮成功率、重复均值和标准差、轮数、生成/编译/总耗时、输入/输出/总 token 及费用。价格或 usage 缺失显示 null；已知费用小计不是完整账单。供应商缓存分层、推理 token 计价或折扣须在 pricing_note 说明，双单价估计不替代发票。

人工检查成功证明后填写 kernel_pass=yes、inappropriate_assumption=no、leakage_risk=no 和 reviewer_note，不得未经检查批量 PASS。trajectory_valid 是自动轨迹校验；release_ready 另需完整多模型/重复四条件设计及成功题复核。旧 validate_pilot.py / export_pilot.py 只支持旧 18×3 格式，不用于新矩阵。新轨迹默认本地保存，发布前另行脱敏审计，勿使用 git add . 强行加入运行目录。

比较按同模型、同题、同重复配对。重复不是新数学题，不扩大独立样本数；论文建议按题聚类 bootstrap 并披露各次重复。脚本提供描述统计，不输出显著性结论。失败、不利结果和基础设施中断都须披露。

## 5. LeanCapsule 价值验证

### 跨环境回放与精简

分别在 Windows、Linux 独立检出，准备同一固定工具链/依赖。不同工具链版本的兼容性测试单独报告。

~~~powershell
python src/capsule_metrics.py measure --environment-label windows-local --out results/research-capsule-windows --repeats 2 --source-map experiments/capsule_sources.json
~~~

Linux 使用同一命令，改标签和输出目录；然后汇集两份轨迹：

~~~powershell
python src/capsule_metrics.py merge results/research-capsule-windows/replays.jsonl results/research-capsule-linux/replays.jsonl --out results/research-capsule-comparison.json
~~~

记录实际 OS、架构、Lean 版本、回放时间、预期诊断是否重现、行数/字节/import 数及精简尝试。改标签不算新环境；同案例源码不一致则拒绝合并。首次观察不等于严格冷启动，热缓存不能写作新机器开箱成功率。

experiments/capsule_sources.json 映射原文件；其诊断独立匹配后才统计缩减率。旧 evaluation18 成功 Capsule 未映射当前含占位符的原题，避免把不同证明版本冒充精简前后。负缩减比、完整文件 fallback 均保留，不筛掉不利结果。

### 人工定位时间

审查发现现有 23 对 gallery 原文与 Capsule 源码完全相同，不能用源码阅读计时证明精简收益。先前两条“错误位置＋原因”记录无效；2026-08-28 按用户要求将旧预演和新未完成计时会话移入回收站，人工研究暂停，材料与代码保留。两个已向参与者解释过答案的旧案例不用于新计时。

新增 `human_study.py` 准备 8 对合成上下文/精简材料：使用真实 pack 抽取，原文/精简版诊断等价，文件确实缩短；这只是控制上下文长度的合成预研究，不冒充真实用户缺陷或完整 Capsule UI 的效果。材料在 results 中单独保存，不替换原 gallery。不要提前阅读 src/human_study.py、材料 JSON 或 reviewer 目录，里面有答案。

互补分配：p01/p02 等相邻两位参与者看到同题的相反版本；单人每题仅一次，各看到 4 个原文与 4 个精简版。编号不能替换同一个真人。至少招募两人才能覆盖所有题的两个版本；两人仍只是可行性预研究，不能据此作可靠显著性结论。

~~~powershell
python src/human_study.py run --participant-number 1
python src/human_study.py report
~~~

材料已经准备好时不再运行 prepare；新材料目录可用 `python src/human_study.py prepare --out results/human-materials-new` 生成并独立验证。第二位不同真人运行 `--participant-number 2`。开始前声明自愿参与及经验；按 Enter 后才显示代码并启动计时，定位完按 Enter 停止，之后填写行号原因，答题录入不计入定位时间。600 秒默认预算，工具不会强制打断输入，但超过预算明确标记 timed_out。放弃、已曝光未完成、无效答案均保留/拒绝，不伪造完成记录。显示中立任务编号，但文件长度不可盲；这不是双盲研究。

`events.jsonl` 记录曝光，`responses.jsonl` 保存原始答案；中断不删除。`review` 子命令将依据写到独立 `reviews.jsonl`，要求明确 `--reviewer-kind human` 或 `ai_assisted`，不修改原始回答。AI 可以辅助正确性复核，不能代替真人计时或冒充真人评审。报告分开列正确且预算内时间、放弃、超时、待复核；无记录不会产生假结果。

### 失败复用

完整矩阵中配对 C_dynamic/C_failure，比较 pass@3、轮数与增加的 token/费用。当前提供接入和设计，不代表已测得增益。

## 6. 结论边界

实现、测试通过、真实模型收益、跨环境收益和人工定位收益是五类不同证据。缺 API、第二环境或真实参与者数据时必须标“待测”。不得填造 token、费用、证明或人工复核。候选策略仍不是操作系统沙箱，不受信任 Lean 项目应在低权限容器或虚拟机运行。
