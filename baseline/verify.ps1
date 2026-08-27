# Part 1 一键验证（层次 1-3）
# 用法（在仓库根目录）： powershell -File baseline/verify.ps1
# 或： ./baseline/verify.ps1
$ErrorActionPreference = "Continue"
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root  = Split-Path -Parent $here
$gFail = 0
Push-Location $root

function Check([string]$name, [scriptblock]$block) {
  try {
    & $block | Out-Null
    Write-Output ("[PASS] {0}" -f $name)
  } catch {
    Write-Output ("[FAIL] {0} :: {1}" -f $name, $_.Exception.Message)
    $script:gFail++
  }
}

Check "baseline 文件齐全" {
  if (-not (Test-Path "baseline/config.yaml") -or -not (Test-Path "baseline/metrics_logger.py") -or -not (Test-Path "baseline/README.md")) { throw "missing file" }
}
Check "config 为合法 YAML 且含关键字段" {
  python baseline/config_check.py
  if ($LASTEXITCODE -ne 0) { throw "config invalid" }
}
Check "metrics_logger 语法" {
  python -m py_compile baseline/metrics_logger.py
  if ($LASTEXITCODE -ne 0) { throw "syntax error" }
}
Check "metrics mock + summary" {
  $tmp = Join-Path $env:TEMP ("vm_" + [guid]::NewGuid().ToString("N") + ".jsonl")
  python baseline/metrics_logger.py mock --tasks 5 --jsonl $tmp
  if ($LASTEXITCODE -ne 0) { throw "mock failed" }
  python baseline/metrics_logger.py summary --jsonl $tmp
}
Check "ax-prover 锁定 commit 存在于远程" {
  git ls-remote "https://github.com/Axiomatic-AI/ax-prover-base.git" 2>$null | Select-String "06dfadc9ab439755af5efcfe0add95bfef2733c7" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "commit not found" }
}

Pop-Location
if ($gFail -eq 0) { Write-Output "ALL CHECKS PASSED"; exit 0 }
Write-Output ("FAILED: {0}" -f $gFail)
exit 1
