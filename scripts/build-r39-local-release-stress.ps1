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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r39 - RELEASE-CRT lifecycle validation' -ForegroundColor Green
Write-Host 'Phase A: reuse the proven Bindgen/MSVC probe and materialize/format gates.'

# The existing probe imports VsDevCmd, verifies MSVC/Windows SDK headers, and
# supplies BINDGEN_EXTRA_CLANG_ARGS. Force the old debug-profile stress/check
# stages off here because BoringSSL Debug uses the Debug DLL CRT (/MDd), while
# the Rust test executable is linked against the non-debug DLL CRT (/MD).
#
# A release-profile cargo build also executes src-tauri/build.rs. That build
# script intentionally rejects the debug fallback frontend/dist placeholder, so
# release validation must always build the real frontend first. Do this through
# the existing fast gate so node_modules and the V:-resident npm cache are reused.
$probeArgs = @{
    SkipStress = $true
    SkipCargoCheck = $true
    Frontend = $true
}

$probe = Join-Path $PSScriptRoot 'build-r39-local-fast-bindgen-probe.ps1'
& $probe @probeArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# Fail before the expensive release Rust build if the frontend prerequisite was
# not actually produced. This mirrors the release guard in src-tauri/build.rs,
# but catches the problem immediately instead of after native dependencies build.
$frontendIndex = Join-Path $repoRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "Release frontend preflight failed: $frontendIndex was not generated."
}
$frontendIndexText = Get-Content -LiteralPath $frontendIndex -Raw -Encoding UTF8
if ($frontendIndexText -match 'dev placeholder|Frontend not built|前端未构建') {
    throw 'Release frontend preflight failed: frontend/dist/index.html is still the debug placeholder.'
}
Write-Host "Release frontend: PASS ($frontendIndex)" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) {
    throw 'CARGO_HOME is empty after the r39 probe.'
}
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) {
    throw "V:-local cargo.exe was not found after the r39 probe: $cargoExe"
}

if (-not $SkipStress) {
    Write-Host "`n[release 3/5] r39 same-port owner-thread stress tests (100 generations, Release CRT)" -ForegroundColor Green
    Invoke-Checked $cargoExe 'test' '-p' 'codex-app-transfer' 'proxy_lifecycle_r39' '--release' '--target' $target '--' '--nocapture'
} else {
    Write-Host "`n[release 3/5] Stress tests skipped by request" -ForegroundColor Yellow
}

if (-not $SkipCargoCheck) {
    Write-Host "`n[release 4/5] Windows app cargo check" -ForegroundColor Green
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[release 4/5] cargo check skipped by request" -ForegroundColor Yellow
}

Write-Host "`nR39 RELEASE-CRT LIFECYCLE VALIDATION PASS" -ForegroundColor Green
Write-Host 'If the 100-generation test passed, the next step is to fold the proven VsDevCmd/Bindgen setup and Release-CRT stress policy into the normal fast/package gates.' -ForegroundColor Green
