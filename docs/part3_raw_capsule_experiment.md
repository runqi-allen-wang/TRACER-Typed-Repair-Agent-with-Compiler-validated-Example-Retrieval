# Part 3：Raw 与 CapsuleFeedback 最小严格对比实验

## 研究问题

Part 1 的 Experience 与 Part 2 的 CapsuleFeedback 同时改变了 memory 和失败反馈格式，不能单独说明 CapsuleFeedback 的影响。Part 3 补充一个更窄的对照：两组都使用 `MemorylessProcessor`，只比较 Ax 原始 `BuildFailedFeedback` 与确定性的 `CapsuleFeedback`。另有独立的 `capsule_experience` B 臂用于拆分该混杂因素，但不并入 Raw/Capsule 的主汇总。

结论范围限定为“共享首轮候选条件下的后续修复比较”。这是单模型、单批次的小型 pilot，不是显著性检验，也不代表通用能力或 SOTA 结果。

## 实验条件

| 条件 | Memory | 编译失败反馈 | 首轮候选 |
| --- | --- | --- | --- |
| Experience（参考） | `ExperienceProcessor` | 原始 Ax 流程 | Part 1 已有结果 |
| B 混杂拆分臂（独立） | `ExperienceProcessor` | 确定性的 `CapsuleFeedback` | 见独立 B handoff |
| Raw | `MemorylessProcessor` | 原始 `BuildFailedFeedback` 原样传给下一轮 Proposer | 与 Capsule 完全共享 |
| Capsule | `MemorylessProcessor` | 确定性的 `CapsuleFeedback` | 与 Raw 完全共享 |

固定环境和参数如下：

- FATE-M `v4.28.0`，commit `4eb33c8ccd0ff058b461cd763cc406509129743f`；题集为前 25 题。
- AxProverBase commit `06dfadc9ab439755af5efcfe0add95bfef2733c7`。
- AI4Math `yxai` provider，Ax/LangChain 模型名 `openai:gpt-5.6-sol`，endpoint `https://yxai.chat/v1`。
- Responses API，`store=false`，`reasoning.effort=high`。
- `max_iterations=4`、`max_input_tokens=65536`、`max_tool_calling_iterations=1`。
- `search_lean`、`search_web` 和最终 summary 均关闭。
- 两组使用相同的 `tracer-candidate-v2` 候选安全策略；Raw/Capsule 自身的 Memory、额外 LLM 和额外编译调用都必须为零。

首轮候选缓存包含完整的 `code`、`reasoning`、`imports`、`opens` 四个字段。运行前逐字段校验 Raw、Capsule 与 Part 1 记录，首轮候选生成成本不计入 Raw/Capsule 的后续修复成本。为减少时间顺序影响，第奇数题按 `Raw → Capsule` 运行，第偶数题按 `Capsule → Raw` 运行。

运行器在每次题目执行前把选中的 FATE-M 源文件恢复到指定 commit 的 pristine 内容，题目结束后恢复运行前的文件；因此不会把外部 FATE-M 工作区的临时修改写回本仓库。正式运行使用已有的 Lean、Ax 和 Python 环境，不需要重新下载依赖。

## 运行与验收

下面的路径是示例；API key 只通过当前进程环境变量提供，不写入仓库或 `~/.codex/auth.json`：

```powershell
$secureKey = Read-Host "请输入 yxai API Key（输入不会显示）" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$fateFolder = "C:\path\to\FATE-M-v4.28.0"
$runDir = ".\results\work\part3-after-main-90ba62b-20260829\full"
$baseline = ".\results\work\part12-corrected-20260828\baseline-merged-corrected.jsonl"
$cache = ".\results\work\part3-after-main-20260829\part2-first-round.json"
try {
  $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
  $keyPtr = [IntPtr]::Zero
python .\baseline\run_part3.py `
  --baseline $baseline `
  --cache $cache `
  --folder $fateFolder `
  --out-dir $runDir `
  --overwrite
python .\scripts\compare_part3.py `
  --raw "$runDir\raw.jsonl" `
  --capsule "$runDir\capsule.jsonl" `
  --baseline $baseline `
  --cache $cache `
  --errors "$runDir\errors.jsonl" `
  --out-dir .\results\handoff\part3-after-main-90ba62b-20260829
}
finally {
  if ($keyPtr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
  }
  Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
  Remove-Variable secureKey,keyPtr,fateFolder -ErrorAction SilentlyContinue
}
```

`compare_part3.py` 的严格门禁检查：25 个唯一题目、Raw/Capsule 配对字段、共享首轮 Proposal、模型和 endpoint、Responses 配置、预算、安全策略、Memory/额外调用计数，以及未报告的 API/基础设施错误。本次正式交接包为 `results/handoff/part3-after-main-90ba62b-20260829/`；此前的 `part3-after-main-20260829/` 和历史 `part3-minimal/` 仍保留，`results/work/`、Capsule state、metrics 和请求缓存继续忽略。

## 实际结果（合并最新 main 后）

此前 2026-08-28 的 `results/handoff/part3-minimal/` 和随后 `07301eb` 批次的 `results/handoff/part3-after-main-20260829/` 均保留为历史工件。本节报告在 `leiteng` 合并 `origin/main@90ba62b` 后重新执行的批次（2026-08-29），其交接清单中的 `source_revision` 为 `53bc501`；之后 `origin/main@37f12de` 仅加入交接协议、校验器和 CI，并以 `23ec5a3` 合入当前 `leiteng`，未改变运行逻辑，也未伪造新的模型轨迹。正式交接包位于 [`results/handoff/part3-after-main-90ba62b-20260829/`](../results/handoff/part3-after-main-90ba62b-20260829/)。25/25 对齐，配对门禁通过，`errors.jsonl` 为空。共享首轮候选中 16 题首轮成功，9 题首轮失败；后续修复指标应主要看这 9 题：

| 指标 | Raw | Capsule | Capsule - Raw |
| --- | ---: | ---: | ---: |
| 最终成功题数 | 22/25 | 19/25 | -3 |
| 首轮失败后第二轮修复 | 4/9 | 2/9 | -2 |
| 首轮失败后最终修复 | 6/9 | 3/9 | -3 |
| 总轮数 | 43 | 47 | +4 |
| 编译错误次数 | 21 | 28 | +7 |
| Proposer 调用数 | 19 | 22 | +3 |
| Reviewer 调用数 | 22 | 19 | -3 |
| 总 LLM 调用数 | 41 | 41 | 0 |
| 总 token 数 | 400862 | 432548 | +31686 |
| 重复诊断次数 | 0 | 0 | 0 |
| API/基础设施错误 | 0 | 0 | 0 |

因此，在这一次 pilot 中，Raw 的最终成功数为 22/25（88%），Capsule 为 19/25（76%）；在真正有信息量的 9 个首轮失败题上，Raw 最终修复 6 题，Capsule 修复 3 题。两组实际 LLM 调用数相同，但 Capsule 多 4 个总轮次并多消耗 31686 token。这个结果不能推出 CapsuleFeedback 普遍降低性能：后续轮次仍受模型随机性和单次服务时间影响，且每个条件只运行一次。

本次最新 main 批次的 `errors.jsonl` 为空，未发生 API/基础设施错误。更早的 `07301eb` 批次中，`fate24` 的 Capsule 请求收到一次 `502 Bad Gateway`；该批次原始目录 [`results/work/part3-after-main-20260829/full/`](../results/work/part3-after-main-20260829/full/) 及单题重试目录 `full-corrected/` 均保留，历史结果没有被覆盖。该重试仅用于纠正基础设施缺失，不与模型条件效果混为一谈。

Part 1 Experience 结果仅作资源参考：25/25 成功、39 总轮数、14 次编译错误、79 次 LLM 调用、656657 token。它使用 `ExperienceProcessor`，且运行时间不同，不能与 Raw/Capsule 做因果归因或合并成一个三条件结论。

独立 B 混杂拆分臂（`ExperienceProcessor + CapsuleFeedback`）在同一 25 题上通过 20/25，
总轮数 47，LLM 请求 69（其中 Memory 27），编译错误 27，总 token 659791；9 个共享
首轮失败中修复 4 个。该结果来自单独批次，详见
[`part2_capsule_feedback_confound_arm.md`](part2_capsule_feedback_confound_arm.md)及
[`B handoff`](../results/handoff/part2-experience-capsule-20260829/REPORT.md)，不能与
本节 Raw/Capsule 数字直接拼接成四条件结论。

逐题结果、候选和遥测摘要见 [`results/handoff/part3-after-main-90ba62b-20260829/`](../results/handoff/part3-after-main-90ba62b-20260829/)，其中：

- `raw.jsonl`、`capsule.jsonl`：逐题原始交接记录及反馈事件；
- `pairing.json`：严格配对结果和逐题差值；
- `per-task.csv`：便于表格分析的逐题结果；
- `summary.json`、`REPORT.md`：汇总指标和英文交接报告；
- `handoff.json`：交接文件的相对路径、字节数和元数据说明。

SP-1 是独立的安全策略回归，不是 Part 3 的第四个 Agent 条件；其候选在 Lean 编译前拒绝，验证方式见 [`security_policy.md`](security_policy.md)。
