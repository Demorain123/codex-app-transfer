#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$Frontend,
    [switch]$SkipCargoCheck,
    [switch]$SkipStress
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

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r39 local build policy requires the repository itself on physical V:. Current: $repoRoot"
}

# CAS-R39-V-DRIVE-LOCAL-BUILD
$cacheRoot = 'V:\Codex-App-Transfer-DevCache'
$env:CARGO_HOME = Join-Path $cacheRoot 'cargo-home'
$env:CARGO_TARGET_DIR = Join-Path $cacheRoot 'target\r39'
$env:npm_config_cache = Join-Path $cacheRoot 'npm-cache'
$env:NPM_CONFIG_CACHE = $env:npm_config_cache
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:CODEX_APP_TRANSFER_LOCAL_BUILD = 'r39'

foreach ($dir in @(
    $env:CARGO_HOME,
    $env:CARGO_TARGET_DIR,
    $env:npm_config_cache,
    $env:TEMP
)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

# cargo-installed helper binaries for this project live on V as well.
$env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH

Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r39 - LOCAL FAST gate' -ForegroundColor Green
Write-Host "Repo         : $repoRoot"
Write-Host "Cargo home   : $env:CARGO_HOME"
Write-Host "Cargo target : $env:CARGO_TARGET_DIR"
Write-Host "npm cache    : $env:npm_config_cache"
Write-Host "TEMP/TMP     : $env:TEMP"
Write-Host 'Policy       : no automatic port switching; fixed-port lifecycle regression'

Require-Command git
Require-Command python
Require-Command cargo
Require-Command rustc
Require-Command rustup
if ($Frontend) {
    Require-Command node
    Require-Command npm
}

Write-Host "`n[1/5] Materialize r39 overlays" -ForegroundColor Green
Invoke-Checked python 'scripts/apply_r39_unified.py'

Write-Host "`n[2/5] Rust formatting gate" -ForegroundColor Green
Invoke-Checked cargo 'fmt' '--all' '--' '--check'

if (-not $SkipStress) {
    Write-Host "`n[3/5] r39 same-port owner-thread stress tests (100 generations)" -ForegroundColor Green
    Invoke-Checked cargo 'test' '-p' 'codex-app-transfer' 'proxy_lifecycle_r39' '--target' $target '--' '--nocapture'
} else {
    Write-Host "`n[3/5] Stress tests skipped by request" -ForegroundColor Yellow
}

if (-not $SkipCargoCheck) {
    Write-Host "`n[4/5] Windows app cargo check" -ForegroundColor Green
    Invoke-Checked cargo 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[4/5] cargo check skipped by request" -ForegroundColor Yellow
}

if ($Frontend) {
    Write-Host "`n[5/5] Frontend install/build" -ForegroundColor Green
    Invoke-Checked npm '--prefix' 'frontend' 'ci'
    Invoke-Checked npm '--prefix' 'frontend' 'run' 'build'
} else {
    Write-Host "`n[5/5] Frontend skipped (use -Frontend when UI changed)" -ForegroundColor DarkGray
}

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$version = if (Test-Path $versionPath) { Get-Content $versionPath -Raw -Encoding UTF8 } else { '<missing>' }
Write-Host "`nLOCAL FAST PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'All project build/cache/temp outputs for this run are rooted on V:.' -ForegroundColor Green
