param(
  [string]$Project = "$PSScriptRoot\..\mathlib_project"
)

$ErrorActionPreference = "Stop"
$resolved = (Resolve-Path $Project).Path
$env:MATHLIB_CACHE_DIR = Join-Path $resolved ".lake\mathlib-cache"
New-Item -ItemType Directory -Force -Path $env:MATHLIB_CACHE_DIR | Out-Null

function Clear-ReadOnlyFiles([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  Get-ChildItem -LiteralPath $Path -File -Force -Recurse | ForEach-Object {
    if ($_.IsReadOnly) { $_.IsReadOnly = $false }
  }
}

Push-Location $resolved
try {
  # 网络中断可能留下只有 .git 但没有有效 HEAD 的残缺包；仅清理这个
  # 可重新生成的依赖目录，避免 lake update 在损坏仓库上反复失败。
  $mathlibPackage = Join-Path $resolved ".lake\packages\mathlib"
  if (Test-Path -LiteralPath $mathlibPackage) {
    $null = git -C $mathlibPackage rev-parse --verify HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "检测到损坏的 Mathlib 包，正在清理后重新获取..."
      Remove-Item -LiteralPath $mathlibPackage -Recurse -Force
    }
  }
  Clear-ReadOnlyFiles (Join-Path $resolved ".lake")
  Write-Host "正在同步 Mathlib 依赖..."
  lake update
  if ($LASTEXITCODE -ne 0) { throw "lake update 失败，退出码：$LASTEXITCODE" }
  $cacheProbe = Join-Path $resolved ".lake\packages\mathlib\.lake\build\lib\lean\Mathlib.olean"
  if (-not (Test-Path -LiteralPath $cacheProbe)) {
    Write-Host "正在获取 Mathlib 预编译缓存..."
    lake exe cache get
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "预编译缓存未完全下载，将尝试从源码构建所需模块。"
      # 缓存归档解压出的文件可能是只读的，源码构建前必须先解除属性。
      Clear-ReadOnlyFiles (Join-Path $resolved ".lake")
      lake build Mathlib.Data.Nat.Prime.Basic
      if ($LASTEXITCODE -ne 0) { throw "Mathlib 缓存和源码构建均失败，退出码：$LASTEXITCODE" }
    }
  }
  # cache get 产生的归档文件可能带只读属性；Lake 后续需要写入内部状态文件。
  Clear-ReadOnlyFiles (Join-Path $resolved ".lake")
  Write-Host "Mathlib 环境准备完成。"
}
finally {
  Pop-Location
}
