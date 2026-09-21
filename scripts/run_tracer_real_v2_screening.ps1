param(
    [ValidateSet("Status", "Prepare", "Screen", "Build")]
    [string]$Mode = "Status",
    [ValidateSet("next", "scilean", "equational_theories", "flt", "physlean")]
    [string]$Project = "next"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$planPath = Join-Path $repoRoot "experiments\tracer_real_v2_screening.plan.json"

function Test-ActiveResearchRunner {
    $pythonProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { $_.Name -match "^python(?:\.exe)?$" })
    $explicitRunner = @($pythonProcesses | Where-Object {
        $_.CommandLine -match "src[\\/]research\.py\s+(run|resume)"
    })
    if ($explicitRunner.Count -gt 0) {
        return $true
    }

    # 某些 Windows 会话不允许读取另一个终端启动进程的 CommandLine。
    # 此时用“仍有 Python 进程 + 最近更新的研究预算账本”作为保守活跃信号；
    # 15 分钟冷却会避免刚退出的批次立刻与 V2 争用缓存。
    $recentThreshold = [DateTime]::UtcNow.AddMinutes(-15)
    $recentBudgets = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "results") `
        -Directory -Filter "research-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "budget.json" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Where-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc -ge $recentThreshold })
    return $pythonProcesses.Count -gt 0 -and $recentBudgets.Count -gt 0
}

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Action)
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label 失败，退出码：$LASTEXITCODE"
    }
}

Set-Location -LiteralPath $repoRoot
$statusText = & python src/tracer_real_v2_screening_plan.py --plan $planPath --check-repositories
if ($LASTEXITCODE -ne 0) {
    throw "V2 筛查计划或上游检出审计失败：$statusText"
}
$status = $statusText | ConvertFrom-Json
$researchActive = Test-ActiveResearchRunner

if ($Mode -eq "Status") {
    [pscustomobject]@{
        ok = $true
        active_research_runner = $researchActive
        next_project = $status.next_project
        remaining_candidates = $status.remaining_candidates
        provider_calls = 0
        heavy_work_started = $false
        projects = $status.projects
        enrollment_projection = $status.enrollment_projection
    } | ConvertTo-Json -Depth 8
    exit 0
}

if ($researchActive) {
    throw "TRACER_V2_CONCURRENT_RESEARCH：检测到 repair24 研究 runner 仍在运行；为避免污染编译与耗时证据，拒绝启动 V2 依赖准备或筛查。"
}
if ($Project -eq "next") {
    $Project = $status.next_project
}
if ([string]::IsNullOrWhiteSpace($Project)) {
    throw "四个剩余项目均已完成筛查；请执行 tracer_real_v2.py audit，而不是重复运行。"
}
$entry = @($status.projects | Where-Object { $_.project_id -eq $Project })
if ($entry.Count -ne 1) {
    throw "项目不在剩余筛查计划中：$Project"
}
$entry = $entry[0]
if ($entry.complete -and $Mode -ne "Build") {
    throw "项目已存在完整公开筛查报告，拒绝覆盖：$Project"
}
if (-not $entry.complete -and $Mode -eq "Build") {
    throw "项目尚无完整筛查报告，不能构建公开子题库：$Project"
}

$workingRoot = Join-Path $repoRoot "results\tracer-real-v2-screening"
$upstream = Join-Path $workingRoot "repos\$Project"
$manifest = Join-Path $upstream "lake-manifest.json"
$manifestBefore = if (Test-Path -LiteralPath $manifest) {
    Get-Content -Raw -LiteralPath $manifest -Encoding utf8
} else {
    $null
}

if ($Mode -eq "Prepare") {
    Push-Location -LiteralPath $upstream
    try {
        Invoke-Checked "lake update" { lake update }
        if ($null -ne $manifestBefore) {
            $manifestAfter = Get-Content -Raw -LiteralPath $manifest -Encoding utf8
            if ($manifestAfter -cne $manifestBefore) {
                throw "lake update 改写了冻结端点的 lake-manifest.json；拒绝继续，请人工审查依赖漂移。"
            }
        }
        Invoke-Checked "Mathlib 缓存准备" { lake exe cache get }
    }
    finally {
        Pop-Location
    }
    Invoke-Checked "准备后静态审计" {
        python src/tracer_real_v2_screening_plan.py --plan $planPath --check-repositories
    }
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $upstream ".lake\packages"))) {
    throw "项目依赖尚未准备。先运行：.\scripts\run_tracer_real_v2_screening.ps1 -Mode Prepare -Project $Project"
}
$inventory = Join-Path $repoRoot "benchmarks\real_repairs\tracer_real_v2_candidates\$Project.inventory.json"
$state = Join-Path $workingRoot "$Project.screen-state.jsonl"
$spec = Join-Path $workingRoot "$Project.spec.json"
$report = Join-Path $repoRoot "benchmarks\real_repairs\tracer_real_v2_screening\$Project.screen.json"

if ($Mode -eq "Build") {
    if (-not (Test-Path -LiteralPath $spec)) {
        throw "筛查规范不存在，不能构建公开子题库：$spec"
    }
    $publicOut = Join-Path $repoRoot "benchmarks\real_repairs\${Project}_v2"
    $referenceOut = Join-Path $repoRoot "private_references\${Project}_v2"
    if ((Test-Path -LiteralPath $publicOut) -or (Test-Path -LiteralPath $referenceOut)) {
        throw "公开子题库或隔离参考证明目录已存在；拒绝覆盖：$Project"
    }
    Invoke-Checked "$Project 公开子题库构建" {
        python src/real_repairs.py build `
            --repo $upstream `
            --spec $spec `
            --out $publicOut `
            --reference-out $referenceOut `
            --project-root $upstream `
            --timeout 180
    }
    exit 0
}

Invoke-Checked "$Project 全量筛查" {
    python src/real_repair_inventory.py screen `
        --repo $upstream `
        --inventory $inventory `
        --project-root $upstream `
        --timeout 180 `
        --workers 1 `
        --state $state `
        --spec-out $spec `
        --report-out $report
}
Invoke-Checked "V2 纳入审计" { python src/tracer_real_v2.py audit }
