#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipTauriInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Codex App Transfer r46 - FAST REAL-USE BUILD' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Purpose: get to real old-thread testing as fast as possible.'
Write-Host 'Skipped: Rust unit tests / cargo check / legacy stress / release proof.' -ForegroundColor Yellow
Write-Host 'Included: r46 materialization + actual Windows NSIS compilation.'

Write-Host "`n[1/4] Materialize r46" -ForegroundColor Green
Invoke-Checked 'python' '.\scripts\apply_r46_unified.py'

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=46' -or $versionFile -notmatch 'app_version=2\.4\.5\+46') {
    throw 'r46 materialization completed but version stamp is not 2.4.5+46.'
}
Write-Host $versionFile.Trim() -ForegroundColor Green

Write-Host "`n[2/4] Locate Cargo / Tauri" -ForegroundColor Green
$cargo = (Get-Command cargo.exe -ErrorAction SilentlyContinue).Source
if (-not $cargo) {
    $cargo = (Get-Command cargo -ErrorAction SilentlyContinue).Source
}
if (-not $cargo) { throw 'cargo was not found in PATH.' }

$tauriAvailable = $false
try {
    & $cargo tauri --version *> $null
    $tauriAvailable = ($LASTEXITCODE -eq 0)
} catch { $tauriAvailable = $false }

if (-not $tauriAvailable) {
    if ($SkipTauriInstall) {
        throw 'cargo-tauri is not installed and -SkipTauriInstall was specified.'
    }
    Write-Host 'cargo-tauri missing; installing once...' -ForegroundColor Yellow
    Invoke-Checked $cargo 'install' 'tauri-cli' '--version' '^2' '--locked'
}

Write-Host "`n[3/4] Build actual Windows NSIS package" -ForegroundColor Green
# Tauri runs the configured frontend beforeBuildCommand itself. Do not run a second
# npm production build here: this script intentionally optimizes time-to-real-test.
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked $cargo 'tauri' 'build' '--target' $target '--bundles' 'nsis'
} finally {
    Pop-Location
}

Write-Host "`n[4/4] Copy real-use installer" -ForegroundColor Green
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+46' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r46-real-use\$safeVersion"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$bundleRoot = if ($env:CARGO_TARGET_DIR) {
    Join-Path $env:CARGO_TARGET_DIR "$target\release\bundle\nsis"
} else {
    Join-Path $repoRoot "target\$target\release\bundle\nsis"
}
$setup = Get-ChildItem -LiteralPath $bundleRoot -Filter '*.exe' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $setup) {
    throw "NSIS installer not found under: $bundleRoot"
}

$dest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-FAST-REAL-USE.exe"
Copy-Item -LiteralPath $setup.FullName -Destination $dest -Force
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $dest).Hash

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 46
    purpose = 'FAST REAL-USE TEST BUILD'
    fullReleaseValidation = $false
    skipped = @('Rust unit tests','cargo check','legacy stress','release proof')
    materialization = 'passed'
    windowsNsisCompilation = 'passed'
    realThreadRecoveryExecutedDuringBuild = $false
    installer = $dest
    sha256 = $sha
    builtAt = (Get-Date).ToString('o')
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outDir 'FAST-REAL-USE-MANIFEST.json') -Encoding UTF8

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host 'R46 FAST REAL-USE BUILD PASS' -ForegroundColor Green
Write-Host "Installer: $dest"
Write-Host "SHA256   : $sha"
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Next real test:' -ForegroundColor Yellow
Write-Host '1. Install r46.'
Write-Host '2. Start Codex Desktop + Transfer.'
Write-Host '3. Open 路由 -> 全链路健康 -> 旧会话恢复（先预览）.'
Write-Host '4. First test ONLY read-only preview against the broken old thread.'
Write-Host '5. If preview is correct, click 同 ID 回退 1 轮 only once, then send one short message.'
