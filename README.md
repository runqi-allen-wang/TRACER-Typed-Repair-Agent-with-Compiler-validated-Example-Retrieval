# TRACER / LeanCapsule

TRACER 是一个由 Lean 编译器验证的证明修复与失败工件工具。LeanCapsule 是其中面向社区复现的核心协议：它把 Lean 文件、工具链、项目配置和规范化诊断打包成可回放的 capsule。

仓库同时保留两条互补路径：

- `leancapsule`：生成、回放、批量验收和渲染 Lean 失败工件；
- `src/agent.py`：使用编译反馈和本地示例进行局部证明修复。

## 快速开始

建议在已经安装 Lean、Lake 和 Python 的环境中运行：

```powershell
python -m pip install -r requirements.txt
lake build
python -m unittest discover -s tests -v
```

生成一个本地 capsule。示例输出放在忽略目录中，不会覆盖 `capsules/` 下已经发布和审计的工件：

```powershell
python -m leancapsule pack `
  --project . `
  --file examples/capsule_failures/unknown_identifier.lean `
  --lines 1:7 `
  --out results/work/unknown-identifier
```

回放该本地工件：

```powershell
python -m leancapsule replay results/work/unknown-identifier
```

验收仓库中的公开 gallery：

```powershell
python -m leancapsule replay capsules/std/unknown-identifier
python -m leancapsule verify capsules
python -m leancapsule audit capsules
python -m leancapsule issue capsules/std/unknown-identifier --out issue.md
python -m leancapsule gallery capsules --out capsules/index.json
```

所有命令都输出机器可读 JSON；`replay`、`verify`、`audit` 和 `gallery` 会用进程退出码表示是否通过。Mathlib 冷启动可能需要较长时间，因此回放默认超时为 180 秒。

使用 `--theorem` 时，工具会先尝试保留 imports、namespace 和目标定理的 standalone 文件；如果编译结果与原始诊断不一致，就自动退回完整文件。standalone 成功后会在固定编译预算内逐个尝试删除 imports，也可以使用 `--no-minimize-imports` 关闭。

## 公开失败 gallery

仓库当前包含 24 个可回放 capsule，覆盖四类失败：`Name / import`、`Type / application`、`Elaboration / instance` 和 `Goal / scope`，每类至少 3 个；来源覆盖 Std、Mathlib 和 project-local，每类来源至少 4 个。`capsules/index.json`、`capsules/index.csv` 和 `capsules/index.md` 是由 CLI 生成的三种 gallery 索引，`capsules/MANUAL_REVIEW.csv` 记录逐案例的语义、来源和敏感内容复核结论。

发布审计会检查必需文件、manifest、冻结分类、来源许可、绝对本机路径、疑似敏感凭据、成功案例中的未完成证明以及复核台账完整性。CI 会在构建和全量回放前强制运行该审计。

Mathlib 案例使用独立的 `mathlib_project/` 依赖工程。首次回放前请执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_mathlib.ps1
```

`-ExecutionPolicy Bypass` 只应用于这一个子进程，不修改系统策略。Linux/macOS 可执行 `bash scripts/setup_mathlib.sh`。两个脚本都会设置稳定的 Mathlib 缓存目录，并在 `lake` 返回非零退出码时失败。该步骤会按 `mathlib_project/lakefile.lean` 中的固定版本下载依赖和预编译缓存；依赖缓存不纳入仓库。没有网络或未准备缓存时，Std 与 project-local 案例仍可独立回放，Mathlib 案例会明确报告缺少依赖环境。

## 证明修复 Agent

目标文件可以包含 `-- PROOF_START` / `-- PROOF_END` 标记，也可以包含唯一的 `sorry` 占位符。原文件不会被覆盖，成功的隔离证明会保存到 `results/solutions/`。

```powershell
python src/agent.py solve `
  --file lean_project/Benchmarks/Evaluation18.lean `
  --theorem Eval18.and_swap_eval `
  --condition B `
  --provider mock `
  --mock-candidate "by intro h; exact And.intro h.right h.left"
```

## AxProverBase CapsuleFeedback（Part 2）

`leancapsule.feedback.CapsuleFeedback` 可以直接消费 AxProverBase 已有的 Builder 返回值，生成错误类别、稳定指纹、重复次数、诊断漂移和有界历史。该步骤不会再次运行 Lean，也不会调用 LLM。

```python
from leancapsule.feedback import CapsuleFeedback

capsule = CapsuleFeedback()
build_success, message = await check_lean_file(...)
feedback = capsule.observe_ax((build_success, message), round_no=1)
```

Part 1/2/3 中 AxProverBase 涉及的模型调用统一冻结为 DeepSeek Flash：Ax/LangChain 模型名 `openai:deepseek-v4-flash`，官方模型 ID `deepseek-v4-flash`，`base_url=https://api.deepseek.com`。具体接入步骤、JSON CLI 和验收标准见 [`docs/part2_capsule_feedback.md`](docs/part2_capsule_feedback.md)。

## 直接输入 API 配置

单次运行可以在命令行输入接口地址、模型，并通过安全提示输入密钥。输入时终端不会显示密钥；读取完成后只确认成功，不显示长度、末四位或任何密钥字符。完整密钥只存在于当前进程内，不写入日志和缓存：

```powershell
python src/agent.py solve `
  --file input.lean `
  --theorem Demo.target `
  --condition B `
  --provider openai_compatible `
  --api-url "https://example.invalid/v1/chat/completions" `
  --model "your-model" `
  --api-key-prompt
```

DeepSeek 等提供 OpenAI 兼容聊天接口的服务也可以直接使用。例如：

```powershell
python src/agent.py solve `
  --file lean_project/Benchmarks/Evaluation18.lean `
  --theorem Eval18.and_swap_eval `
  --condition B `
  --provider openai_compatible `
  --api-url "https://api.deepseek.com/chat/completions" `
  --model "your-deepseek-model" `
  --temperature 0 `
  --max-tokens 2000 `
  --api-key-prompt `
  --max-rounds 3
```

模型名称必须替换为账户实际可用的名称。远程 provider 必须使用 HTTPS，认证头只允许跟随同源重定向；错误响应只读取有界的结构化消息并在日志前脱敏。模型返回值只有在整个响应由单个 Markdown `lean`/`lean4`/`text` 代码围栏包裹时才移除围栏，Lean 字符串内部或带额外说明的反引号不会被误删；旧缓存候选遵循相同规则。

模型候选只允许局部证明项。`run_tac` 等元编程执行入口、`#eval` 和额外顶层命令会在调用 Lean 前被拒绝；Lean 子进程使用不含 `LEAN_PROOF_API_KEY`、token、cookie 或其他父进程变量的最小环境和临时 HOME。该边界保护冻结基准上的模型候选，但不是通用操作系统容器：项目源文件、导入模块和自定义 tactic 本身仍必须可信。

### 如何判断失败位置

- 出现 `provider_error`：请求尚未进入 Lean 编译阶段，应检查接口地址、密钥、模型名、额度或代理。
- 出现 `diagnostic.category = syntax/type/goal`：模型请求已经成功，失败来自候选证明的 Lean 编译结果。
- `compile_ok: false` 本身不代表 API 损坏；应同时阅读 `diagnostic`。
- 每轮详细候选、缓存命中、模型 usage 和编译诊断记录在 `results/agent_runs.jsonl`。
- 成功证明保存到 `results/solutions/`；持续失败的最后候选保存到 `results/solutions/failures/`。

## 正式 A/B/C 实验

完整实验运行冻结的 `18` 道题和 `A/B/C` 三个条件，共 `54` 个任务。请在专用 PowerShell 会话中固定以下配置；URL 必须是接口实际接受的完整 Chat Completions 地址：

```powershell
$env:LEAN_PROOF_API_URL = "https://example.invalid/v1/chat/completions"
$env:LEAN_PROOF_MODEL = "your-model"
$env:LEAN_PROOF_TEMPERATURE = "0"
$env:LEAN_PROOF_MAX_TOKENS = "800"

$secureKey = Read-Host "API Key" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $env:LEAN_PROOF_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
}
finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
}

try {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_all.ps1 `
    -ApiUrl $env:LEAN_PROOF_API_URL `
    -Model $env:LEAN_PROOF_MODEL `
    -Temperature 0 `
    -MaxTokens 800
}
finally {
  Remove-Item Env:LEAN_PROOF_API_KEY -ErrorAction SilentlyContinue
  Remove-Variable secureKey,keyPtr -ErrorAction SilentlyContinue
}
```

`run_all.ps1` 先执行 `lake build` 和 Python 测试，再让 `evaluate.py --fresh` 归档旧实验状态并使用空请求缓存运行。运行条件 C 前会检查检索示例与 18 个冻结声明是否相同（允许变量改名）；发现重合会在归档旧实验或调用 provider 前终止。默认严格模式不允许新实验出现缓存命中；`-ReuseCache` 仅用于调试或成本受限的复跑，不得称为严格 fresh pilot。实验执行完成后会校验 54 个任务、轮次、单一 provider 配置、候选安全策略、provider/任务错误和缓存状态，然后生成明确标为未复核的草稿报告。

人工逐项填写 `results/manual_review.csv` 后，执行最终门禁和报告：

```powershell
python scripts/validate_pilot.py --require-manual-review
python src/report.py
python scripts/export_pilot.py --out results/handoff/pilot-reviewed
```

不得批量填充或推断人工复核结果。每个成功证明的 `kernel_pass`、`inappropriate_assumption`、`leakage_risk` 必须填写 `yes` 或 `no`，并写明 `reviewer_note`；正式结果只接受 `kernel_pass=yes`、`inappropriate_assumption=no`、`leakage_risk=no`。导出命令在复核缺失、实验不完整、严格运行包含缓存命中或检测到疑似凭据时拒绝生成工件。

运行日志、请求缓存、solutions、归档和 handoff 目录默认被 `.gitignore` 排除。`real_pilot_runs.jsonl` 还可能包含本机绝对路径，不应直接提交；`export_pilot.py` 会结构化清理仓库目录、用户目录和临时目录路径，并且不会复制 SQLite 缓存。检查导出目录后，如确实要通过 Git 交接，请使用 `git add -f results/handoff/pilot-reviewed` 显式选择该目录。更完整的文件说明见 [`results/README.md`](results/README.md)。

也可以使用本地 HTTP 接口：

```powershell
python src/api_server.py --host 127.0.0.1 --port 8765
```

向 `POST /solve` 发送 JSON，字段包括 `file`、`theorem`、`condition`、`api_url`、`api_key` 和 `model`。服务默认只监听本机，请勿直接暴露到公网。请求体不会写入服务日志，且限制为 64 KiB；异常返回会移除请求中的密钥。

PowerShell 请求示例：

```powershell
$body = @{
  file = "lean_project/Benchmarks/Evaluation18.lean"
  theorem = "Eval18.and_swap_eval"
  condition = "B"
  api_url = "https://example.invalid/v1/chat/completions"
  api_key = "在本地粘贴密钥"
  model = "your-model"
  max_rounds = 3
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/solve -ContentType "application/json" -Body $body
```

## 仓库结构

```text
src/leancapsule/       capsule 的打包、回放、验收和 issue 渲染
src/agent.py           编译反馈证明修复 Agent
src/api_server.py      本地 HTTP API
capsule_schema/        manifest 结构说明
capsules/               可公开回放的示例工件
examples/               检索示例与失败输入
lean_project/           Lean 测试项目
tests/                  Python 自动化测试
scripts/                环境准备与复现实用脚本
docs/                   方法、格式和贡献说明
PROGRESS.md             唯一的当前工作进度记录
```

## 设计边界

- capsule 核心不依赖模型或 API；Agent 只是可选消费者。
- 当前支持经过编译验证的 theorem standalone 和完整文件 fallback；多文件依赖切片和数学意义上的全局最小化尚未承诺。
- 诊断比较使用可读的规范化文本 `diagnostic_key`，并保留原始诊断供人工审计。
- API 密钥不进入 JSONL、SQLite、候选文件、manifest 或错误响应。
- Provider 返回的 Markdown 代码围栏会在解析边界和编译边界各清洗一次，兼容历史缓存。
- 仓库中的实验结果不能替代正式的模型对比实验；正式实验必须记录模型配置、token、延迟和人工复核。

## 贡献

请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [docs/CAPSULE_FORMAT.md](docs/CAPSULE_FORMAT.md)，为每个公开 capsule 补充来源、许可、预期诊断和回放结果。
