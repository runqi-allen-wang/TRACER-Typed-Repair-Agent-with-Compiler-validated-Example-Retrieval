# 项目概览

TRACER（Typed Repair Agent with Compiler-validated Example Retrieval）是面向 Lean 4 局部证明修复的工程与评测框架。它把模型生成、编译器反馈、本地示例检索、持久缓存和可追踪评测连接成同一条受控链路。

## 核心组件

1. `src/agent.py`：实现 provider 驱动的求解 CLI 和有限轮反馈循环。
2. `src/compiler.py`：隔离源文件补丁，并选择目标文件所属的 Lean/Lake 环境。
3. `src/provider.py`：支持 OpenAI 兼容接口、命令行 provider 和测试专用 mock；统一清洗模型代码围栏。
4. `src/retriever.py`：为条件 C 提供本地示例上下文。
5. `src/cache.py`：使用 SQLite 持久保存精确请求与候选结果。
6. `src/evaluate.py`：运行冻结的 18 题三条件 pilot。
7. `src/report.py`：计算通过率、Wilson 区间、token/成本汇总和题型分析。
8. `src/leancapsule/`：打包、回放和发布审计可复现的 Lean 失败工件。
9. `CHANGELOG.md`：记录影响安全、实验协议和发布审计的补丁。

## 当前验证状态

- 18 个 benchmark 任务对应 18 个 Lean 定理声明。
- 49 项单元、端到端与文档一致性测试通过。
- 成功候选会保存为可独立再次编译的隔离文件。
- 修复过程中原始 benchmark 源文件保持不变。
- OpenAI 兼容 provider 的错误正文、非敏感配置、usage 和 Lean 诊断均可追踪。
- 仓库不内置正式模型 pilot 结论；配置真实 provider 并完成复核后才能形成实验结果。

## 可复现实验

```powershell
python -m unittest discover -s tests -v
lake build
python src/evaluate.py --provider openai_compatible --conditions A,B,C --fresh
python src/report.py
```

最后两条命令需要真实 provider。发布实验结论时，必须同时提供生成的 JSONL 轨迹、汇总结果和填写完成的 `results/manual_review.csv`。
