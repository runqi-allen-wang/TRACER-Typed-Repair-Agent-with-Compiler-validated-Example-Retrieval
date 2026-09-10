# Feedback Adoption v1：反馈采纳与动态检索审计

Feedback Adoption v1 是一个离线轨迹分析层。它回答“下一轮发生了什么变化”，但不会把可观察变化直接解释为模型内部的因果采纳。

## 记录内容

对同一 `run_id` 的相邻轮次，分析器记录：

- 错误类别是否变化；
- 候选文本是否变化；
- 改动是否触及上一轮结构化诊断中的未知标识符、期望类型或目标词；
- 当前轮是否来自缓存；
- 反馈是可转换、为空、转换失败还是基础设施错误；
- 检索查询、Top-k 路径及排序是否变化；
- 静态检索与诊断驱动检索分别统计变化率。

`relevant_change` 只表示候选文本改动与诊断信号存在可审计重合。它不是“模型理解了反馈”的心理或因果结论。`changed_without_signal_match` 也不等于改动无效，因为词法分析不能覆盖所有等价 Lean 修复。

## 使用方法

```powershell
python src/feedback_adoption.py results/research-run-001 --out results/research-run-001/feedback-adoption.json
```

输入可以是单个 `runs.jsonl`，也可以是包含多个任务轨迹的研究目录。分析器逐文件保持任务边界，不把不同 `run_id` 拼接为多轮轨迹。

现有 `src/research.py report` 也会在新报告中给出：

- `feedback_relevant_change_rate`；
- `repeated_error_category_rate`；
- `retrieval_query_change_rate`；
- `retrieval_top_k_change_rate`。

历史轨迹缺少 `feedback_payload` 时会标记 `not_recorded`，不会倒推成“反馈已送达”。缓存命中单列为 `cache_reuse`，不得作为新一轮模型生成。

## 当前证据边界

仓库内单元与端到端测试验证了未知标识符修复、候选不变、缓存复用、静态查询不变和动态查询/Top-k 变化等离线场景。当前没有基于新协议完成的真实 provider 配对结果，因此不能据此宣称反馈或动态检索提高成功率。
