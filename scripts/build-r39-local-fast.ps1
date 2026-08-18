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
$env:RUSTUP_HOME = Join-Path $cacheRoot 'rustup-home'
$env:CARGO_TARGET_DIR = Join-Path $cacheRoot 'target\r39'
$env:npm_config_cache = Join-Path $cacheRoot 'npm-cache'
$env:NPM_CONFIG_CACHE = $env:npm_config_cache
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:CODEX_APP_TRANSFER_LOCAL_BUILD = 'r39'
$env:RUSTUP_TOOLCHAIN = 'stable'

foreach ($dir in @(
    $env:CARGO_HOME,
    $env:RUSTUP_HOME,
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
Write-Host "Rustup home  : $env:RUSTUP_HOME"
Write-Host "Cargo target : $env:CARGO_TARGET_DIR"
Write-Host "npm cache    : $env:npm_config_cache"
Write-Host "TEMP/TMP     : $env:TEMP"
Write-Host 'Policy       : no automatic port switching; fixed-port lifecycle regression'

Require-Command git
Require-Command python
Require-Command rustup
if ($Frontend) {
    Require-Command node
    Require-Command npm
}

# libsqlite3-sys 0.38.x uses cfg_select!, which is stable from Rust 1.95.
# Mirror GitHub Actions' `dtolnay/rust-toolchain@stable`, but install/cache the
# toolchain under V: so local iteration neither depends on an older global
# toolchain nor consumes C: for Rust toolchains.
Write-Host "`n[0/5] Ensure current stable Rust toolchain on V:" -ForegroundColor Green
Invoke-Checked rustup 'toolchain' 'install' 'stable' '--profile' 'minimal' '--component' 'rustfmt' '--target' $target
$rustcVersion = (& rustup run stable rustc --version).Trim()
$cargoVersion = (& rustup run stable cargo --version).Trim()
Write-Host "Rust          : $rustcVersion"
Write-Host "Cargo         : $cargoVersion"
if ($rustcVersion -notmatch '^rustc\s+(\d+)\.(\d+)\.(\d+)') {
    throw "Unable to parse rustc version: $rustcVersion"
}
$rustMajor = [int]$Matches[1]
$rustMinor = [int]$Matches[2]
if ($rustMajor -lt 1 -or ($rustMajor -eq 1 -and $rustMinor -lt 95)) {
    throw "Rust 1.95+ is required by the resolved dependency set; active stable is $rustcVersion"
}

Write-Host "`n[1/5] Materialize r39 overlays" -ForegroundColor Green
Invoke-Checked python 'scripts/apply_r39_unified.py'

# The release workflow intentionally normalizes generated Rust after replay because
# several historical overlay generators predate current rustfmt output. Local builds
# must mirror that exact policy instead of failing on formatting-only diffs.
Write-Host "`n[2/5] Normalize generated Rust + formatting/whitespace gate" -ForegroundColor Green
Invoke-Checked cargo 'fmt' '--all'
Invoke-Checked git 'diff' '--check'
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
    Write-Host "`n[5/5] Frontend build (reuse V: node_modules/cache when possible)" -ForegroundColor Green
    $nodeModules = Join-Path $repoRoot 'frontend\node_modules'
    if (-not (Test-Path $nodeModules)) {
        Invoke-Checked npm '--prefix' 'frontend' 'ci' '--prefer-offline' '--no-audit'
    } else {
        Write-Host "Reusing existing V:\...\frontend\node_modules; skipping npm ci." -ForegroundColor DarkGray
    }
    Invoke-Checked npm '--prefix' 'frontend' 'run' 'build'
} else {
    Write-Host "`n[5/5] Frontend skipped (use -Frontend when UI changed)" -ForegroundColor DarkGray
}

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$version = if (Test-Path $versionPath) { Get-Content $versionPath -Raw -Encoding UTF8 } else { '<missing>' }
Write-Host "`nLOCAL FAST PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'All project build/cache/temp/toolchain outputs for this run are rooted on V:.' -ForegroundColor Green
