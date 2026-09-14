[CmdletBinding()]
param(
    [string]$Out = "results/causal-tracer-real-v1-deepseek-20260913"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot

if (Test-Path -LiteralPath $Out) {
    throw "Output directory already exists; refusing to overwrite: $Out"
}

$secureKey = Read-Host "DeepSeek API key" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$plainKey = $null

try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "API key cannot be empty."
    }
    $env:TRACER_CAUSAL_DEEPSEEK_KEY = $plainKey

    & python src/causal_feedback.py preflight `
        --config experiments/causal_feedback.tracer_real_v1.json
    if ($LASTEXITCODE -ne 0) {
        throw "Provider preflight failed; the formal experiment was not started."
    }

    & python src/causal_feedback.py run `
        --config experiments/causal_feedback.tracer_real_v1.json `
        --benchmark benchmarks/real_repairs/tracer_real_v1/manifest.json `
        --project-root mathlib_project `
        --preregistration experiments/preregistrations/tracer_real_causal_v1.json `
        --out $Out `
        --max-calls 108 `
        --no-cost-limit
    if ($LASTEXITCODE -ne 0) {
        throw "Formal experiment did not finish. Keep the output directory and do not rerun blindly."
    }

    & python src/causal_feedback.py audit --run $Out
    if ($LASTEXITCODE -ne 0) {
        throw "The experiment finished but did not pass the audit gate."
    }
}
finally {
    Remove-Item Env:TRACER_CAUSAL_DEEPSEEK_KEY -ErrorAction SilentlyContinue
    $plainKey = $null
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
}
