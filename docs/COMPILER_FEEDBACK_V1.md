# Compiler Feedback v1 离线协议

> **状态：冻结的可复验实现（2026-09-09）。** 本协议不调用模型 API，不改写既有实验轨迹，也不证明任何反馈表示能提高修复成功率。

Compiler Feedback v1 把一次编译结果保存为原始、规范化和结构化三层。三层同时存在，既允许程序统计，也让研究者能回到脱敏后的原文核对抽取是否失真。

## 1. 冻结范围

- 协议版本：`tracer-compiler-feedback-v1`。
- 机器可读规则：[protocol.json](../benchmarks/compiler_feedback_v1/protocol.json)。
- 记录结构：[record.schema.json](../benchmarks/compiler_feedback_v1/record.schema.json)。
- 冻结夹具：[manifest.json](../benchmarks/compiler_feedback_v1/manifest.json)。
- 实现：[compiler_feedback.py](../src/compiler_feedback.py)。
- 离线门禁：[verify_compiler_feedback_v1.py](../scripts/verify_compiler_feedback_v1.py)。

该版本只冻结诊断表示和最小失败夹具，不替换 P-A/P-B/P-C、R-A～R-F 或 FATE-M 的历史日志格式。

## 2. 三层记录

| 层 | 主要字段 | 规则 |
| --- | --- | --- |
| `raw` | `origin`、`text`、`compile_ok`、`returncode`、`timed_out` | 保存一次运行的完整诊断，只清理认证信息、本机绝对路径和换行差异 |
| `normalized` | `category`、`summary`、`diagnostic_text` 及现有诊断字段 | 规范位置、易变元变量编号和空白，但保留全部非空诊断行 |
| `structured` | `category`、`category_source`、`category_evidence`、`signals` | 抽取未知标识符、实际/期望类型、目标、typeclass、elaboration、语法或基础设施信号 |

每个 `signals[]` 项都必须包含：

- `kind`：冻结的信号类型；
- `value`：供离线统计使用的可读值；
- `evidence_excerpt`：逐字存在于 `raw.text` 的原始诊断片段。

`structured.category_evidence` 同样必须逐字存在于失败记录的 `raw.text`。校验器会拒绝凭空生成、改写后无法回溯或缺少原文依据的字段。

## 3. 分类来源

真实 Lean 编译结果的 `category_source` 必须是 `diagnostic_text`，不得使用 `category_hint` 覆盖。只有运行时才能确定的三类基础设施事件可以显式传入元数据：

- `timeout`：运行器超时；
- `provider_error`：模型服务调用失败；
- `compiler_unavailable`：Lean/Lake 进程不可启动。

这些事件单独计数，不作为普通证明失败。协议不读取参考证明、运行时答案表或模型生成的分类覆盖值。

## 4. 冻结夹具

当前共 15 个最小失败夹具，其中 12 个由固定 Lean 4.32.0 真实编译，3 个是显式基础设施事件。

| ID | 家族 | 预期类别 | 运行来源 |
| --- | --- | --- | --- |
| CF-01～CF-02 | 未知标识符/命名空间 | `unknown_identifier` | Lean 编译 |
| CF-03～CF-04 | 字面量与函数应用类型错误 | `type_mismatch` | Lean 编译 |
| CF-05～CF-06 | 合取与分支中的未解决目标 | `unsolved_goals` | Lean 编译 |
| CF-07～CF-08 | 意外 token 与缺失项 | `syntax` | Lean 编译 |
| CF-09～CF-10 | 缺少 typeclass 实例 | `typeclass` | Lean 编译 |
| CF-11～CF-12 | binder/占位符 elaboration 失败 | `elaboration` | Lean 编译 |
| CF-13～CF-15 | 超时、provider、编译器不可用 | 对应基础设施类别 | 显式运行时元数据 |

清单直接保存每个 Lean 源码或基础设施诊断的完整可读快照。门禁逐文件比较文本，不生成派生摘要或指纹。

## 5. 离线验证

只验证协议和冻结夹具，不写结果文件：

```text
python scripts/verify_compiler_feedback_v1.py --verify-only
```

如需保存一次新的观察记录，可指定一个尚不存在的路径：

```text
python scripts/verify_compiler_feedback_v1.py --out results/compiler-feedback-v1-observation.jsonl
```

写出模式拒绝覆盖已有文件。门禁汇总会明确报告 `api_calls: 0` 和 `existing_experiments_modified: false`。

## 6. 证据边界

当前实现可以支持以下结论：

- 三层字段和证据来源规则已冻结并可离线校验；
- 12 个 Lean 失败实例与 3 类基础设施事件能按预期分类；
- 结构化字段可以逐项回溯到脱敏后的原始诊断。

它不能支持以下结论：

- 模型会读取或采纳结构化反馈；
- 某种反馈表示优于另一种表示；
- 动态检索查询会因此改善；
- 15 个夹具覆盖 Lean 的全部诊断或真实项目分布。

反馈采纳率、重复错误率、完整错误转移矩阵、查询变化率和受控模型比较仍属于 F2/F3 后续工作。
