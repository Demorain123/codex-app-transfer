#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipCargoCheck,
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
    if ($exitCode -ne 0) { throw "$Label failed ($exitCode). Transcript: $Transcript" }
    $text = Get-Content -LiteralPath $Transcript -Raw -Encoding UTF8
    foreach ($expected in $ExpectedTests) {
        if ($text -notmatch [regex]::Escape($expected)) { throw "$Label did not execute: $expected" }
    }
    if ($text -notmatch ("(?m)^running\s+{0}\s+tests\s*$" -f $ExpectedCount)) { throw "$Label did not report running $ExpectedCount tests" }
    if ($text -notmatch ("test result:\s+ok\.\s+{0} passed;\s+0 failed;" -f $ExpectedCount)) { throw "$Label did not prove $ExpectedCount passed / 0 failed" }
    Write-Host "${Label}: PASS ($ExpectedCount/$ExpectedCount visible)" -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r43 - Health + Model-Switch + MCP Hardening' -ForegroundColor Green
Write-Host 'Target: clear stale fault votes, isolate active shared failures, diagnose pre-switch compact 5xx, verify MCP cleanup.'

$dirtyBefore = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git working tree.' }
if ($dirtyBefore.Count -gt 0) { throw "r43 validation requires a completely clean working tree:`n$($dirtyBefore -join "`n")" }
$cleanHead = (& git rev-parse HEAD).Trim()
Write-Host "Clean baseline : $cleanHead" -ForegroundColor DarkGray

$probe = Join-Path $PSScriptRoot 'build-r39-local-fast-bindgen-probe.ps1'
& $probe -SkipStress -SkipCargoCheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) { throw 'CARGO_HOME is empty after environment probe.' }
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

Write-Host "`n[r43 0/7] Restore clean r43 baseline" -ForegroundColor Green
Invoke-Checked git 'reset' '--hard' $cleanHead
Invoke-Checked git 'clean' '-fd'
if (@(& git status --porcelain).Count -gt 0) { throw 'r43 baseline restore left a dirty tree.' }

Write-Host "`n[r43 1/7] Materialize r43 exactly once" -ForegroundColor Green
Invoke-Checked python 'scripts/apply_r43_unified.py'

Write-Host "`n[r43 2/7] Format + whitespace + static review gate" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked git 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'
Invoke-Checked python 'scripts/review_r43_health_mcp_hardening.py'

if (-not $SkipLegacyStress) {
    Write-Host "`n[r43 3/7] Preserve r39/r40/r41 Windows regression proofs" -ForegroundColor Green
    Invoke-CargoProof -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','proxy_lifecycle_r39','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript (Join-Path $env:TEMP 'r43-r39-lifecycle-proof-last.log') `
        -ExpectedTests @('proxy_lifecycle_r39_owner_thread_join_rebind_100_generations','proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier') `
        -ExpectedCount 2 -Label 'r39 lifecycle regression proof'
    Invoke-CargoProof -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','windows_port_guard_r40','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript (Join-Path $env:TEMP 'r43-r40-port-guard-proof-last.log') `
        -ExpectedTests @('windows_port_guard_r40_clears_inherit_bit','windows_port_guard_r40_classifies_foreign_and_stale_binders') `
        -ExpectedCount 2 -Label 'r40 port guard regression proof'
    Invoke-CargoProof -CargoExe $cargoExe `
        -Arguments @('test','-p','codex-app-transfer','windows_port_repair_r41','--release','--target',$target,'--','--nocapture','--test-threads=1') `
        -Transcript (Join-Path $env:TEMP 'r43-r41-repair-proof-last.log') `
        -ExpectedTests @('windows_port_repair_r41_rejects_self_owner','windows_port_repair_r41_terminates_explicit_foreign_owner') `
        -ExpectedCount 2 -Label 'r41 explicit repair regression proof'
} else {
    Write-Host "`n[r43 3/7] Legacy Windows stress skipped by request" -ForegroundColor Yellow
}

Write-Host "`n[r43 4/7] Preserve r42 Grok effective-name collision proof" -ForegroundColor Green
Invoke-CargoProof -CargoExe $cargoExe `
    -Arguments @('test','-p','codex-app-transfer-adapters','grok_tool_collision_r42','--release','--target',$target,'--','--nocapture','--test-threads=1') `
    -Transcript (Join-Path $env:TEMP 'r43-r42-grok-collision-proof-last.log') `
    -ExpectedTests @(
        'grok_tool_collision_r42_native_plus_function_web_search_is_one',
        'grok_tool_collision_r42_duplicate_native_web_search_is_one',
        'grok_tool_collision_r42_function_first_preserves_client_routing',
        'grok_tool_collision_r42_ordinary_function_duplicate_still_dedups',
        'grok_tool_collision_r42_unique_tools_are_preserved',
        'grok_tool_collision_r42_discovered_function_cannot_duplicate_native_web_search'
    ) `
    -ExpectedCount 6 -Label 'r42 Grok collision regression proof'

Write-Host "`n[r43 5/7] r43 lifecycle / compaction attribution unit tests" -ForegroundColor Green
Invoke-CargoProof -CargoExe $cargoExe `
    -Arguments @('test','-p','codex-app-transfer','r43_','--release','--target',$target,'--','--nocapture','--test-threads=1') `
    -Transcript (Join-Path $env:TEMP 'r43-health-mcp-proof-last.log') `
    -ExpectedTests @(
        'r43_lifecycle_failure_predicate_clears_on_success',
        'r43_compaction_transition_requires_fresh_5xx_and_signal'
    ) `
    -ExpectedCount 2 -Label 'r43 health/compaction proof'

if (-not $SkipCargoCheck) {
    Write-Host "`n[r43 6/7] Windows app cargo check" -ForegroundColor Green
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[r43 6/7] cargo check skipped by request" -ForegroundColor Yellow
}

Write-Host "`n[r43 7/7] Version/invariant gate" -ForegroundColor Green
$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
if ($version -notmatch 'compat_revision=43' -or $version -notmatch 'app_version=2\.4\.5\+43') { throw 'r43 version stamp mismatch' }
Invoke-Checked python 'scripts/review_r43_health_mcp_hardening.py'
Write-Host 'R43 HEALTH + MODEL-SWITCH + MCP HARDENING VALIDATION PASS' -ForegroundColor Green
Write-Host $version.Trim()
Write-Host 'No real-account test is performed by this gate.' -ForegroundColor Green
