# Results 目录说明

`results/` 是当前本地运行输出与 LeanCapsule 复验工件目录。正式公开发布包统一放在仓库根目录的 `published/`；已经被取代的实验和交接材料统一放在 [`historical/`](../historical/README.md)。

## 当前纳入仓库的工件

- `capsule_feasibility/`：12 个 core 案例及其回放汇总；
- `capsule_challenges/`：4 个 challenge 案例及其回放汇总。

两组结果用于验证有限案例中的编译状态、错误类别和规范化诊断保真度，不代表任意项目都可自动最小化，也不等于证明修复成功。

## 本地运行时输出

- `agent_runs.jsonl`、`solutions/`、`requests.sqlite3`：交互式或单题 Agent 运行；
- `research-*/`：repair24 多臂研究；
- `feedback-study-*/`、`causal-*/`：反馈表示或因果实验；
- `tracer-real-v2-screening/`：上游筛查工作目录；
- `human-*/`、`sp-isolation-*/`：真人研究或隔离探针结果。

这些内容由 `.gitignore` 排除。缺少本地目录不表示实验失败，也不能根据汇总数字反向补造原始轨迹、复核或费用记录。需要发布时必须使用相应脱敏导出器，并通过发布审计。

## 当前正式发布

- [`published/research-six-arm-313f437f/`](../published/research-six-arm-313f437f/)：864 任务六臂主结果；
- [`published/security-study-tracer-sp-v2/`](../published/security-study-tracer-sp-v2/)：SP v2 安全回归。

旧 Evaluation18、Feedback Study v1 和 FATE-M 交接均完整保存在 [`historical/`](../historical/README.md)，不再混放在当前 `results/` 或 `published/`。

## 结果判读

- `provider_error` 表示请求没有产生可用候选；syntax/type/goal 类别表示候选已经进入 Lean；
- 请求缓存只适合本地调试，正式独立运行不得把缓存命中计作新采样；
- 未配置价格时成本是 unknown/null，不是零；
- 编译通过、发布审计通过与研究结论成立是三个不同层级。
