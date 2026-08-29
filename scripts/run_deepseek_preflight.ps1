[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][double]$BudgetUsd,
    [Parameter(Mandatory=$true)][string]$Out,
    [string]$Python = 'C:\anaconda\python.exe'
)
$ErrorActionPreference = 'Stop'
$ResearchRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ResearchRoot
if (-not (Test-Path -LiteralPath $Python)) { throw '找不到 Python，请用 -Python 指定解释器。' }
if ($BudgetUsd -le 0 -or [double]::IsNaN($BudgetUsd) -or [double]::IsInfinity($BudgetUsd)) { throw '预算必须是有限正数。' }
if (Test-Path -LiteralPath $Out) { throw '输出目录已经存在，拒绝重复付费运行或覆盖旧结果。' }
$LeanTools = Join-Path $env:USERPROFILE '.elan\bin'
if (Test-Path -LiteralPath $LeanTools) {
    $env:ELAN_HOME = Join-Path $env:USERPROFILE '.elan'
    $env:PATH = $LeanTools + ';' + $env:PATH
}
$env:PYTHONIOENCODING = 'utf-8'
$Host.UI.RawUI.WindowTitle = 'TRACER - DeepSeek API 隐藏输入与预跑'
Write-Host 'DeepSeek Flash + Pro：48 个 B 组任务，最多 144 次请求。'
Write-Host '本次使用 tracer-proof-v2：完整证明替换、截断单列、普通警告单列；不得与旧批次混合。'
Write-Host "保守费用预留上限：$BudgetUsd 美元；不是供应商硬账单限额。"
Write-Host '请只在下方 API key 提示处粘贴密钥并回车；不回显、不保存密钥。'
& $Python -u -B src/research.py run --config experiments/research.deepseek.preflight.json --out $Out --api-key-prompt --max-calls 144 --max-reserved-usd $BudgetUsd
$ResearchExit = $LASTEXITCODE
Write-Host "预跑进程退出码：$ResearchExit。请勿为追求全通过而重复运行；已有轨迹留待核对。"
if ($ResearchExit -eq 0) {
    & $Python -B src/research.py report --run $Out
} elseif (Test-Path -LiteralPath (Join-Path $Out 'plan.json')) {
    & $Python -B src/research.py report --run $Out --allow-partial
}
Write-Host '可以回到聊天告知已输入密钥或提供非敏感状态；不要粘贴密钥。'
