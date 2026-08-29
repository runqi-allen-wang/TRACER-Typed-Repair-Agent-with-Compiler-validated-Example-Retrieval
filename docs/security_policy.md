# SP 安全策略回归

SP 类用于保存“Lean 可能接受、但会破坏逻辑可信性或违反候选策略”的恶意候选。它是独立的编译前安全门禁，不是证明实验条件，因此不会改变冻结的 18 题 × 3 条件＝54 项历史实验口径，也不会与 repair24 研究中表示“只检索、不反馈”的 R-D 混淆。

## SP-1：Unsafe construction of `False` after disabling positivity check

案例文件：`benchmarks/security/unsafe_inductive_false.lean`。

该候选通过 `unsafe inductive` 绕过 inductive positivity 约束，并构造 `False`。TRACER 必须在调用 Lean 前拒绝它，结果类别必须为 `unsafe_candidate`。

保护边界包括：

- Agent 候选检查：不得进入 `compile_candidate`；
- AxProverBase：共享首轮缓存、后续 LLM `ProposalMessage` 和 Builder 前置防线都必须执行安全校验；
- 完整 theorem：目标名称和声明头必须与原题一致，只允许一个顶层 theorem/lemma；
- Capsule `pack`：不得发布含不安全声明的源码；
- Capsule `replay`：不得执行含不安全声明的回放源；
- Gallery `audit`：必须报告含不安全声明的 Capsule；
- 候选策略：`tracer-candidate-v2` 明确记录 `unsafe_declarations=blocked`；
- Part 1/Part 2 配对门禁：两组必须逐题记录并共享同一份 v2 候选策略。

运行专项回归：

```powershell
python -m unittest tests.test_security_cases -v
```

新增安全案例时，在 `benchmarks/security/manifest.json` 中增加 `SP-n` 条目，并提供独立候选文件。所有安全案例都必须声明 `expected_policy=reject_before_compile`，不能依赖 Lean 编译后的失败来实现安全门禁。
