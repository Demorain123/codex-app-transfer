#requires -Version 7.0

[CmdletBinding()]
param(
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

function Invoke-CargoProof {
    param(
        [Parameter(Mandatory)][string]$CargoExe,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Transcript,
        [Parameter(Mandatory)][string[]]$ExpectedTests,
        [Parameter(Mandatory)][int]$ExpectedCount,
        [Parameter(Mandatory)][string]$Label
    )

    Remove-Item -LiteralPath $Transcript -Force -ErrorAction SilentlyContinue
    Write-Host "`n> $CargoExe $($Arguments -join ' ')" -ForegroundColor Cyan
    & $CargoExe @Arguments 2>&1 | Tee-Object -FilePath $Transcript
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Label failed ($exitCode). Transcript: $Transcript"
    }

    $text = Get-Content -LiteralPath $Transcript -Raw -Encoding UTF8
    foreach ($expected in $ExpectedTests) {
        if ($text -notmatch [regex]::Escape($expected)) {
            throw "$Label did not visibly execute expected test: $expected. Transcript: $Transcript"
        }
    }
    if ($text -notmatch ("(?m)^running\s+{0}\s+tests\s*$" -f $ExpectedCount)) {
        throw "$Label did not visibly report running $ExpectedCount tests. Transcript: $Transcript"
    }
    if ($text -notmatch ("test result:\s+ok\.\s+{0} passed;\s+0 failed;" -f $ExpectedCount)) {
        throw "$Label did not prove $ExpectedCount passed / 0 failed. Transcript: $Transcript"
    }
    Write-Host "${Label}: PASS ($ExpectedCount/$ExpectedCount visible)" -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r40 - Windows Port Guard release validation' -ForegroundColor Green
Write-Host 'Base: validated r39 owner-thread lifecycle; r40 adds handle-inheritance hardening + owner classification.'

# Reuse the already-proven V:-local Rust/MSVC/SDK/libclang setup. The r39 probe
# materializes r39 first; r40 is intentionally an outer overlay applied immediately
# afterwards. Environment variables set by the invoked script remain process-scoped.
$probe = Join-Path $PSScriptRoot 'build-r39-local-fast-bindgen-probe.ps1'
& $probe -SkipStress -SkipCargoCheck
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) {
    throw 'CARGO_HOME is empty after the V:-local toolchain probe.'
}
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) {
    throw "V:-local cargo.exe was not found: $cargoExe"
}

Write-Host "`n[r40 1/6] Materialize r40 overlays" -ForegroundColor Green
Invoke-Checked python 'scripts/apply_r40_unified.py'

Write-Host "`n[r40 2/6] Normalize generated Rust + formatting/whitespace gate" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked git 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'

Write-Host "`n[r40 3/6] Build real frontend with native npm.cmd" -ForegroundColor Green
$npmCommand = Get-Command 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $npmCommand) {
    throw 'npm.cmd was not found as a native application on PATH.'
}
$npmCmd = $npmCommand.Source
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

$frontendIndex = Join-Path $repoRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "r40 frontend preflight failed: $frontendIndex was not generated."
}
$frontendText = Get-Content -LiteralPath $frontendIndex -Raw -Encoding UTF8
if ($frontendText -match 'dev placeholder|Frontend not built|前端未构建') {
    throw 'r40 frontend preflight failed: dist/index.html is still the debug placeholder.'
}

if (-not $SkipStress) {
    Write-Host "`n[r40 4/6] Preserve r39 owner-thread proof (100 generations, Release CRT)" -ForegroundColor Green
    $lifecycleLog = Join-Path $env:TEMP 'r40-r39-lifecycle-proof-last.log'
    Invoke-CargoProof `
        -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','proxy_lifecycle_r39','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript $lifecycleLog `
        -ExpectedTests @(
            'proxy_lifecycle_r39_owner_thread_join_rebind_100_generations',
            'proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier'
        ) `
        -ExpectedCount 2 `
        -Label 'r39 lifecycle regression proof'

    Write-Host "`n[r40 5/6] Windows socket inheritance + owner-classification guard tests" -ForegroundColor Green
    $guardLog = Join-Path $env:TEMP 'r40-windows-port-guard-proof-last.log'
    Invoke-CargoProof `
        -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','windows_port_guard_r40','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript $guardLog `
        -ExpectedTests @(
            'windows_port_guard_r40_clears_inherit_bit',
            'windows_port_guard_r40_classifies_foreign_and_stale_binders'
        ) `
        -ExpectedCount 2 `
        -Label 'r40 Windows port guard proof'
} else {
    Write-Host "`n[r40 4-5/6] Stress/guard tests skipped by request" -ForegroundColor Yellow
}

if (-not $SkipCargoCheck) {
    Write-Host "`n[r40 6/6] Windows app cargo check" -ForegroundColor Green
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[r40 6/6] cargo check skipped by request" -ForegroundColor Yellow
}

$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
Write-Host "`nR40 WINDOWS PORT GUARD VALIDATION PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'Acceptance requires: r39 100-generation lifecycle 2/2 + r40 Windows port guard 2/2 + cargo check.' -ForegroundColor Green
