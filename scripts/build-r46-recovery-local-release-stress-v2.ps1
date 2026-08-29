#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipCargoCheck,
    [switch]$SkipFrontendBuild,
    [switch]$SkipLegacyStress
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$Command,[Parameter(ValueFromRemainingArguments)][string[]]$Arguments)
    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')" }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r46 v2 - Recovery Safety Hardening' -ForegroundColor Green
$baseGate = Join-Path $PSScriptRoot 'build-r46-recovery-local-release-stress.ps1'
$args = @()
$args += '-SkipCargoCheck'
$args += '-SkipFrontendBuild'
if ($SkipLegacyStress) { $args += '-SkipLegacyStress' }
& $baseGate @args
if ($LASTEXITCODE -ne 0) { throw "r46 base gate failed with exit code $LASTEXITCODE" }

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) { throw 'CARGO_HOME is empty after inherited gate.' }
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

Write-Host "`n[r46-v2 1/5] Recovery backup + chain-health hardening" -ForegroundColor Green
Invoke-Checked 'python' 'scripts/apply_r46_thread_recovery_backup_hardening.py'
Invoke-Checked 'python' 'scripts/apply_r46_chain_health_recovery_hint.py'
Set-Content -LiteralPath (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_REVISION.txt') -Value '46' -Encoding UTF8
Invoke-Checked 'python' 'scripts/apply_sub2api_grok_compat_revision.py'

Write-Host "`n[r46-v2 2/5] Format / whitespace" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked 'git' 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'

Write-Host "`n[r46-v2 3/5] Hardened source invariants" -ForegroundColor Green
$backend = Get-Content (Join-Path $repoRoot 'src-tauri/src/admin/handlers/thread_recovery.rs') -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R46-RECOVERY-STATE-DB-BACKUP',
    'state-db-backup',
    'state_db_copies',
    'backup_recovery_state(codex_home, rollout, thread_id)',
    'UNIX_EPOCH'
)) {
    if ($backend -notmatch [regex]::Escape($marker)) { throw "r46-v2 recovery invariant missing: $marker" }
}
$health = Get-Content (Join-Path $repoRoot 'src-tauri/src/admin/handlers/chain_health.rs') -Raw -Encoding UTF8
if ($health -notmatch 'CAS-R46-OLD-THREAD-RECOVERY-HINT' -or $health -notmatch 'same_thread_recovery_available') {
    throw 'r46-v2 chain-health recovery hint missing'
}

Write-Host "`n[r46-v2 4/5] Production frontend" -ForegroundColor Green
if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $repoRoot 'frontend')
    try { Invoke-Checked 'npm.cmd' 'run' 'build' } finally { Pop-Location }
}

Write-Host "`n[r46-v2 5/5] Final Windows cargo checks" -ForegroundColor Green
if (-not $SkipCargoCheck) {
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer-proxy' '--target' $target
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host 'cargo check skipped by request' -ForegroundColor Yellow
}

$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
if ($version -notmatch 'compat_revision=46' -or $version -notmatch 'app_version=2\.4\.5\+46') {
    throw 'r46-v2 version stamp mismatch'
}

Write-Host "`nR46 V2 RECOVERY SAFETY VALIDATION PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'No real thread recovery was executed by this build gate.' -ForegroundColor Yellow
