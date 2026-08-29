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
    $global:LASTEXITCODE = 0
    & $Command @Arguments
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed ($exitCode): $Command $($Arguments -join ' ')"
    }
}

function Parse-RustVersion {
    param([Parameter(Mandatory)][string]$Line)
    if ($Line -notmatch '^rustc\s+(\d+)\.(\d+)\.(\d+)') {
        throw "Unable to parse rustc version: $Line"
    }
    [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
}

function Get-StableRustVersion {
    param([Parameter(Mandatory)][string]$Rustup)
    $global:LASTEXITCODE = 0
    $output = @(& $Rustup run stable rustc --version 2>&1)
    $exitCode = $global:LASTEXITCODE
    $line = $output | Select-Object -First 1
    if ($exitCode -ne 0 -or -not $line) { return $null }
    return Parse-RustVersion ([string]$line).Trim()
}

function Invoke-StableCargo {
    param(
        [Parameter(Mandatory)][string]$Rustup,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "`n> rustup run stable cargo $($Arguments -join ' ')" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Rustup run stable cargo @Arguments
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed ($exitCode): rustup run stable cargo $($Arguments -join ' ')"
    }
}

function Find-CMake {
    $cmd = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command cmake -ErrorAction SilentlyContinue }
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'CMake\bin\cmake.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'CMake\bin\cmake.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    return ($candidates | Select-Object -First 1)
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
Write-Host 'Successful stages are reused automatically.' -ForegroundColor Green

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$currentVersion = if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
    Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
} else { '' }
$recoveryBackend = Join-Path $repoRoot 'src-tauri\src\admin\handlers\thread_recovery.rs'
$alreadyMaterialized = $currentVersion -match 'compat_revision=46' -and
    $currentVersion -match 'app_version=2\.4\.5\+46' -and
    (Test-Path -LiteralPath $recoveryBackend -PathType Leaf) -and
    ((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY')

Write-Host "`n[1/7] Materialize r46" -ForegroundColor Green
if ($alreadyMaterialized -and -not $ForceMaterialize) {
    Write-Host 'Warm r46 materialization detected; SKIP.' -ForegroundColor Green
} else {
    Invoke-Checked 'python' '.\scripts\apply_r46_unified.py'
}

$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=46' -or $versionFile -notmatch 'app_version=2\.4\.5\+46') {
    throw 'r46 materialization completed but version stamp is not 2.4.5+46.'
}
Write-Host $versionFile.Trim() -ForegroundColor Green

Write-Host "`n[2/7] Frontend assets" -ForegroundColor Green
$frontendDir = Join-Path $repoRoot 'frontend'
$nodeModules = Join-Path $frontendDir 'node_modules'
$frontendIndex = Join-Path $frontendDir 'dist\index.html'
if ((Test-Path -LiteralPath $frontendIndex -PathType Leaf) -and -not $ForceFrontendBuild) {
    Write-Host "Warm frontend assets detected; SKIP: $frontendIndex" -ForegroundColor Green
} else {
    Push-Location $frontendDir
    try {
        if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
            Invoke-Checked 'npm.cmd' 'ci'
        }
        Invoke-Checked 'npm.cmd' 'run' 'build'
    } finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
        throw "Frontend build completed but dist/index.html is missing: $frontendIndex"
    }
}

Write-Host "`n[3/7] Ensure stable Rust >= 1.95" -ForegroundColor Green
$rustup = (Get-Command rustup.exe -ErrorAction SilentlyContinue).Source
if (-not $rustup) { $rustup = (Get-Command rustup -ErrorAction SilentlyContinue).Source }
if (-not $rustup) { throw 'rustup was not found in PATH.' }

$rustVersion = Get-StableRustVersion $rustup
if ($rustVersion -and $rustVersion -ge $minimumRust) {
    Write-Host "Stable Rust already ready: $rustVersion; SKIP rustup update." -ForegroundColor Green
} else {
    Write-Host 'Stable Rust missing/too old; updating stable toolchain...' -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $rustup update stable
    $updateExit = $global:LASTEXITCODE
    $rustVersion = Get-StableRustVersion $rustup
    if (-not $rustVersion -or $rustVersion -lt $minimumRust) {
        throw "Stable Rust is still unavailable or < $minimumRust after rustup update (exit=$updateExit)."
    }
    if ($updateExit -ne 0) {
        Write-Warning "rustup update returned $updateExit, but stable rustc $rustVersion is installed, so continuing."
    }
}
Write-Host "Using stable rustc: $rustVersion" -ForegroundColor Green

Write-Host "`n[4/7] Locate Tauri" -ForegroundColor Green
$tauriAvailable = $false
try {
    $global:LASTEXITCODE = 0
    & $rustup run stable cargo tauri --version *> $null
    $tauriAvailable = ($global:LASTEXITCODE -eq 0)
} catch { $tauriAvailable = $false }
if (-not $tauriAvailable) {
    if ($SkipTauriInstall) { throw 'cargo-tauri is not installed and -SkipTauriInstall was specified.' }
    Write-Host 'cargo-tauri missing; installing once...' -ForegroundColor Yellow
    Invoke-StableCargo $rustup 'install' 'tauri-cli' '--version' '^2' '--locked'
} else {
    Write-Host 'cargo-tauri already available; SKIP install.' -ForegroundColor Green
}

Write-Host "`n[5/7] Ensure CMake for boring-sys2" -ForegroundColor Green
$cmake = Find-CMake
if (-not $cmake) {
    $winget = (Get-Command winget.exe -ErrorAction SilentlyContinue).Source
    if (-not $winget) { $winget = (Get-Command winget -ErrorAction SilentlyContinue).Source }
    if (-not $winget) {
        throw 'CMake is required by boring-sys2, but cmake and winget were both not found.'
    }
    Write-Host 'CMake missing; installing Kitware.CMake once with winget...' -ForegroundColor Yellow
    Invoke-Checked $winget 'install' '--id' 'Kitware.CMake' '--exact' '--silent' '--accept-package-agreements' '--accept-source-agreements'
    $cmake = Find-CMake
    if (-not $cmake) {
        throw 'winget reported success, but cmake.exe was still not found under PATH or Program Files.'
    }
} else {
    Write-Host "CMake already available; SKIP install: $cmake" -ForegroundColor Green
}
$cmakeBin = Split-Path -Parent $cmake
if (($env:PATH -split ';') -notcontains $cmakeBin) {
    $env:PATH = "$cmakeBin;$env:PATH"
}
$env:CMAKE = $cmake
$global:LASTEXITCODE = 0
$cmakeVersion = @(& $cmake --version 2>&1) | Select-Object -First 1
if ($global:LASTEXITCODE -ne 0) { throw "cmake --version failed: $cmake" }
Write-Host "Using $cmakeVersion" -ForegroundColor Green

Write-Host "`n[6/7] Build actual Windows NSIS package" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-StableCargo $rustup 'tauri' 'build' '--target' $target '--bundles' 'nsis'
} finally {
    Pop-Location
}

Write-Host "`n[7/7] Copy real-use installer" -ForegroundColor Green
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
    materialization = 'passed/reused'
    frontendBuild = 'passed/reused'
    rustc = $rustVersion.ToString()
    cmake = [string]$cmakeVersion
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
Write-Host 'Next: install r46, open 路由 -> 全链路健康 -> 旧会话恢复（先预览）.' -ForegroundColor Yellow
