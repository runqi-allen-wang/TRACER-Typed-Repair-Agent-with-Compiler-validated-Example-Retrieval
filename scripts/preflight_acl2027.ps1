[CmdletBinding()]
param(
    [ValidateSet("All", "Extended", "MiniMax")]
    [string]$Provider = "All"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot

function Set-HiddenApiKey {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$EnvironmentName
    )
    $secureValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $plainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plainValue)) {
            throw "$Prompt cannot be empty."
        }
        Set-Item -LiteralPath "Env:$EnvironmentName" -Value $plainValue
        $plainValue = $null
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

try {
    & python src/acl2027.py audit
    if ($LASTEXITCODE -ne 0) {
        throw "ACL 2027 offline readiness audit failed; no provider was called."
    }

    if ($Provider -in @("All", "Extended")) {
        Set-HiddenApiKey "DeepSeek API key" "TRACER_ACL_DEEPSEEK_KEY"
        Set-HiddenApiKey "Zhipu BigModel GLM API key" "TRACER_ACL_GLM_KEY"

        & python src/causal_feedback.py preflight `
            --config experiments/causal_feedback.tracer_acl2027_extended_v2.json
        if ($LASTEXITCODE -ne 0) {
            throw "DeepSeek/GLM synthetic preflight failed; no TRACER-REAL task was sent."
        }
    }

    if ($Provider -in @("All", "MiniMax")) {
        Set-HiddenApiKey "MiniMax API key" "TRACER_ACL_MINIMAX_KEY"

        & python src/causal_feedback.py preflight `
            --config experiments/causal_feedback.tracer_acl2027_minimax_confirmatory_v2.json
        if ($LASTEXITCODE -ne 0) {
            throw "MiniMax synthetic preflight failed; no TRACER-REAL task was sent."
        }
    }

    Write-Host "$Provider first-party provider preflight passed. No TRACER-REAL task was sent."
}
finally {
    Remove-Item Env:TRACER_ACL_DEEPSEEK_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TRACER_ACL_GLM_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TRACER_ACL_MINIMAX_KEY -ErrorAction SilentlyContinue
}
