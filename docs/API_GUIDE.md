# 模型 API 使用指南

核对日期：2026-08-28。本指南以当前 `src/provider.py`、`src/agent.py`、`src/evaluate.py` 和 `src/api_server.py` 为准。示例经过参数与请求结构核对，不代表已经替你调用各家 API；账号权限、余额与服务可用性需通过一次单题运行确认。

## 1. 当前支持的接口

内置 `openai_compatible` provider 支持非流式 **Chat Completions** 和 **Responses API**。Chat 模式发送 `model/messages/temperature/max_tokens` 并读取 `choices[0].message.content`；Responses 模式发送 `model/input/max_output_tokens/reasoning/store` 并读取 `output[].content[].text`。两种模式都通过 `Authorization: Bearer` 认证。

| 服务 | `--api-url` 完整请求地址 | `--model` 示例 | 示例输出预算 |
| --- | --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-v4-pro` | `12000` |
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-v4-flash` | `12000` |
| OpenAI GPT | `https://api.openai.com/v1/chat/completions` | `gpt-4.1` | `4000` |
| AI4Math yxai Responses | `https://yxai.chat/v1`（配合 `--wire-api responses`） | `gpt-5.6-sol` | 按冻结实验配置 |
| 其他兼容服务 | 服务商提供的完整 Chat Completions 地址 | 该服务实际可用的模型 ID | 按该模型限制设置 |

这些预算不是模型最低要求，也不保证证明成功。GPT-4.1 是适配现有请求结构的示例，并非“最新或最佳模型”的判断。DeepSeek 接口及模型名见[官方快速开始](https://api-docs.deepseek.com/)；GPT-4.1 的端点与模型信息见[官方模型页](https://developers.openai.com/api/docs/models/gpt-4.1)。

重要限制：

- Chat 模式地址应为完整端点；Responses 模式显式传 `--wire-api responses` 时可给 `/v1` base URL，provider 会追加 `/responses`。不要粘贴 Markdown 的 `[网址](网址)` 包装。
- `--reasoning-effort` 仅用于 Responses；`--disable-response-storage` 会发送 `store=false`。不要假设所有兼容服务都支持这些字段。
- 不能把示例模型名任意替换为其他模型。部分模型需要不同输出预算字段或不接受温度参数；应先核对对应协议。Chat 模式仍使用 `max_tokens`，Responses 模式使用 `max_output_tokens`。
- 需要其他协议时，可实现 `--provider command` 适配器：标准输入接收 `{"prompt":"..."}`，标准输出返回 `{"candidate":"by ...","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}`。诊断写标准错误；不得把密钥写入命令字符串、候选或日志。当前命令 provider 默认超时为 60 秒。
- 只把密钥发送给你确认可信的服务商；第三方兼容服务不等同于 OpenAI 官方服务。账号订阅或网页能使用某模型，不足以证明该 API 账号能调用同名模型。

## 2. 环境准备与密钥输入

以下命令都在仓库根目录运行，需要已安装项目指定的 Lean/Lake 和可用的 Python。

```text
python -m pip install -r requirements.txt
lake build
```

PowerShell 可设置 `$env:ELAN_HOME = Join-Path $env:USERPROFILE ".elan"`。若 `python` 不在 PATH，使用你已安装依赖的解释器；Git Bash 中调用带空格的解释器路径时加双引号。

默认使用 `--api-key-prompt`：在提示出现后粘贴密钥，不要把它写在命令行、文档、脚本或提交信息里。单题 CLI 读取后会显示长度和末四位，正式评测只显示“已读取 API key”；分享截图前也应遮住末四位。以下示例均不需要将完整密钥保存到文件。

## 3. 先跑一题：DeepSeek

下面是单行命令，PowerShell 与 Git Bash 都可以复制执行。不要复制终端的 `PS ...>`、`>>` 或 `$` 提示符。

```text
python src/agent.py solve --file lean_project/Benchmarks/Evaluation18.lean --theorem Eval18.and_swap_eval --condition B --provider openai_compatible --api-url https://api.deepseek.com/chat/completions --model deepseek-v4-pro --temperature 0 --max-tokens 12000 --api-key-prompt --max-rounds 3 --timeout 60
```

使用 Flash 时，只将 `--model deepseek-v4-pro` 改成 `--model deepseek-v4-flash`，并输入对应 DeepSeek 账号的密钥。

当前 DeepSeek V4 默认启用思考模式；该模式下 `temperature` 为兼容参数，传入也不生效。TRACER 未显式设置 `thinking` 或 `reasoning_effort`，因此使用服务端默认值；不能把日志中的 `temperature: 0` 写成“推理完全确定”的保证。TRACER 使用最终 `content` 作为证明，不把 `reasoning_content` 当作证明正文。参见[DeepSeek 思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 4. 先跑一题：OpenAI GPT

使用 OpenAI 官方 API 的密钥，不要沿用 DeepSeek 的密钥：

```text
python src/agent.py solve --file lean_project/Benchmarks/Evaluation18.lean --theorem Eval18.and_swap_eval --condition B --provider openai_compatible --api-url https://api.openai.com/v1/chat/completions --model gpt-4.1 --temperature 0 --max-tokens 4000 --api-key-prompt --max-rounds 3 --timeout 60
```

正式实验可以使用账号支持的固定模型版本，减少别名变化带来的影响。是否可调用以及具体限额以账号和官方文档为准；本指南不宣称已在你的 OpenAI 账号上测试成功。

## 5. 环境变量方式：两个终端不要混用语法

每次显式写 URL 与模型最不容易混淆；也可以在**将要执行 Python 的同一终端**设置非敏感配置。

PowerShell，DeepSeek 示例：

```powershell
$env:LEAN_PROOF_API_URL = "https://api.deepseek.com/chat/completions"
$env:LEAN_PROOF_MODEL = "deepseek-v4-pro"
$env:LEAN_PROOF_TEMPERATURE = "0"
$env:LEAN_PROOF_MAX_TOKENS = "12000"
python src/agent.py solve --file lean_project/Benchmarks/Evaluation18.lean --theorem Eval18.and_swap_eval --condition B --provider openai_compatible --api-key-prompt --max-rounds 3 --timeout 60
```

Git Bash，OpenAI GPT 示例：

```bash
export LEAN_PROOF_API_URL="https://api.openai.com/v1/chat/completions"
export LEAN_PROOF_MODEL="gpt-4.1"
export LEAN_PROOF_TEMPERATURE="0"
export LEAN_PROOF_MAX_TOKENS="4000"
python src/agent.py solve --file lean_project/Benchmarks/Evaluation18.lean --theorem Eval18.and_swap_eval --condition B --provider openai_compatible --api-key-prompt --max-rounds 3 --timeout 60
```

变量赋值没有输出是正常现象。`$env:...` 属于 PowerShell，`export` 属于 Git Bash；PowerShell 续行符是反引号，Bash 续行符是反斜杠。本指南优先使用单行运行命令，避免续行粘贴错误。

如果 Git Bash 中的 Python 提示无法隐藏输入，停止该次输入，改用 PowerShell 的 `--api-key-prompt`；不要改成回显完整密钥。已有安全注入环境变量的自动化流程可使用 `LEAN_PROOF_API_KEY` 并省略提示参数，或通过标准输入配合 `--api-key-stdin`；不要同时使用两种输入参数。

配置对应关系：

| CLI 参数 | 环境变量 | 未显式设置时 |
| --- | --- | --- |
| `--api-url` | `LEAN_PROOF_API_URL` | 必填 |
| `--model` | `LEAN_PROOF_MODEL` | `gpt-4.1-mini`，建议总是显式指定 |
| `--temperature` | `LEAN_PROOF_TEMPERATURE` | `0`，是否生效由服务端决定 |
| `--max-tokens` | `LEAN_PROOF_MAX_TOKENS` | `800`，不建议直接用作推理模型完整评测预算 |
| `--wire-api` | `LEAN_PROOF_WIRE_API` | 根据 URL 推断，建议 Responses 实验显式指定 |
| `--reasoning-effort` | `LEAN_PROOF_REASONING_EFFORT` | 未设置；仅 Responses 使用 |
| `--disable-response-storage` | `LEAN_PROOF_DISABLE_RESPONSE_STORAGE` | `false`；隐私敏感实验应显式关闭存储 |
| `--api-key-prompt` / `--api-key-stdin` | `LEAN_PROOF_API_KEY` | 必须安全提供一种密钥来源 |

显式 CLI 配置优先于环境变量。更换服务商时同时更换 URL、模型和密钥，避免只改其中一项。

## 6. 正式 18 × 3 实验

单题验证成功后再运行完整 A/B/C。以下二选一，**不要连续运行两条后才导出结果**：

DeepSeek：

```text
python src/evaluate.py --provider openai_compatible --api-url https://api.deepseek.com/chat/completions --model deepseek-v4-pro --temperature 0 --max-tokens 12000 --api-key-prompt --conditions A,B,C --max-rounds 3 --timeout 60 --fresh
```

OpenAI GPT：

```text
python src/evaluate.py --provider openai_compatible --api-url https://api.openai.com/v1/chat/completions --model gpt-4.1 --temperature 0 --max-tokens 4000 --api-key-prompt --conditions A,B,C --max-rounds 3 --timeout 60 --fresh
```

每个模型完成一批后，先复核、生成报告并导出到独立目录，再运行另一个模型。`--fresh` 会归档上一批结果和复核表；它不表示“保留旧复核并自动用于新实验”。详细步骤见 [真实实验操作说明](REAL_PILOT_GUIDE.md)。

- 同一批 A/B/C 必须保持模型、请求参数、轮数与预算一致；不同模型使用不同批次，不拼接日志来生成更高通过率。
- 上述 12000 与 4000 是启动示例，不构成等预算模型对比；若比较模型，应预先约定预算，并披露推理模式与服务端默认行为。
- 最大三轮不等于每题都运行三轮；成功会停止，provider 错误也会提前停止。
- 增大 token 预算不保证修复成功。候选为空可能来自额度、响应结构或输出截断，不能仅凭空文本判断预算不足。
- `--timeout 60` 控制 Lean 编译，不是模型网络超时。当前 HTTP provider 每次网络等待为 90 秒，连接/超时异常最多尝试三次；HTTP 错误不会按该循环自动重试。
- 不知道价格就不设置 `LEAN_PROOF_INPUT_PRICE_PER_1K` / `LEAN_PROOF_OUTPUT_PRICE_PER_1K`；写 `0` 表示明确指定零价格，不是“未知”。模型账单可能区分缓存和推理等类别，当前两项费率只产生估算，不代替账单。

## 7. 本地 HTTP 接口

终端一启动服务，工作目录保持在仓库根目录：

```text
python src/api_server.py --host 127.0.0.1 --port 8765
```

终端二使用 PowerShell 安全输入密钥并请求，示例为 DeepSeek。要用 GPT，改为上表中的 OpenAI URL、模型和预算，同时输入 OpenAI 密钥。

```powershell
$secureKey = Read-Host "API key（不回显）" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $requestBody = @{
    file = "lean_project/Benchmarks/Evaluation18.lean"
    theorem = "Eval18.and_swap_eval"
    condition = "B"
    api_url = "https://api.deepseek.com/chat/completions"
    api_key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
    model = "deepseek-v4-pro"
    temperature = 0
    max_tokens = 12000
    max_rounds = 3
    timeout = 60
  } | ConvertTo-Json
  Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/solve" -ContentType "application/json" -Body $requestBody
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
  Remove-Variable requestBody,secureKey,keyPtr -ErrorAction SilentlyContinue
}
```

`GET /health` 是健康检查；`POST /solve` 的必填字段为 `file`、`theorem`、`condition`、`api_url`、`api_key`、`model`。可选字段为 `temperature`、`max_tokens`、`max_rounds`、`timeout`、`examples_dir`、`cache`、`output_dir`、`log`。相对路径按服务器工作目录解析。

本地服务没有访问鉴权，不要监听公网、设置端口转发或交给不可信客户端使用。请求体中的密钥会在内存中处理，因此不要打印 `$requestBody`；清除变量也不等于操作系统级内存擦除保证。

## 8. 故障排查

| 现象 | 下一步 |
| --- | --- |
| 缺少 API URL / KEY | 检查是否在同一终端设置；推荐显式 URL、模型和 `--api-key-prompt` |
| HTTP 401 / 403 | 检查密钥、目标服务、账号权限；不要贴完整密钥求助 |
| HTTP 400 / 404、模型不存在 | 核对完整端点、模型 ID 和请求字段；模型参数不能跨接口照搬 |
| HTTP 429 | 查看额度、余额和限流；勿把这批基础设施失败当作证明失败结论 |
| 网络超时 | 检查网络/代理及服务状态；提高 Lean 的 `--timeout` 不会延长 API 等待 |
| `compile_ok: false` 且 `diagnostic.category` 为 `syntax/type/goal` | 检查 Lean 候选与诊断，不等于 API 密钥错误 |
| `provider_error` | 查看该字段的脱敏错误；尚不能形成有效编译反馈 |
| C 条件语料重合 | 修正评测题与检索例子的泄漏，不要绕过预检 |
| 单题缓存命中 | 此次不一定发出新请求；正式实验使用 `evaluate.py --fresh`，不要加 `--reuse-cache` |

单题轨迹在 `results/agent_runs.jsonl`，正式实验轨迹在 `results/real_pilot_runs.jsonl`。只分享经过 `scripts/export_pilot.py` 导出的材料，不强制上传原始日志或 SQLite。
