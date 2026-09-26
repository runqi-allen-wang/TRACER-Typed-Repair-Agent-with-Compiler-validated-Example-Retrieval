[CmdletBinding()]
param(
    [ValidateSet("All", "Extended", "MiniMax")]
    [string]$Batch = "All",
    [string]$RunRoot,
    [switch]$Resume,
    [switch]$SkipPreflight,
    [switch]$NoCostLimit,
    [double]$ExtendedBudgetUsd = 0,
    [double]$MiniMaxBudgetUsd = 0,
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repoRoot

$batchSpecs = @{
    Extended = @{
        Directory = "extended"
        Config = "experiments/causal_feedback.tracer_acl2027_extended_v1.json"
        Preregistration = "experiments/preregistrations/tracer_acl2027_extended_v1.json"
        KeyNames = @("TRACER_ACL_DEEPSEEK_KEY", "TRACER_ACL_GLM_KEY")
    }
    MiniMax = @{
        Directory = "minimax-confirmatory"
        Config = "experiments/causal_feedback.tracer_acl2027_minimax_confirmatory_v1.json"
        Preregistration = "experiments/preregistrations/tracer_acl2027_minimax_confirmatory_v1.json"
        KeyNames = @("TRACER_ACL_MINIMAX_KEY")
    }
}
$selectedBatches = if ($Batch -eq "All") { @("Extended", "MiniMax") } else { @($Batch) }

if ($Resume -and [string]::IsNullOrWhiteSpace($RunRoot)) {
    throw "-Resume requires the exact existing -RunRoot."
}
if ($NoCostLimit -and ($ExtendedBudgetUsd -gt 0 -or $MiniMaxBudgetUsd -gt 0)) {
    throw "Do not combine -NoCostLimit with a batch budget."
}
if (-not $NoCostLimit) {
    if ($selectedBatches -contains "Extended" -and $ExtendedBudgetUsd -le 0) {
        throw "Provide -ExtendedBudgetUsd or explicitly use -NoCostLimit."
    }
    if ($selectedBatches -contains "MiniMax" -and $MiniMaxBudgetUsd -le 0) {
        throw "Provide -MiniMaxBudgetUsd or explicitly use -NoCostLimit."
    }
    foreach ($batchName in $selectedBatches) {
        $priceConfig = Get-Content -LiteralPath $batchSpecs[$batchName].Config -Raw -Encoding UTF8 | ConvertFrom-Json
        $unknownPrices = @($priceConfig.models | Where-Object {
            $null -eq $_.input_price_per_1k -or $null -eq $_.output_price_per_1k
        })
        if ($unknownPrices.Count -gt 0) {
            throw "$batchName has frozen unknown prices. Use -NoCostLimit and enforce an account-level provider budget; the preregistered call-count limit still applies."
        }
    }
}

if ([string]::IsNullOrWhiteSpace($RunRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $RunRoot = Join-Path "results" "acl2027-formal-$stamp-$suffix"
}
if (-not [IO.Path]::IsPathRooted($RunRoot)) {
    $RunRoot = Join-Path $repoRoot $RunRoot
}
$RunRoot = [IO.Path]::GetFullPath($RunRoot)
$runnerRoot = Join-Path $RunRoot "_runner"
$attemptRoot = Join-Path $runnerRoot "attempts"
$contractPath = Join-Path $runnerRoot "run-contract.json"

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-LoggedPython {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][string]$BatchName
    )
    $logParent = Split-Path -Parent $LogPath
    if (-not (Test-Path -LiteralPath $logParent)) {
        New-Item -ItemType Directory -Path $logParent -Force | Out-Null
    }
    & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $failurePath = Join-Path $attemptRoot ("failure-{0}-{1}-{2}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $BatchName.ToLowerInvariant(), $Phase)
        $relativeLog = $LogPath.Substring($RunRoot.Length).TrimStart([char[]]@('\', '/')).Replace("\", "/")
        Write-JsonFile $failurePath ([ordered]@{
            schema_version = "tracer-acl2027-runner-failure-v1"
            recorded_at = (Get-Date).ToUniversalTime().ToString("o")
            batch = $BatchName
            phase = $Phase
            exit_code = $exitCode
            output_directory = $batchSpecs[$BatchName].Directory
            log = $relativeLog
            artifacts_retained = $true
        })
        throw "$BatchName $Phase failed with exit code $exitCode. Existing artifacts were retained at $RunRoot."
    }
}

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

if ($Resume) {
    if (-not (Test-Path -LiteralPath $RunRoot -PathType Container)) {
        throw "Resume root does not exist: $RunRoot"
    }
    if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
        throw "Resume root has no run contract: $contractPath"
    }
    $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $savedBatches = @($contract.selected_batches)
    if (Compare-Object $savedBatches $selectedBatches) {
        throw "-Batch does not match the existing run contract."
    }
}
else {
    if (Test-Path -LiteralPath $RunRoot) {
        throw "Run root already exists. Use -Resume with this exact path: $RunRoot"
    }
    New-Item -ItemType Directory -Path $attemptRoot -Force | Out-Null
    Write-JsonFile $contractPath ([ordered]@{
        schema_version = "tracer-acl2027-run-contract-v1"
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        protocol = "tracer-acl2027-causal-protocol-v1"
        benchmark = "tracer-real-v2"
        selected_batches = $selectedBatches
        batch_directories = @($selectedBatches | ForEach-Object { $batchSpecs[$_].Directory })
        resume_requires_same_root = $true
        completed_batches_are_audited_then_skipped = $true
        failed_artifacts_are_retained = $true
    })
}

$attemptId = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$attemptDirectory = Join-Path $attemptRoot $attemptId
New-Item -ItemType Directory -Path $attemptDirectory -Force | Out-Null
Write-Host "ACL 2027 run root: $RunRoot"

try {
    Invoke-LoggedPython `
        -Arguments @("src/acl2027.py", "audit") `
        -LogPath (Join-Path $attemptDirectory "offline-audit.log") `
        -Phase "offline-audit" `
        -BatchName $selectedBatches[0]

    $pending = New-Object System.Collections.Generic.List[string]
    foreach ($batchName in $selectedBatches) {
        $batchOut = Join-Path $RunRoot $batchSpecs[$batchName].Directory
        $summaryPath = Join-Path $batchOut "summary.json"
        if (Test-Path -LiteralPath $summaryPath -PathType Leaf) {
            Invoke-LoggedPython `
                -Arguments @("src/causal_feedback.py", "audit", "--run", $batchOut) `
                -LogPath (Join-Path $attemptDirectory ("{0}-existing-audit.log" -f $batchName.ToLowerInvariant())) `
                -Phase "existing-audit" `
                -BatchName $batchName
            Write-Host "$batchName is already complete and passed audit; skipping it."
            continue
        }
        if ((Test-Path -LiteralPath $batchOut) -and -not $Resume) {
            throw "$batchName output already exists; use -Resume with the exact run root."
        }
        $pending.Add($batchName)
    }

    if ($pending.Count -eq 0) {
        Write-Host "All selected batches are already complete and audited: $RunRoot"
        return
    }

    if ($pending -contains "Extended") {
        Set-HiddenApiKey "DeepSeek API key" "TRACER_ACL_DEEPSEEK_KEY"
        Set-HiddenApiKey "Zhipu BigModel GLM API key" "TRACER_ACL_GLM_KEY"
    }
    if ($pending -contains "MiniMax") {
        Set-HiddenApiKey "MiniMax API key" "TRACER_ACL_MINIMAX_KEY"
    }

    if (-not $SkipPreflight) {
        foreach ($preflightBatchName in $pending) {
            $preflightSpec = $batchSpecs[$preflightBatchName]
            Invoke-LoggedPython `
                -Arguments @("src/causal_feedback.py", "preflight", "--config", $preflightSpec.Config) `
                -LogPath (Join-Path $attemptDirectory ("{0}-preflight.log" -f $preflightBatchName.ToLowerInvariant())) `
                -Phase "preflight" `
                -BatchName $preflightBatchName
        }
    }

    foreach ($batchName in $pending) {
        $spec = $batchSpecs[$batchName]
        $batchOut = Join-Path $RunRoot $spec.Directory
        $batchExists = Test-Path -LiteralPath $batchOut -PathType Container

        $runArguments = @(
            "src/causal_feedback.py", "run",
            "--config", $spec.Config,
            "--benchmark", "benchmarks/real_repairs/tracer_real_v2/manifest.json",
            "--preregistration", $spec.Preregistration,
            "--out", $batchOut
        )
        if ($batchExists) {
            if (-not $Resume) {
                throw "$batchName output exists but -Resume was not supplied."
            }
            $runArguments += "--resume"
        }
        if ($NoCostLimit) {
            $runArguments += "--no-cost-limit"
        }
        else {
            $budget = if ($batchName -eq "Extended") { $ExtendedBudgetUsd } else { $MiniMaxBudgetUsd }
            $runArguments += @("--max-reserved-usd", $budget.ToString([Globalization.CultureInfo]::InvariantCulture))
        }

        Invoke-LoggedPython `
            -Arguments $runArguments `
            -LogPath (Join-Path $attemptDirectory ("{0}-run.log" -f $batchName.ToLowerInvariant())) `
            -Phase "run" `
            -BatchName $batchName
        Invoke-LoggedPython `
            -Arguments @("src/causal_feedback.py", "audit", "--run", $batchOut) `
            -LogPath (Join-Path $attemptDirectory ("{0}-audit.log" -f $batchName.ToLowerInvariant())) `
            -Phase "audit" `
            -BatchName $batchName
    }

    Write-JsonFile (Join-Path $runnerRoot "status.json") ([ordered]@{
        schema_version = "tracer-acl2027-runner-status-v1"
        status = "complete"
        completed_at = (Get-Date).ToUniversalTime().ToString("o")
        selected_batches = $selectedBatches
        run_root = "."
    })
    Write-Host "All selected ACL 2027 batches completed and passed audit: $RunRoot"
}
finally {
    Remove-Item Env:TRACER_ACL_DEEPSEEK_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TRACER_ACL_GLM_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TRACER_ACL_MINIMAX_KEY -ErrorAction SilentlyContinue
}
