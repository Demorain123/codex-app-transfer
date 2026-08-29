#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipCargoCheck,
    [switch]$SkipFrontendBuild,
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

function Invoke-TestProof {
    param(
        [Parameter(Mandatory)][string]$CargoExe,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Transcript,
        [Parameter(Mandatory)][string[]]$ExpectedTests,
        [Parameter(Mandatory)][string]$Label
    )
    Remove-Item -LiteralPath $Transcript -Force -ErrorAction SilentlyContinue
    Write-Host "`n> $CargoExe $($Arguments -join ' ')" -ForegroundColor Cyan
    & $CargoExe @Arguments 2>&1 | Tee-Object -FilePath $Transcript
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "$Label failed ($exitCode). Transcript: $Transcript" }
    $text = Get-Content -LiteralPath $Transcript -Raw -Encoding UTF8
    foreach ($expected in $ExpectedTests) {
        if ($text -notmatch [regex]::Escape($expected)) {
            throw "$Label did not execute expected test: $expected"
        }
        if ($text -notmatch ("test .*{0}.* \.\.\. ok" -f [regex]::Escape($expected))) {
            throw "$Label did not prove PASS for: $expected"
        }
    }
    if ($text -match 'test result:\s+FAILED' -or $text -match '(?m)^failures:') {
        throw "$Label contains a failed Rust test"
    }
    Write-Host "${Label}: PASS ($($ExpectedTests.Count) named tests visible)" -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r46 - Old Thread Recovery + Model Switch Forensics' -ForegroundColor Green
Write-Host 'Base: r45 continuity/metadata-truth/semantic-terminal. New: recovery center + structural diagnostics.'

Write-Host "`n[r46 0/8] Inherited r45 gate" -ForegroundColor Green
$r45Gate = Join-Path $PSScriptRoot 'build-r45-model-switch-local-release-stress.ps1'
if ($SkipLegacyStress) {
    & $r45Gate -SkipCargoCheck -SkipLegacyStress
} else {
    & $r45Gate -SkipCargoCheck
}
if ($LASTEXITCODE -ne 0) { throw "r45 inherited gate failed with exit code $LASTEXITCODE" }

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) { throw 'CARGO_HOME is empty after r45 gate.' }
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

Write-Host "`n[r46 1/8] Apply r46 overlays" -ForegroundColor Green
Invoke-Checked 'python' 'scripts/apply_r46_thread_recovery_backend_fixes.py'
Invoke-Checked 'python' 'scripts/apply_r46_model_switch_forensics_v2.py'
Invoke-Checked 'python' 'scripts/apply_r46_thread_recovery_ui.py'
Set-Content -LiteralPath (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_REVISION.txt') -Value '46' -Encoding UTF8
Invoke-Checked 'python' 'scripts/apply_sub2api_grok_compat_revision.py'

Write-Host "`n[r46 2/8] Format + whitespace" -ForegroundColor Green
Invoke-Checked $cargoExe 'fmt' '--all'
Invoke-Checked 'git' 'diff' '--check'
Invoke-Checked $cargoExe 'fmt' '--all' '--' '--check'

Write-Host "`n[r46 3/8] Proxy structural-forensics tests" -ForegroundColor Green
$proxyLog = Join-Path $env:TEMP 'r46-model-switch-forensics-proof-last.log'
Invoke-TestProof -CargoExe $cargoExe `
    -Arguments @('test','-p','codex-app-transfer-proxy','r46_','--release','--target',$target,'--','--nocapture','--test-threads=1') `
    -Transcript $proxyLog `
    -ExpectedTests @(
        'r46_metadata_truth_keeps_feature_flag_out_of_request_role',
        'r46_shape_counts_never_copy_message_content',
        'r46_body_fingerprint_is_stable_without_echoing_body'
    ) `
    -Label 'r46 proxy forensics proof'

Write-Host "`n[r46 4/8] Recovery backend tests" -ForegroundColor Green
$recoveryLog = Join-Path $env:TEMP 'r46-thread-recovery-proof-last.log'
Invoke-TestProof -CargoExe $cargoExe `
    -Arguments @('test','-p','codex-app-transfer','r46_','--release','--target',$target,'--','--nocapture','--test-threads=1') `
    -Transcript $recoveryLog `
    -ExpectedTests @(
        'r46_failure_parser_extracts_only_structural_metadata',
        'r46_thread_id_guard_rejects_paths',
        'r46_fingerprint_does_not_echo_thread_id'
    ) `
    -Label 'r46 recovery backend proof'

Write-Host "`n[r46 5/8] Generated-source invariants" -ForegroundColor Green
$forward = Get-Content (Join-Path $repoRoot 'crates/proxy/src/forward.rs') -Raw -Encoding UTF8
foreach ($marker in @(
    'CAS-R45-COMPACTION-METADATA-TRUTH',
    'CAS-R46-MODEL-SWITCH-FORENSICS-V2',
    'event=raw_client_status_mismatch',
    'failed_compaction_preserves_history',
    'cross_model_compaction_mismatch',
    'input_types=[{}]'
)) {
    if ($forward -notmatch [regex]::Escape($marker)) { throw "r46 forward marker missing: $marker" }
}
$backend = Get-Content (Join-Path $repoRoot 'src-tauri/src/admin/handlers/thread_recovery.rs') -Raw -Encoding UTF8
foreach ($marker in @('thread/revert','thread/rollback','thread/fork','RECOVERY-BACKUP.json','workspace_files_changed: false')) {
    if ($backend -notmatch [regex]::Escape($marker)) { throw "r46 recovery marker missing: $marker" }
}
$admin = Get-Content (Join-Path $repoRoot 'src-tauri/src/admin/mod.rs') -Raw -Encoding UTF8
if ($admin -notmatch '/api/thread-recovery/preview' -or $admin -notmatch '/api/thread-recovery/action') {
    throw 'r46 recovery routes missing'
}
$page = Get-Content (Join-Path $repoRoot 'frontend/src/pages/ProxyPage.vue') -Raw -Encoding UTF8
if ($page -notmatch '同 ID 回退 1 轮（推荐）' -or $page -notmatch '创建恢复副本（原会话不动）') {
    throw 'r46 recovery UI missing'
}

Write-Host "`n[r46 6/8] Frontend production build" -ForegroundColor Green
if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $repoRoot 'frontend')
    try { Invoke-Checked 'npm.cmd' 'run' 'build' } finally { Pop-Location }
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'frontend\dist\index.html') -PathType Leaf)) {
        throw 'r46 frontend dist/index.html missing after production build'
    }
} else {
    Write-Host 'Frontend build skipped by request' -ForegroundColor Yellow
}

Write-Host "`n[r46 7/8] Windows cargo checks" -ForegroundColor Green
if (-not $SkipCargoCheck) {
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer-proxy' '--target' $target
    Invoke-Checked $cargoExe 'check' '-p' 'codex-app-transfer' '--target' $target
} else {
    Write-Host 'cargo check skipped by request' -ForegroundColor Yellow
}

Write-Host "`n[r46 8/8] Version gate" -ForegroundColor Green
$version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
if ($version -notmatch 'compat_revision=46' -or $version -notmatch 'app_version=2\.4\.5\+46') {
    throw 'r46 version stamp mismatch'
}

Write-Host "`nR46 RECOVERY + FORENSICS VALIDATION PASS" -ForegroundColor Green
Write-Host $version.Trim()
Write-Host "Proxy proof   : $proxyLog"
Write-Host "Recovery proof: $recoveryLog"
Write-Host 'Real-environment recovery is intentionally NOT executed by this build gate.' -ForegroundColor Yellow
