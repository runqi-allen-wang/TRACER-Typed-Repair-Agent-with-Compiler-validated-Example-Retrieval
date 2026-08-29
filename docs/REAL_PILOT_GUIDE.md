# 真实 54 题 Provider Pilot 操作说明

本说明用于运行冻结的 18 道 Lean 题目在 A、B、C 三种条件下的真实 provider 实验。总任务数为 `18 × 3 = 54`。实验不会修改原始题库；每轮候选、编译诊断、token 用量和成功证明都会落盘。

## 1. 准备环境

在 PowerShell 中进入仓库根目录：

```powershell
cd "C:\Users\王润祺\Desktop\LeanProofRepairAgent-整理版\TRACER"
python -m pip install -r requirements.txt
$env:ELAN_HOME = Join-Path $env:USERPROFILE ".elan"
lake build
```

如果 `python` 不在 PATH，可把下面所有 `python` 替换成已经安装依赖的 Python 解释器完整路径。

## 2. 选择模型与安全输入密钥

当前实现支持 OpenAI 兼容的 Chat Completions 与 Responses API；本页 A/B/C 示例仍使用 Chat Completions。Responses 的 wire API、推理强度和存储配置见 [API 使用指南](API_GUIDE.md)。先按该指南完成一题验证，再运行完整实验。

DeepSeek 可选非敏感环境配置：

```powershell
$env:LEAN_PROOF_API_URL = "https://api.deepseek.com/chat/completions"
$env:LEAN_PROOF_MODEL = "deepseek-v4-pro"
$env:LEAN_PROOF_TEMPERATURE = "0"
$env:LEAN_PROOF_MAX_TOKENS = "12000"
```

使用 OpenAI GPT 时，同时切换端点、模型和预算，并在运行时输入 OpenAI 密钥：

```powershell
$env:LEAN_PROOF_API_URL = "https://api.openai.com/v1/chat/completions"
$env:LEAN_PROOF_MODEL = "gpt-4.1"
$env:LEAN_PROOF_TEMPERATURE = "0"
$env:LEAN_PROOF_MAX_TOKENS = "4000"
```

不要把密钥写入 README、脚本、Git 历史或 JSONL。使用 `--api-key-prompt` 后，在提示出现时粘贴密钥即可；不需要提前设置密钥环境变量。

价格未知时保持未配置。若当前终端残留以前的费率，可清除：

```powershell
Remove-Item Env:LEAN_PROOF_INPUT_PRICE_PER_1K -ErrorAction SilentlyContinue
Remove-Item Env:LEAN_PROOF_OUTPUT_PRICE_PER_1K -ErrorAction SilentlyContinue
```

只有掌握实际费率时才设置上述两项，单位是美元 / 1000 token；`0` 表示明确零价格，不能用来表示“未知”。报告金额是估算，不是账单。

## 3. 运行完整真实实验

`--fresh` 会先把旧日志、证明、复核台账、报告和缓存移动到 `results/archive/`，然后开始新的实验批次。旧数据可恢复，不会被覆盖。

下面二选一，单行命令适用于 PowerShell 与 Git Bash。示例显式参数优先于前面的环境变量。

DeepSeek：

```text
python src/evaluate.py --provider openai_compatible --api-url https://api.deepseek.com/chat/completions --model deepseek-v4-pro --temperature 0 --max-tokens 12000 --api-key-prompt --conditions A,B,C --max-rounds 3 --timeout 60 --fresh
```

OpenAI GPT：

```text
python src/evaluate.py --provider openai_compatible --api-url https://api.openai.com/v1/chat/completions --model gpt-4.1 --temperature 0 --max-tokens 4000 --api-key-prompt --conditions A,B,C --max-rounds 3 --timeout 60 --fresh
```

这些预算只是启动示例，不保证成功。若出现疑似截断，应结合服务响应与 usage 判断；决定改变预算后需用 `--fresh` 重跑整批，而不是只替换失败题。DeepSeek 思考模式下温度参数不生效，当前 provider 使用其默认思考配置，不能宣称温度为 0 就完全确定。

比较多个模型时，先完成一个模型的第 4～7 步并导出，再运行另一个模型。同批 A/B/C 配置相同；跨模型对比必须提前约定预算和披露差异，禁止把不同模型的记录拼成一个正式报告。`--timeout` 是 Lean 编译预算，不是模型 API 网络超时。

运行过程结束后应看到一个新的 `experiment_id`。如果出现 `provider_error`、大量 `task_error` 或中途断网，不要把这批结果当作正式实验；修复配置后重新使用 `--fresh` 完整运行。

## 4. 检查原始轨迹和成功证明

```powershell
Get-Content results\real_pilot_runs.jsonl -Tail 1
Get-ChildItem results\solutions -Recurse -Filter *.lean
```

文件含义：

- `results/real_pilot_runs.jsonl`：逐题逐轮原始轨迹，最多 162 条记录；
- `results/solutions/A|B|C/`：通过 Lean 编译的最终隔离证明；
- `results/solutions/failures/`：未成功题目的最后候选；
- `results/manual_review.csv`：54 个题目×条件组合的复核台账。

## 5. 完成人工复核

打开 `results/manual_review.csv`。对每个成功候选至少填写：

- `kernel_pass`：确认独立 Lean 编译通过，填写 `yes`；
- `inappropriate_assumption`：没有不恰当额外假设时填写 `no`；
- `leakage_risk`：没有使用原题答案或不当示例时填写 `no`；
- `reviewer_note`：写一句可追溯备注，例如“独立复编译；仅使用题目上下文”。

失败题目也保留台账行；是否填写其复核字段由研究者决定，但成功题目的字段不能为空。

## 6. 严格校验、生成报告

```powershell
python scripts/validate_pilot.py `
  --runs results/real_pilot_runs.jsonl `
  --manifest benchmarks/manifest.json `
  --review results/manual_review.csv `
  --require-manual-review
if ($LASTEXITCODE -ne 0) { throw "复核或轨迹校验未通过" }
python src/report.py
if ($LASTEXITCODE -ne 0) { throw "报告未生成，不可继续导出" }
```

校验会拒绝：缺少 54 个组合、轮次不连续、成功后仍继续尝试、provider 配置不一致、基础设施错误、缓存命中或候选安全策略不一致。`report.py` 只有在门禁通过后才会生成 `formal` 报告；否则应先修正问题，不要使用 `--allow-*` 选项冒充正式结果。

报告文件包括：

- `results/pilot_report.json`；
- `results/pilot_summary.csv`；
- `results/pilot_failure_types.csv`；
- `results/pilot_topic_summary.csv`；
- `results/pass_at_1.svg` 和 `results/pass_at_3.svg`；
- 根目录 `REPORT.md`。

## 7. 导出可交付实验包

只有严格校验和人工复核通过后才执行：

```powershell
python scripts/export_pilot.py --out published/deepseek-v4-pro-12000-run01
```

导出包包含脱敏后的逐轮 JSONL、54 个组合的复核表、正式报告和成功 `.lean` 文件。导出前会拒绝疑似认证信息，并把本机绝对路径替换为占位路径。输出目录必须不存在，以防止误覆盖旧交付物。

GPT 可使用另一个尚不存在的目录，例如 `published/gpt-4.1-4000-run01`。目录名只是便于阅读，实际批次以日志的 `experiment_id` 为准。需要公开交付时只暂存这次导出的指定目录；`results/archive/`、原始密钥、原始日志和 SQLite 不应强制加入提交。已有历史实验结果不能替代这次新模型实验。

## 8. 最终验收

```powershell
python scripts/validate_pilot.py --require-manual-review
if ($LASTEXITCODE -ne 0) { throw "实验验收未通过" }
python -m leancapsule audit capsules
if ($LASTEXITCODE -ne 0) { throw "Capsule 审计未通过" }
lake build
```

最终交付前确认：`pilot_report.json` 的 `status` 为 `formal`，`cache_hits` 为 `0`，`experiment_id` 全程一致，并且导出包中存在每个成功记录对应的 `.lean` 文件。

第 8 步不重复写入第 7 步已存在的导出目录。Git Bash 不使用 `$LASTEXITCODE`，可以用 `python scripts/validate_pilot.py --require-manual-review && python src/report.py` 在校验通过后生成报告，再按第 7 步导出。
