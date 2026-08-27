[CmdletBinding()]
param(
  [string]$PythonCommand = "python",
  [string]$AxDependencies = "",
  [string]$ApiKeyFile = "",
  [string]$ResultPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$axDependenciesPath = $null
if (-not [string]::IsNullOrWhiteSpace($AxDependencies)) {
  $axDependenciesPath = (Resolve-Path (Join-Path $repoRoot $AxDependencies)).Path
}
$keyPtr = [IntPtr]::Zero
$plainKey = $null
$priorLeanKey = $env:LEAN_PROOF_API_KEY
$priorOpenAIKey = $env:OPENAI_API_KEY
$priorPythonPath = $env:PYTHONPATH
$workDir = Join-Path $repoRoot (".live-yxai-smoke-" + [Guid]::NewGuid().ToString("N"))
$finalResult = $null
$stage = "initialization"
$directResult = $null
$directExitCode = $null
$axResult = $null
$axExitCode = $null

function Read-OptionalProperty {
  param(
    [object]$Object,
    [string]$Name
  )
  if ($null -eq $Object) { return $null }
  $property = $Object.PSObject.Properties[$Name]
  if ($null -eq $property) { return $null }
  return $property.Value
}

function Save-LiveResult {
  param([hashtable]$Result)
  if (-not [string]::IsNullOrWhiteSpace($ResultPath)) {
    $parent = Split-Path -Parent $ResultPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
  }
}

try {
  $stage = "secure_key_prompt"
  if (-not [string]::IsNullOrWhiteSpace($ApiKeyFile)) {
    $resolvedKeyFile = (Resolve-Path -LiteralPath $ApiKeyFile).Path
    $plainKey = [IO.File]::ReadAllText($resolvedKeyFile).Trim()
    if ([string]::IsNullOrWhiteSpace($plainKey)) { throw "API Key file is empty" }
  }
  else {
    $secureKey = Read-Host "Enter yxai API Key once (input is hidden)" -AsSecureString
    if ($secureKey.Length -eq 0) { throw "API Key cannot be empty" }
    $keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
  }
  $env:LEAN_PROOF_API_KEY = $plainKey
  $env:OPENAI_API_KEY = $plainKey
  $env:PYTHONPATH = Join-Path $repoRoot "src"
  if ($null -ne $axDependenciesPath) {
    $env:PYTHONPATH = $axDependenciesPath + [IO.Path]::PathSeparator + $env:PYTHONPATH
  }
  New-Item -ItemType Directory -Path $workDir | Out-Null

  $stage = "direct_agent_call"
  $directLog = Join-Path $workDir "direct-agent.jsonl"
  $directCache = Join-Path $workDir "direct-cache.sqlite3"
  $directOutputDir = Join-Path $workDir "solutions"
  Write-Host "[1/2] Testing direct provider -> Agent -> Lean..."
  $directLines = @(
    & $PythonCommand (Join-Path $repoRoot "src\agent.py") solve `
      --file (Join-Path $repoRoot "lean_project\Benchmarks\Evaluation18.lean") `
      --theorem "Eval18.and_swap_eval" `
      --condition A `
      --provider openai_compatible `
      --api-url "https://yxai.chat/v1" `
      --model "gpt-5.6-sol" `
      --wire-api responses `
      --reasoning-effort high `
      --disable-response-storage `
      --max-tokens 512 `
      --max-rounds 1 `
      --timeout 20 `
      --cache $directCache `
      --output-dir $directOutputDir `
      --log $directLog 2>&1
  )
  $directExitCode = $LASTEXITCODE
  $stage = "direct_agent_result"
  $directRecord = $null
  if (Test-Path -LiteralPath $directLog) {
    $directRecord = Get-Content -LiteralPath $directLog -Encoding UTF8 | Select-Object -Last 1 | ConvertFrom-Json
  }
  $directProviderError = Read-OptionalProperty $directRecord "provider_error"
  $directUsage = Read-OptionalProperty $directRecord "usage"
  $directResult = @{
    api_ok = ($null -ne $directRecord) -and [string]::IsNullOrWhiteSpace([string]$directProviderError)
    compile_ok = [bool](Read-OptionalProperty $directRecord "compile_ok")
    process_exit_code = $directExitCode
    diagnostic_category = Read-OptionalProperty (Read-OptionalProperty $directRecord "diagnostic") "category"
    input_tokens = Read-OptionalProperty $directUsage "input_tokens"
    output_tokens = Read-OptionalProperty $directUsage "output_tokens"
    total_tokens = Read-OptionalProperty $directUsage "total_tokens"
  }

  $stage = "axprover_call"
  Write-Host "[2/2] Testing pinned AxProverBase -> LangChain -> yxai..."
  $axLines = @(& $PythonCommand (Join-Path $repoRoot "scripts\live_ax_yxai_smoke.py") 2>&1)
  $axExitCode = $LASTEXITCODE
  $axJsonLine = $axLines | Where-Object { ([string]$_).TrimStart().StartsWith("{") } | Select-Object -Last 1
  $axResult = $null
  if ($null -ne $axJsonLine) {
    $axResult = ([string]$axJsonLine) | ConvertFrom-Json
  }

  $stage = "result_serialization"
  $finalResult = @{
    ok = $directResult.api_ok -and $directResult.compile_ok -and ($null -ne $axResult) -and [bool]$axResult.ok
    model = "gpt-5.6-sol"
    endpoint = "https://yxai.chat/v1"
    wire_api = "responses"
    store = $false
    reasoning_effort = "high"
    direct_agent = $directResult
    axprover = $axResult
    ax_process_exit_code = $axExitCode
  }
  Save-LiveResult $finalResult

  if ($directResult.api_ok) {
    Write-Host "Direct provider API call succeeded." -ForegroundColor Green
  }
  else {
    Write-Host "Direct provider API call failed." -ForegroundColor Red
  }
  if ($directResult.compile_ok) {
    Write-Host "Generated proof passed Lean." -ForegroundColor Green
  }
  else {
    Write-Host "Generated proof did not pass Lean in the one allowed round." -ForegroundColor Yellow
  }
  if (($null -ne $axResult) -and [bool]$axResult.ok) {
    Write-Host "AxProverBase API call succeeded." -ForegroundColor Green
  }
  else {
    Write-Host "AxProverBase API call failed." -ForegroundColor Red
  }
  Write-Host "No credential, prompt, candidate, or raw response was saved."
  Start-Sleep -Seconds 3
}
catch {
  $finalResult = @{
    ok = $false
    model = "gpt-5.6-sol"
    endpoint = "https://yxai.chat/v1"
    stage = $stage
    script_line = $_.InvocationInfo.ScriptLineNumber
    error_type = $_.Exception.GetType().FullName
    direct_process_exit_code = $directExitCode
    ax_process_exit_code = $axExitCode
  }
  Save-LiveResult $finalResult
  Write-Host "Live yxai smoke failed before completion." -ForegroundColor Red
  Write-Host ("Error type: " + $finalResult.error_type)
  Write-Host "No credential or raw response was saved."
  Start-Sleep -Seconds 3
}
finally {
  if ($null -eq $priorLeanKey) { Remove-Item Env:LEAN_PROOF_API_KEY -ErrorAction SilentlyContinue }
  else { $env:LEAN_PROOF_API_KEY = $priorLeanKey }
  if ($null -eq $priorOpenAIKey) { Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue }
  else { $env:OPENAI_API_KEY = $priorOpenAIKey }
  $env:PYTHONPATH = $priorPythonPath
  $plainKey = $null
  if ($keyPtr -ne [IntPtr]::Zero) {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
    $keyPtr = [IntPtr]::Zero
  }
  Remove-Variable secureKey, plainKey -ErrorAction SilentlyContinue

  if (Test-Path -LiteralPath $workDir) {
    $resolvedWorkDir = (Resolve-Path -LiteralPath $workDir).Path
    if ((Split-Path -Parent $resolvedWorkDir) -ne $repoRoot -or -not (Split-Path -Leaf $resolvedWorkDir).StartsWith(".live-yxai-smoke-")) {
      throw "Refusing to remove unexpected live smoke directory: $resolvedWorkDir"
    }
    Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force
  }
}

if (($null -ne $finalResult) -and [bool]$finalResult.ok) { exit 0 }
exit 1
