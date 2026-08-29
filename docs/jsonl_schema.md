# JSONL 追踪字段

每次修复尝试都会向配置的追踪文件追加一个 JSON 对象。记录以题目、条件和轮次为分析单位，同时保存规范化后的候选、provider 状态和编译结果。API 密钥不会进入追踪文件。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `run_id` | string | 一次 solve 调用的标识 |
| `experiment_id` | string 或 null | 一整批 A/B/C 运行的批次标识；报告按此字段隔离 |
| `benchmark_id` | string 或 null | 冻结清单中的题目标识 |
| `problem_id` | string | Agent 使用的稳定题目键 |
| `theorem` | string | 完全限定的 Lean 定理名 |
| `condition` | string | Prompt 条件 `A`、`B`、`C` 或 `D`；动态检索由独立字段标识 |
| `round` | integer | 从 1 开始的修复轮次 |
| `candidate` | string | 清洗传输格式后的局部 Lean 证明项 |
| `provider` | string | Provider 名称 |
| `provider_config` | object | 不含密钥的模型与生成配置 |
| `provider_response` | object | 服务端返回的 model、id、finish_reason，不记录推理正文 |
| `proof_protocol` | object | 新运行的可读输出/验收协议；当前版本 tracer-proof-v2，旧日志可能缺失 |
| `generation_status` | string | complete / truncated / unknown；unknown 表示缺少结束标记，不推断已正常结束 |
| `provider_error` | string 或 null | Provider 调用失败正文；非空时不会调用编译器 |
| `usage` | object | Provider 报告的输入、输出和总 token |
| `estimated_cost_usd` | number 或 null | 根据可选价格配置估算的成本；未配置价格时为 null，不解释为零成本 |
| `cache_hit` | boolean | 本轮是否由 SQLite 精确请求缓存提供 |
| `retrieved_examples` | array | 条件 C 实际加入 prompt 的示例 |
| `prompt_chars` | integer | Prompt 字符数 |
| `compile_ok` | boolean | 该批协议下是否成功；旧严格警告口径不可按新口径重写 |
| `kernel_pass` | boolean 或 null | 新协议下隔离证明是否通过 Lean 及未完成证明检查；未编译时 null |
| `compile_has_warnings` | boolean 或 null | 新协议下诊断是否含普通警告；未编译时 null |
| `warning_free` | boolean 或 null | 新协议下证明通过且没有普通警告；未编译时 null |
| `compile_elapsed_ms` | number | 编译器墙钟耗时 |
| `diagnostic` | object | 结构化类别、摘要和有界反馈；已编译诊断另含 warnings / warning_count |
| `raw_diagnostics` | string | 未结构化的 provider 或 Lean 原始诊断 |
| `compiler_command` | array 或 null | 实际使用的 Lean/Lake 命令 |
| `timestamp_utc` | string | UTC 事件时间 |

原始源文件不会被覆盖。成功隔离文件保存在 `results/solutions/<experiment_id>/<condition>/`；持续失败的最后候选保存在对应批次的 `failures/` 子目录中。

新 repair24 研究另用 `results/<研究目录>/trials/<模型>/<重复>/<组>/<题目>/`，以该目录内的 solutions 保存文件。`finish_reason=length` 不编译、记录 generation_truncated、消耗一轮且保留 usage/费用；不是 API 认证错误，也不直接证明数学失败。旧日志无新版字段时不补造字段或改成绩，研究报告标记 legacy-strict-warnings-v1。
