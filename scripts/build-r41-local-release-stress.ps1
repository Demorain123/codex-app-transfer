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

Write-Host 'Codex App Transfer r41 - Explicit Port Repair release validation' -ForegroundColor Green
Write-Host 'Acceptance UX: port occupied -> user clicks Try repair -> port becomes free -> user can click Start forwarding again.'
Write-Host 'Base: r39 owner-thread + r40 Windows Port Guard; r41 adds explicit user-triggered live foreign-owner release.'

# Refuse to erase pre-existing work, including untracked generated files.
$dirtyBefore = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inspect Git working-tree state before r41 validation.'
}
if ($dirtyBefore.Count -gt 0) {
    throw "r41 validation requires a completely clean working tree. Preserve edits, then reset/clean generated files before retrying. Current entries:`n$($dirtyBefore -join "`n")"
}
$cleanHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($cleanHead)) {
    throw 'Unable to resolve clean r41 HEAD commit.'
}
Write-Host "Clean baseline : $cleanHead" -ForegroundColor DarkGray

# Reuse the proven V:-local Rust/MSVC/SDK/libclang environment. The r39 probe
# temporarily materializes older overlays; discard those source mutations afterward.
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

Write-Host "`n[r41 0b/7] Restore clean r41 source baseline after environment probe" -ForegroundColor Green
Invoke-Checked git 'reset' '--hard' $cleanHead
Invoke-Checked git 'clean' '-fd'
$headAfterReset = (& git rev-parse HEAD).Trim()
$dirtyAfter = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $headAfterReset -ne $cleanHead -or $dirtyAfter.Count -gt 0) {
    throw "r41 baseline restore failed. Expected clean HEAD $cleanHead; actual HEAD $headAfterReset; dirty=$($dirtyAfter -join ', ')"
}
Write-Host 'r41 source baseline: CLEAN (probe environment retained; tracked + generated source mutations discarded)' -ForegroundColor Green

Write-Host "`n[r41 1/7] Materialize r41 overlays exactly once" -ForegroundColor Green
Invoke-Checked python 'scripts/apply_r41_unified.py'

Write-Host "`n[r41 2/7] Normalize generated Rust + formatting/whitespace gate" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked git 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'

Write-Host "`n[r41 3/7] Build real frontend with native npm.cmd" -ForegroundColor Green
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
    throw "r41 frontend preflight failed: $frontendIndex was not generated."
}
$frontendText = Get-Content -LiteralPath $frontendIndex -Raw -Encoding UTF8
if ($frontendText -match 'dev placeholder|Frontend not built|前端未构建') {
    throw 'r41 frontend preflight failed: dist/index.html is still the debug placeholder.'
}

if (-not $SkipStress) {
    Write-Host "`n[r41 4/7] Preserve r39 owner-thread proof (100 generations, Release CRT)" -ForegroundColor Green
    $lifecycleLog = Join-Path $env:TEMP 'r41-r39-lifecycle-proof-last.log'
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

    Write-Host "`n[r41 5/7] Preserve r40 Windows Port Guard proof" -ForegroundColor Green
    $guardLog = Join-Path $env:TEMP 'r41-r40-windows-port-guard-proof-last.log'
    Invoke-CargoProof `
        -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','windows_port_guard_r40','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript $guardLog `
        -ExpectedTests @(
            'windows_port_guard_r40_clears_inherit_bit',
            'windows_port_guard_r40_classifies_foreign_and_stale_binders'
        ) `
        -ExpectedCount 2 `
        -Label 'r40 Windows port guard regression proof'

    Write-Host "`n[r41 6/7] Explicit repair tests: self-protection + dedicated foreign PowerShell owner release" -ForegroundColor Green
    $repairLog = Join-Path $env:TEMP 'r41-explicit-port-repair-proof-last.log'
    Invoke-CargoProof `
        -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','windows_port_repair_r41','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript $repairLog `
        -ExpectedTests @(
            'windows_port_repair_r41_rejects_self_owner',
            'windows_port_repair_r41_terminates_explicit_foreign_owner'
        ) `
        -ExpectedCount 2 `
        -Label 'r41 explicit port repair proof'
} else {
    Write-Host "`n[r41 4-6/7] Stress/guard/repair tests skipped by request" -ForegroundColor Yellow
}

if (-not $SkipCargoCheck) {
    Write-Host "`n[r41 7/7] Windows app cargo check" -ForegroundColor Green
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[r41 7/7] cargo check skipped by request" -ForegroundColor Yellow
}

$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
Write-Host "`nR41 EXPLICIT PORT REPAIR VALIDATION PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'Acceptance requires: r39 100-generation 2/2 + r40 guard 2/2 + r41 explicit repair 2/2 + cargo check.' -ForegroundColor Green
Write-Host 'Installed UX acceptance: foreign owner -> click Try repair -> port FREE -> click Start forwarding -> success.' -ForegroundColor Green
