[CmdletBinding()] param()
$ErrorActionPreference = 'Stop'
$CapsuleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepositoryRoot = $CapsuleRoot
while ($RepositoryRoot -and -not (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'leancapsule\__main__.py'))) {
  $Parent = Split-Path -Parent $RepositoryRoot
  if ($Parent -eq $RepositoryRoot) { $RepositoryRoot = $null } else { $RepositoryRoot = $Parent }
}
if ($RepositoryRoot) { Push-Location $RepositoryRoot }
try { python -m leancapsule replay $CapsuleRoot; exit $LASTEXITCODE } finally { if ($RepositoryRoot) { Pop-Location } }
