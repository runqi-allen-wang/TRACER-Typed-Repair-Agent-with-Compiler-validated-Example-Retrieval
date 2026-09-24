# TRACER Pilot Report

- Experiment ID: `pilot-20260826T122354Z-d628742d`
- Status: **FORMAL**
- Cache hits: `0`
- Provider configuration: `{"input_price_per_1k": null, "max_tokens": 12000, "model": "deepseek-v4-pro", "output_price_per_1k": null, "provider": "openai_compatible", "temperature": 0.0, "url": "https://api.deepseek.com/chat/completions"}`
- Candidate policy: `{"environment": "minimal", "meta_execution": "blocked", "version": "tracer-candidate-v1"}`

## 汇总

| 条件 | 题数 | pass@1 | Wilson 95% CI | pass@3 | Wilson 95% CI | 平均轮次 | 平均编译毫秒 | 平均总 token | 估算成本 |
|---|---:|---:|---|---:|---|---:|---:|---:|---:|
| A | 18 | 18/18 (100.0%) | [82.4%, 100.0%] | 18/18 (100.0%) | [82.4%, 100.0%] | 1.00 | 1416.5 | 1750.4 | unknown |
| B | 18 | 16/18 (88.9%) | [67.2%, 96.9%] | 18/18 (100.0%) | [82.4%, 100.0%] | 1.11 | 1107.7 | 1841.9 | unknown |
| C | 18 | 18/18 (100.0%) | [82.4%, 100.0%] | 18/18 (100.0%) | [82.4%, 100.0%] | 1.00 | 1065.3 | 2906.1 | unknown |

## 解释边界

- 18 道题是工作流 pilot，不构成通用自动定理证明能力或 SOTA 证据。
- C 条件的本地示例与部分评测题高度相似，泄漏风险必须逐题人工复核。
- 只有状态为 FORMAL、完整保留对应 JSONL 与 proof artifacts 的报告才能用于正式结论。
