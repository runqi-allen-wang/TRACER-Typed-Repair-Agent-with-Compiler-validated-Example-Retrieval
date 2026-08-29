# JSONL 追踪字段

每次修复尝试都会向配置的追踪文件追加一个 JSON 对象。记录以题目、条件和轮次为分析单位，同时保存规范化后的候选、provider 状态和编译结果。API 密钥不会进入追踪文件。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `run_id` | string | 一次 solve 调用的标识 |
| `experiment_id` | string 或 null | 一整批 A/B/C 运行的批次标识；报告按此字段隔离 |
| `benchmark_id` | string 或 null | 冻结清单中的题目标识 |
| `problem_id` | string | Agent 使用的稳定题目键 |
| `theorem` | string | 完全限定的 Lean 定理名 |
| `condition` | string | Prompt 条件 `A`、`B` 或 `C` |
| `round` | integer | 从 1 开始的修复轮次 |
| `candidate` | string | 清洗传输格式后的局部 Lean 证明项 |
| `provider` | string | Provider 名称 |
| `provider_config` | object | 不含密钥的模型与生成配置 |
| `provider_error` | string 或 null | Provider 调用失败正文；非空时不会调用编译器 |
| `usage` | object | Provider 报告的输入、输出和总 token |
| `estimated_cost_usd` | number 或 null | 根据可选价格配置估算的成本；未配置价格时为 null，不解释为零成本 |
| `cache_hit` | boolean | 本轮是否由 SQLite 精确请求缓存提供 |
| `retrieved_examples` | array | 条件 C 实际加入 prompt 的示例 |
| `prompt_chars` | integer | Prompt 字符数 |
| `compile_ok` | boolean | Lean 是否接受隔离源文件 |
| `compile_elapsed_ms` | number | 编译器墙钟耗时 |
| `diagnostic` | object | 结构化类别、摘要和有界反馈 |
| `raw_diagnostics` | string | 未结构化的 provider 或 Lean 原始诊断 |
| `compiler_command` | array 或 null | 实际使用的 Lean/Lake 命令 |
| `timestamp_utc` | string | UTC 事件时间 |

原始源文件不会被覆盖。成功隔离文件保存在 `results/solutions/<experiment_id>/<condition>/`；持续失败的最后候选保存在对应批次的 `failures/` 子目录中。
