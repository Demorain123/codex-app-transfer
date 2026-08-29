#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipTauriInstall,
    [switch]$ForceMaterialize,
    [switch]$ForceFrontendBuild
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

function Get-RustVersion {
    param([Parameter(Mandatory)][string]$Rustc)
    $line = (& $Rustc --version).Trim()
    if ($LASTEXITCODE -ne 0) { throw "rustc --version failed: $Rustc" }
    if ($line -notmatch '^rustc\s+(\d+)\.(\d+)\.(\d+)') {
        throw "Unable to parse rustc version: $line"
    }
    [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'
$minimumRust = [version]'1.95.0'

Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Codex App Transfer r46 - FAST REAL-USE BUILD' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Purpose: get to real old-thread testing as fast as possible.'
Write-Host 'Skipped: Rust unit tests / cargo check / legacy stress / release proof.' -ForegroundColor Yellow
Write-Host 'Included: r46 materialization + frontend assets + actual Windows NSIS compilation.'

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$currentVersion = if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
    Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
} else { '' }
$recoveryBackend = Join-Path $repoRoot 'src-tauri\src\admin\handlers\thread_recovery.rs'
$alreadyMaterialized = $currentVersion -match 'compat_revision=46' -and
    $currentVersion -match 'app_version=2\.4\.5\+46' -and
    (Test-Path -LiteralPath $recoveryBackend -PathType Leaf) -and
    ((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY')

Write-Host "`n[1/6] Materialize r46" -ForegroundColor Green
if ($alreadyMaterialized -and -not $ForceMaterialize) {
    Write-Host 'Warm r46 materialization detected; reusing current generated tree.' -ForegroundColor Green
} else {
    Invoke-Checked 'python' '.\scripts\apply_r46_unified.py'
}

$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=46' -or $versionFile -notmatch 'app_version=2\.4\.5\+46') {
    throw 'r46 materialization completed but version stamp is not 2.4.5+46.'
}
Write-Host $versionFile.Trim() -ForegroundColor Green

Write-Host "`n[2/6] Frontend assets" -ForegroundColor Green
$frontendDir = Join-Path $repoRoot 'frontend'
$nodeModules = Join-Path $frontendDir 'node_modules'
$frontendIndex = Join-Path $frontendDir 'dist\index.html'
if ((Test-Path -LiteralPath $frontendIndex -PathType Leaf) -and -not $ForceFrontendBuild) {
    Write-Host "Warm frontend assets detected; reusing: $frontendIndex" -ForegroundColor Green
} else {
    Push-Location $frontendDir
    try {
        if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
            Write-Host 'frontend/node_modules missing; running npm ci once...' -ForegroundColor Yellow
            Invoke-Checked 'npm.cmd' 'ci'
        }
        Invoke-Checked 'npm.cmd' 'run' 'build'
    } finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
        throw "Frontend build completed but dist/index.html is missing: $frontendIndex"
    }
    Write-Host "Frontend assets ready: $frontendIndex" -ForegroundColor Green
}

Write-Host "`n[3/6] Ensure Rust >= 1.95" -ForegroundColor Green
$rustc = (Get-Command rustc.exe -ErrorAction SilentlyContinue).Source
if (-not $rustc) { $rustc = (Get-Command rustc -ErrorAction SilentlyContinue).Source }
if (-not $rustc) { throw 'rustc was not found in PATH.' }
$rustVersion = Get-RustVersion $rustc
Write-Host "Current rustc: $rustVersion ($rustc)"
if ($rustVersion -lt $minimumRust) {
    $rustup = (Get-Command rustup.exe -ErrorAction SilentlyContinue).Source
    if (-not $rustup) { $rustup = (Get-Command rustup -ErrorAction SilentlyContinue).Source }
    if (-not $rustup) {
        throw "rustc $rustVersion is too old. r46 dependency libsqlite3-sys 0.38.1 requires Rust >= 1.95, and rustup was not found."
    }
    Write-Host "Rust $rustVersion is too old; updating stable toolchain to >= 1.95..." -ForegroundColor Yellow
    Invoke-Checked $rustup 'update' 'stable'
    $env:RUSTUP_TOOLCHAIN = 'stable'
    $rustc = (Get-Command rustc.exe -ErrorAction SilentlyContinue).Source
    if (-not $rustc) { $rustc = (Get-Command rustc -ErrorAction SilentlyContinue).Source }
    $rustVersion = Get-RustVersion $rustc
    Write-Host "Updated rustc: $rustVersion"
    if ($rustVersion -lt $minimumRust) {
        throw "rustup update stable completed, but rustc is still $rustVersion; need >= $minimumRust."
    }
}

Write-Host "`n[4/6] Locate Cargo / Tauri" -ForegroundColor Green
$cargo = (Get-Command cargo.exe -ErrorAction SilentlyContinue).Source
if (-not $cargo) { $cargo = (Get-Command cargo -ErrorAction SilentlyContinue).Source }
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

Write-Host "`n[5/6] Build actual Windows NSIS package" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked $cargo 'tauri' 'build' '--target' $target '--bundles' 'nsis'
} finally {
    Pop-Location
}

Write-Host "`n[6/6] Copy real-use installer" -ForegroundColor Green
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
if (-not $setup) { throw "NSIS installer not found under: $bundleRoot" }

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
    frontendBuild = 'passed'
    rustc = $rustVersion.ToString()
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
