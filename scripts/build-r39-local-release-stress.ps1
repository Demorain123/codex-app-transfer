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
# Do NOT ask the fast gate to build the frontend here. On Windows/PowerShell an
# unqualified `npm` can resolve through a shim/function before the native npm.cmd
# launcher. Keep the probe focused on Rust/MSVC/Bindgen, then invoke npm.cmd by
# its resolved application path below.
$probeArgs = @{
    SkipStress = $true
    SkipCargoCheck = $true
}

$probe = Join-Path $PSScriptRoot 'build-r39-local-fast-bindgen-probe.ps1'
& $probe @probeArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "`n[release 2b/5] Build real frontend with native npm.cmd" -ForegroundColor Green
$npmCommand = Get-Command 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $npmCommand) {
    throw 'npm.cmd was not found as a native application on PATH. Install/repair Node.js npm before release validation.'
}
$npmCmd = $npmCommand.Source
Write-Host "npm.cmd      : $npmCmd"
Invoke-Checked $npmCmd '--version'

$frontendDir = Join-Path $repoRoot 'frontend'
$nodeModules = Join-Path $frontendDir 'node_modules'
Push-Location $frontendDir
try {
    if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
        Invoke-Checked $npmCmd 'ci' '--prefer-offline' '--no-audit'
    } else {
        Write-Host 'Reusing existing frontend/node_modules; skipping npm ci.' -ForegroundColor DarkGray
    }
    Invoke-Checked $npmCmd 'run' 'build'
} finally {
    Pop-Location
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
