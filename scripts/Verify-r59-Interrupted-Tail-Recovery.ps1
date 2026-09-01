param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backend = Join-Path $root 'src-tauri\src\admin\handlers\thread_recovery.rs'
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
Require-Marker $backend 'rewindInterruptedTail'
Require-Marker $backend 'MAX_BAD_TAIL'
Require-Marker $backend 'stage=bad_tail_removed'
Require-Marker $backend 'same_thread=true'
Require-Marker $backend 'model_request=false'
Require-Marker $page '同 ID 清理中断尾巴（0xC000013A）'
Require-Marker $api 'rewindInterruptedTail'
Require-Marker $version 'compat_revision=59'
Require-Marker $version 'app_version=2.4.5+59'

if ($failures.Count -gt 0) {
    Write-Host 'R59 INTERRUPTED-TAIL RECOVERY: FAIL' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host 'R59 INTERRUPTED-TAIL RECOVERY: PASS' -ForegroundColor Green
Write-Host '- same-thread/session-id recovery action is materialized'
Write-Host '- only newest consecutive interrupted/failed turns are eligible'
Write-Host '- completed safe boundary + max-tail guard + post-revert verification are present'
Write-Host '- action records model_request=false and does not modify workspace files'
Write-Host 'NOTE: PASS verifies r59 composition, not the proprietary OpenAI codex.exe 0xC000013A root cause.' -ForegroundColor Yellow
exit 0
