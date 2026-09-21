[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [double]$BudgetUsd,
    [string]$Out = ("results/research-six-arm-deepseek-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [int]$MaxCalls = 2592,
    [ValidateRange(0, 50)]
    [int]$TransportResumeAttempts = 20,
    [ValidateRange(5, 600)]
    [int]$TransportResumeDelaySeconds = 60,
    [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot

$config = "experiments/research.deepseek.six_arm_20260920.json"
$preregistration = "experiments/preregistrations/repair24_six_arm_deepseek_20260920.json"
$benchmark = "benchmarks/repair24/manifest.json"

function Get-LatestTrialFailure {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunRoot,
        [Parameter(Mandatory = $true)]
        [datetime]$NotBeforeUtc
    )

    $trialsRoot = Join-Path $RunRoot "trials"
    if (-not (Test-Path -LiteralPath $trialsRoot)) {
        return $null
    }

    $candidates = Get-ChildItem -LiteralPath $trialsRoot -Recurse -Filter "trial.json" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -ge $NotBeforeUtc } |
        Sort-Object -Property LastWriteTimeUtc -Descending

    foreach ($candidate in $candidates) {
        try {
            $payload = Get-Content -LiteralPath $candidate.FullName -Raw -Encoding utf8 | ConvertFrom-Json
            if ($payload.PSObject.Properties.Name -contains "error") {
                $message = [string]$payload.error
                if (-not [string]::IsNullOrWhiteSpace($message)) {
                    return [pscustomobject]@{
                        Path = $candidate.FullName
                        Message = $message
                    }
                }
            }
        }
        catch {
            continue
        }
    }
    return $null
}

function Test-TransientProviderError {
    param([string]$Message)

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return $false
    }
    $patterns = @(
        "\bHTTP\s+(429|500|502|503|504)\b",
        "WinError\s+(10054|10060|10061)\b",
        "connection\s+(reset|closed|aborted|refused)",
        "RemoteDisconnected",
        "timed out|timeout",
        "service[_ ]unavailable",
        "too busy",
        "temporar(?:y|ily)\s+(unavailable|failure)"
    )
    foreach ($pattern in $patterns) {
        if ($Message -match $pattern) {
            return $true
        }
    }
    return $false
}

if ($BudgetUsd -le 0) {
    throw "BudgetUsd must be positive. It is a local conservative reservation limit, not a provider billing cap."
}
if ($MaxCalls -ne 2592) {
    throw "The preregistered full matrix requires MaxCalls=2592."
}
if ((Test-Path -LiteralPath $Out) -and -not $Resume) {
    throw "Output directory already exists. Use -Resume with the exact same directory and budget: $Out"
}
if ($Resume -and -not (Test-Path -LiteralPath $Out)) {
    throw "Resume directory does not exist: $Out"
}

Write-Host "repair24 full six-arm matrix: 24 tasks x 2 models x 3 repeats x 6 arms = 864 tasks."
Write-Host "Maximum provider calls: 2592. Peak-price output-only worst-case reservation: USD 80.24832; input is additional."
Write-Host "BudgetUsd=$BudgetUsd is a local reservation guard, not a provider hard billing limit."
Write-Host "Output directory: $Out"

& python src/research.py plan `
    --config $config `
    --benchmark $benchmark `
    --preregistration $preregistration
if ($LASTEXITCODE -ne 0) {
    throw "Offline plan or preregistration validation failed."
}

& python src/research.py check-benchmark --benchmark $benchmark --timeout 180
if ($LASTEXITCODE -ne 0) {
    throw "repair24 compile precheck failed; no provider request was sent."
}

$secureKey = Read-Host "DeepSeek API key" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$plainKey = $null

try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "API key cannot be empty."
    }
    $env:TRACER_DEEPSEEK_KEY = $plainKey

    if (-not $Resume) {
        & python src/research.py preflight --config $config
        if ($LASTEXITCODE -ne 0) {
            throw "Synthetic provider preflight failed; the formal matrix was not started."
        }
    }

    $automaticResumesUsed = 0
    $nextInvocationIsResume = [bool]$Resume
    while ($true) {
        $arguments = @(
            "src/research.py", "run",
            "--config", $config,
            "--benchmark", $benchmark,
            "--preregistration", $preregistration,
            "--out", $Out,
            "--max-calls", "$MaxCalls",
            "--max-reserved-usd", "$BudgetUsd"
        )
        if ($nextInvocationIsResume) {
            $arguments += "--resume"
        }

        $invocationStartedUtc = [datetime]::UtcNow
        & python @arguments
        $runExitCode = $LASTEXITCODE
        if ($runExitCode -eq 0) {
            break
        }

        & python src/research.py report --run $Out --allow-partial
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "The partial report could not be generated; the original run directory is unchanged."
        }

        # 只判断本次调用新写入的失败工件，避免用旧 503 掩盖配置、审计或预算错误。
        $failure = Get-LatestTrialFailure -RunRoot $Out -NotBeforeUtc $invocationStartedUtc.AddSeconds(-2)
        if ($null -eq $failure -or -not (Test-TransientProviderError -Message $failure.Message)) {
            throw "The matrix stopped on a non-transient or unclassified error. Keep the directory and inspect the latest trial before resuming."
        }
        if ($automaticResumesUsed -ge $TransportResumeAttempts) {
            throw "The matrix reached the finite transport resume limit. Keep the directory and resume later with the same Out and BudgetUsd."
        }

        $automaticResumesUsed += 1
        $relativeFailure = Resolve-Path -LiteralPath $failure.Path -Relative
        Write-Warning ("Transient provider or transport failure recorded at {0}. Strict resume {1}/{2} starts after {3} seconds." -f $relativeFailure, $automaticResumesUsed, $TransportResumeAttempts, $TransportResumeDelaySeconds)
        Start-Sleep -Seconds $TransportResumeDelaySeconds
        $nextInvocationIsResume = $true
    }

    & python src/research.py report --run $Out
    if ($LASTEXITCODE -ne 0) {
        throw "The matrix completed but failed the trajectory audit. Do not rerun or delete the evidence."
    }
}
finally {
    Remove-Item Env:TRACER_DEEPSEEK_KEY -ErrorAction SilentlyContinue
    $plainKey = $null
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
}
