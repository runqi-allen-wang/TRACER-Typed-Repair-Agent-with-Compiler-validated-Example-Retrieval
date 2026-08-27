[CmdletBinding()]
param(
  [string]$Python = "python",
  [ValidateSet("command", "openai_compatible")]
  [string]$Provider = "openai_compatible",
  [string]$ProviderCommand = "",
  [string]$ApiUrl = "https://yxai.chat/v1",
  [string]$Model = "gpt-5.6-sol",
  [ValidateSet("chat_completions", "responses")]
  [string]$WireApi = "responses",
  [ValidateSet("minimal", "low", "medium", "high")]
  [string]$ReasoningEffort = "high",
  [ValidateRange(0.0, 2.0)]
  [double]$Temperature = 0.0,
  [ValidateRange(1, 1000000)]
  [int]$MaxTokens = 800,
  [ValidateRange(1.0, 3600.0)]
  [double]$LeanTimeout = 20.0,
  [switch]$ReuseCache
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$env:ELAN_HOME = if ($env:ELAN_HOME) { $env:ELAN_HOME } else { Join-Path $env:USERPROFILE ".elan" }

function Invoke-NativeCommand {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command,
    [Parameter(Mandatory = $true)]
    [object[]]$Arguments
  )

  & $Command @Arguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "$Command failed with exit code $exitCode"
  }
}

$PythonArgs = @()
if ($Python -eq "python") {
  $pythonOnPath = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonOnPath) {
    $Python = $pythonOnPath.Source
  }
  else {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
      $Python = $pyLauncher.Source
      $PythonArgs = @("-3")
    }
    else {
      throw "Python 3.10 or newer was not found"
    }
  }
}

if ($Provider -eq "openai_compatible") {
  if ([string]::IsNullOrWhiteSpace($ApiUrl)) { $ApiUrl = $env:LEAN_PROOF_API_URL }
  if ([string]::IsNullOrWhiteSpace($Model)) { $Model = $env:LEAN_PROOF_MODEL }
  if ([string]::IsNullOrWhiteSpace($ApiUrl)) { throw "ApiUrl or LEAN_PROOF_API_URL is required" }
  if ([string]::IsNullOrWhiteSpace($Model)) { throw "Model or LEAN_PROOF_MODEL is required" }
  if ([string]::IsNullOrWhiteSpace($env:LEAN_PROOF_API_KEY)) { throw "LEAN_PROOF_API_KEY is required" }
  $env:LEAN_PROOF_API_URL = $ApiUrl
  $env:LEAN_PROOF_MODEL = $Model
  $env:LEAN_PROOF_WIRE_API = $WireApi
  $env:LEAN_PROOF_REASONING_EFFORT = $ReasoningEffort
  $env:LEAN_PROOF_DISABLE_RESPONSE_STORAGE = "true"
  $env:LEAN_PROOF_TEMPERATURE = [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $Temperature)
  $env:LEAN_PROOF_MAX_TOKENS = $MaxTokens.ToString([Globalization.CultureInfo]::InvariantCulture)
}
elseif ([string]::IsNullOrWhiteSpace($ProviderCommand)) {
  throw "ProviderCommand is required for the command provider"
}

Push-Location $Root
try {
  Invoke-NativeCommand -Command "lake" -Arguments @("build")
  Invoke-NativeCommand -Command $Python -Arguments ($PythonArgs + @("-m", "unittest", "discover", "-s", "tests", "-v"))

  $evaluateArgs = $PythonArgs + @(
    "src/evaluate.py",
    "--provider", $Provider,
    "--conditions", "A,B,C",
    "--max-rounds", "3",
    "--timeout", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $LeanTimeout)),
    "--fresh"
  )
  if ($Provider -eq "command") {
    $evaluateArgs += @("--provider-command", $ProviderCommand)
  }
  if ($ReuseCache) {
    $evaluateArgs += "--reuse-cache"
  }
  Invoke-NativeCommand -Command $Python -Arguments $evaluateArgs

  $validateArgs = $PythonArgs + @("scripts/validate_pilot.py")
  if ($ReuseCache) {
    $validateArgs += "--allow-cache-hits"
  }
  Invoke-NativeCommand -Command $Python -Arguments $validateArgs
  Invoke-NativeCommand -Command $Python -Arguments ($PythonArgs + @("src/report.py", "--allow-unreviewed"))

  Write-Output "Pilot execution complete. REPORT.md is a draft until manual review passes."
}
finally {
  Pop-Location
}
