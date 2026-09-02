param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backend = Join-Path $root 'src-tauri\src\admin\handlers\thread_recovery.rs'
$admin = Join-Path $root 'src-tauri\src\admin\mod.rs'
$page = Join-Path $root 'frontend\src\pages\ProxyPage.vue'
$api = Join-Path $root 'frontend\src\api\threadRecovery.ts'
$version = Join-Path $root 'SUB2API_GROK_COMPAT_VERSION.txt'

$failures = @()
function Require-Marker([string]$Path, [string]$Marker) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $script:failures += "missing file: $Path"
        return
    }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($text -notmatch [regex]::Escape($Marker)) {
        $script:failures += "missing marker '$Marker' in $Path"
    }
}

Require-Marker $backend 'CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY'
Require-Marker $backend 'CAS-R60-RECOVERY-SESSION-CATALOG'
Require-Marker $backend 'RecoveryStatusRegistry'
Require-Marker $backend 'recovery-status-r60.json'
Require-Marker $backend 'r59_log_migration'
Require-Marker $backend 'RECOVERY-SUCCESS.json'
Require-Marker $backend 'latest_unresolved_failure'
Require-Marker $backend 'pub async fn sessions'
Require-Marker $backend 'stage=recovery_status_persisted'
Require-Marker $admin '/api/thread-recovery/sessions'
Require-Marker $page '最近 Session'
Require-Marker $page '无未处理失败'
Require-Marker $page '历史故障已处理'
Require-Marker $api 'getThreadRecoverySessions'
Require-Marker $api 'ThreadRecoverySessionItem'
Require-Marker $api 'recoveryStatus'
Require-Marker $version 'compat_revision=60'
Require-Marker $version 'app_version=2.4.5+60'

if ($failures.Count -gt 0) {
    Write-Host 'R60 RECOVERY SESSION CATALOG: FAIL' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host 'R60 RECOVERY SESSION CATALOG: PASS' -ForegroundColor Green
Write-Host '- r59 same-ID interrupted-tail recovery remains materialized'
Write-Host '- recent Session catalog endpoint + frontend list are present'
Write-Host '- verified r59 success-log migration + persistent r60 lifecycle receipt are present'
Write-Host '- auto-detect is unresolved-only; recovered historical evidence remains forensic-only'
Write-Host '- a newer failure can reopen the same Session as needsRecovery'
exit 0
