param(
  [string]$Python = "python",
  [ValidateSet("command", "openai_compatible")]
  [string]$Provider = "openai_compatible",
  [string]$ProviderCommand = ""
)

$ErrorActionPreference = "Stop"
$env:ELAN_HOME = if ($env:ELAN_HOME) { $env:ELAN_HOME } else { "$env:USERPROFILE\.elan" }

$PythonArgs = @()
if ($Python -eq "python") {
  $pythonOnPath = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonOnPath) {
    $Python = $pythonOnPath.Source
  } else {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $bundled = @(
      "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($bundled) {
      $Python = $bundled
    } elseif ($pyLauncher) {
      $Python = $pyLauncher.Source
      $PythonArgs = @("-3")
    } else {
      throw "找不到 Python。请安装 Python 3.10+，或使用 -Python 指定解释器路径。"
    }
  }
}

& $Python @PythonArgs src/evaluate.py --provider $Provider --provider-command $ProviderCommand --conditions A,B,C --max-rounds 3 --fresh
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python @PythonArgs src/report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Pilot complete: results/pilot_summary.csv and REPORT.md"
