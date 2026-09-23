param(
    [ValidateSet("Status", "Prepare", "Screen", "Build")]
    [string]$Mode = "Status",
    [ValidateSet("next", "leanapap", "pfr", "scilean", "equational_theories", "flt", "physlean", "con_nf")]
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
$plan = Get-Content -Raw -LiteralPath $planPath -Encoding utf8 | ConvertFrom-Json
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
    throw "当前计划中的剩余项目均已完成筛查；请执行 tracer_real_v2.py audit，而不是重复运行。"
}
$entry = @($status.projects | Where-Object { $_.project_id -eq $Project })
if ($entry.Count -ne 1 -and $Mode -in @("Prepare", "Build")) {
    $completed = @($plan.completed_before_plan | Where-Object { $_.project_id -eq $Project })
    if ($completed.Count -eq 1) {
        $entry = @([pscustomobject]@{
            project_id = $Project
            complete = $true
        })
    }
}
if ($entry.Count -ne 1) {
    throw "项目不在剩余筛查计划中：$Project"
}
$entry = $entry[0]
if ($entry.complete -and $Mode -notin @("Prepare", "Build")) {
    throw "项目已存在完整公开筛查报告，拒绝覆盖：$Project"
}
if (-not $entry.complete -and $Mode -eq "Build") {
    throw "项目尚无完整筛查报告，不能构建公开子题库：$Project"
}

$workingRoot = Join-Path $repoRoot "results\tracer-real-v2-screening"
$upstream = Join-Path $workingRoot "repos\$Project"
$inventory = Join-Path $repoRoot "benchmarks\real_repairs\tracer_real_v2_candidates\$Project.inventory.json"
$manifest = Join-Path $upstream "lake-manifest.json"
$manifestBefore = if (Test-Path -LiteralPath $manifest) {
    Get-Content -Raw -LiteralPath $manifest -Encoding utf8
} else {
    $null
}

if ($Mode -eq "Prepare") {
    Push-Location -LiteralPath $upstream
    try {
        if ($null -eq $manifestBefore) {
            throw "$Project 缺少已提交的 lake-manifest.json；冻结筛查禁止现场解析浮动依赖。"
        }
        # 已提交的 manifest 是唯一依赖锁。`lake update` 会重新解析 branch 依赖，
        # 即使上游源码端点不变也可能导致实验环境漂移，因此不在冻结准备流程中调用。
        Invoke-Checked "Mathlib 缓存准备" { lake exe cache get }
        # 仅有依赖目录并不代表目标项目模块可被 `lake env lean` 导入。
        # 优先完整构建；若上游的可选本机库在当前平台链接失败，则必须让冻结清单中的
        # 一个真实源码文件通过 `lake env lean`，才允许进入逐候选筛查。
        # 大型项目在 Windows 上并行构建可能因线程或内存压力留下不完整对象，
        # 继而让真实源码探针出现与任务无关的依赖缺失。准备阶段固定为单线程，
        # 并在结束后恢复调用者原有设置，保证可复现且不污染后续会话。
        $previousLeanNumThreads = $env:LEAN_NUM_THREADS
        $env:LEAN_NUM_THREADS = "1"
        try {
            & lake build
            $projectBuildExit = $LASTEXITCODE
        }
        finally {
            if ($null -eq $previousLeanNumThreads) {
                Remove-Item Env:LEAN_NUM_THREADS -ErrorAction SilentlyContinue
            } else {
                $env:LEAN_NUM_THREADS = $previousLeanNumThreads
            }
        }
        if ($projectBuildExit -ne 0) {
            $inventoryData = Get-Content -Raw -LiteralPath $inventory -Encoding utf8 | ConvertFrom-Json
            $probeSource = @($inventoryData.candidates)[0].file
            if ([string]::IsNullOrWhiteSpace($probeSource)) {
                throw "$Project 项目构建失败，且冻结清单没有可用的 Lean 探针源码。"
            }
            Write-Warning "$Project 完整构建退出码为 $projectBuildExit；正在验证筛查所需纯 Lean 环境：$probeSource"
            & lake env lean $probeSource
            if ($LASTEXITCODE -ne 0) {
                throw "$Project 项目构建失败，且冻结源码探针不能在项目环境中编译。"
            }
        }
    }
    finally {
        Pop-Location
    }
    Invoke-Checked "准备后静态审计" {
        python src/tracer_real_v2_screening_plan.py --plan $planPath --check-repositories
    }
    exit 0
}

if (
    -not (Test-Path -LiteralPath (Join-Path $upstream ".lake\packages")) -or
    -not (Test-Path -LiteralPath (Join-Path $upstream ".lake\build\lib\lean"))
) {
    throw "项目依赖或本地模块尚未完整构建。先运行：.\scripts\run_tracer_real_v2_screening.ps1 -Mode Prepare -Project $Project"
}
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
