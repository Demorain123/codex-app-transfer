#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipCargoCheck,
    [switch]$SkipLegacyStress
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
    if ($text -notmatch ("(?m)^running\s+{0}\s+tests\s*$" -f $ExpectedCount) -or
        $text -notmatch ("test result:\s+ok\.\s+{0} passed;\s+0 failed;" -f $ExpectedCount)) {
        throw "$Label does not prove $ExpectedCount passed / 0 failed"
    }
    Write-Host "${Label}: PASS ($ExpectedCount/$ExpectedCount visible)" -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r45 - Model Switch Continuity + Semantic Terminal' -ForegroundColor Green
Write-Host 'Base: r43 health/MCP rewrite. New: cross-model compaction rebind + terminal-aware lifecycle.'

# Reuse r43's already-hardened environment discovery and all legacy proof gates.
# It starts from the current clean r45 HEAD, materializes r43, and intentionally
# leaves the generated source in place for this r45 post-transform.
$r43Gate = Join-Path $PSScriptRoot 'build-r43-rewrite-local-release-stress.ps1'
Write-Host "`n[r45 0/6] Run inherited r43 verified gate" -ForegroundColor Green
if ($SkipLegacyStress) {
    & $r43Gate -SkipCargoCheck -SkipLegacyStress
} else {
    & $r43Gate -SkipCargoCheck
}
if ($LASTEXITCODE -ne 0) { throw "r43 inherited gate failed with exit code $LASTEXITCODE" }

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) { throw 'CARGO_HOME is empty after r43 gate.' }
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

Write-Host "`n[r45 1/6] Apply r45 runtime transforms over verified r43 materialization" -ForegroundColor Green
& python 'scripts/apply_r45_model_switch_continuity.py'
if ($LASTEXITCODE -ne 0) { throw 'r45 model-switch continuity transform failed' }
& python 'scripts/apply_r45_compaction_detector_safety.py'
if ($LASTEXITCODE -ne 0) { throw 'r45 compaction detector safety transform failed' }
& python 'scripts/apply_r45_compaction_metadata_truth.py'
if ($LASTEXITCODE -ne 0) { throw 'r45 compaction metadata truth transform failed' }
Set-Content -LiteralPath (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_REVISION.txt') -Value "45" -Encoding UTF8
& python 'scripts/apply_sub2api_grok_compat_revision.py'
if ($LASTEXITCODE -ne 0) { throw 'r45 version materialization failed' }

Write-Host "`n[r45 2/6] Rust format + whitespace gate" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked git 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'

Write-Host "`n[r45 3/6] Focused proxy tests" -ForegroundColor Green
$r45Log = Join-Path $env:TEMP 'r45-model-switch-continuity-proof-last.log'
Invoke-CargoProof -CargoExe $cargoExe `
    -Arguments @('test','-p','codex-app-transfer-proxy','r45_','--release','--target',$target,'--','--nocapture','--test-threads=1') `
    -Transcript $r45Log `
    -ExpectedTests @(
        'r45_compaction_helper_detection_is_structural',
        'r45_semantic_terminal_detector_handles_chunk_boundaries',
        'r45_auxiliary_requests_do_not_advance_main_model'
    ) `
    -ExpectedCount 3 -Label 'r45 model-switch/terminal proof'

Write-Host "`n[r45 4/6] Generated-source safety invariants" -ForegroundColor Green
$forward = Get-Content (Join-Path $repoRoot 'crates/proxy/src/forward.rs') -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R45-MODEL-SWITCH-CONTINUITY',
    'effective-models-r45.json',
    'action=rebind_compaction_model',
    'CAS-R45-COMPACTION-DETECTOR-SAFETY',
    'CAS-R45-COMPACTION-METADATA-TRUTH',
    'x-codex-turn-metadata',
    'request_kind',
    'normal Terra turns also advertise',
    'CAS-R45-RESPONSES-SEMANTIC-TERMINAL',
    'response_eof_without_terminal'
)) {
    if ($forward -notmatch [regex]::Escape($marker)) { throw "r45 generated-source marker missing: $marker" }
}
if ($forward -match '"remote_compaction_v2"\s*\|\s*"local_compaction_v2"\s*\|\s*"compaction"') {
    throw 'r45 detector safety failed: free-text compaction is still a helper marker'
}
if ($forward -match 'matches!\([^\r\n]*remote_compaction_v2') {
    throw 'r45 metadata truth failed: feature-name strings are still request-role classifiers'
}

if (-not $SkipCargoCheck) {
    Write-Host "`n[r45 5/6] Windows proxy + app cargo check" -ForegroundColor Green
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer-proxy' '--target' $target
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host "`n[r45 5/6] cargo check skipped by request" -ForegroundColor Yellow
}

Write-Host "`n[r45 6/6] Version + inherited invariants" -ForegroundColor Green
$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
if ($version -notmatch 'compat_revision=45' -or $version -notmatch 'app_version=2\.4\.5\+45') {
    throw 'r45 version stamp mismatch'
}
$health = Get-Content (Join-Path $repoRoot 'src-tauri/src/admin/handlers/chain_health.rs') -Raw -Encoding UTF8
if ($health -notmatch 'CAS-R43-REWRITE-HEALTH-MCP') { throw 'r43 health base marker missing after r45' }
$collision = Get-Content (Join-Path $repoRoot 'crates/adapters/src/mapper/grok_build.rs') -Raw -Encoding UTF8
if ($collision -notmatch 'CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD') { throw 'r42 Grok collision marker missing after r45' }

Write-Host "`nR45 MODEL-SWITCH CONTINUITY VALIDATION PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host "Focused proof: $r45Log"
