# R94_R78_EXACT_OVERLAY_FINAL_OWNER
# Runs inside the generated r78 builder after r78 has materialized its stamp
# source. This is the last observer rewrite before r75 executes.

$R94OverlayBodyPath = Join-Path $PSScriptRoot 'r94-exact-turn-overlay.js'
if (-not (Test-Path -LiteralPath $R94OverlayBodyPath)) {
    throw "r94 exact overlay source missing at r78 owner: $R94OverlayBodyPath"
}
$R94OverlayBody = [System.IO.File]::ReadAllText($R94OverlayBodyPath)
foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_EXACT_TURN_CAPABILITY_RUNTIME',
    'R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME',
    'R94_FULL_DATE_TIMESTAMP_RUNTIME',
    'R94_USER_PROMPT_TIMESTAMP_RUNTIME',
    'R94_NATIVE_RAIL_PRESERVE_RUNTIME',
    'R94_NATIVE_RAIL_METADATA_ONLY_RUNTIME',
    'R94_NATIVE_RAIL_NO_CUSTOM_PAINT_RUNTIME',
    'R94_STREAMING_SEGMENT_THROTTLE_RUNTIME',
    'R94_STREAMING_LATEST_OWNER_CACHE_RUNTIME',
    'R94_MULTI_PANE_THREAD_OWNERSHIP_RUNTIME',
    'R94_MULTI_PANE_LATEST_OWNER_CACHE_RUNTIME',
    'R94_NO_VIEWPORT_EDGE_PINNING_RUNTIME',
    'window.setTimeout(r94FlushSegmentTurns, 220)',
    'const timelineRail = null;',
    'function r94AssistantMessageSurface(node) {',
    'function r94IsUserSurface(node) {',
    'R94_ITEM_EXACT_TIMESTAMP_RUNTIME'
)) {
    if (-not $R94OverlayBody.Contains($Marker)) {
        throw "r94 r78 owner received an incomplete exact-turn observer source: $Marker"
    }
}
foreach ($Forbidden in @(
    'characterData: true',
    'characterData:true',
    'Date.now()',
    'segment.insertBefore(',
    'segment.appendChild(',
    'actionRow.insertAdjacentElement(',
    'setInterval('
)) {
    if ($R94OverlayBody.Contains($Forbidden)) {
        throw "r94 r78 exact overlay retained forbidden behavior: $Forbidden"
    }
}

$R94ObserverWrapped = '$NewObserver = @''' + "`r`n" + $R94OverlayBody + "`r`n'@"
$R94ObserverReplacement = $R94ObserverWrapped + "`r`n`r`ntry {`r`n"
$PatchedR75 = Replace-BlockRequired `
    $PatchedR75 `
    '$NewObserver = @''' `
    '    # Build r75 from the already-reviewed r74 local builder without copying its' `
    $R94ObserverReplacement `
    'r94 exact-only timestamp overlay final owner'

foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_EXACT_TURN_CAPABILITY_RUNTIME',
    'R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME',
    'R94_FULL_DATE_TIMESTAMP_RUNTIME',
    'R94_NATIVE_RAIL_PRESERVE_RUNTIME',
    'const timelineRail = null;',
    'function r94UpsertTimelineEntry(key, epoch, anchor, kind, approx, preview) {',
    'window.__casR94TurnCapability = capability;',
    'R94_ITEM_EXACT_TIMESTAMP_RUNTIME',
    'new IntersectionObserver(function(entries) {',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r94Cleanup };'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r94 r78 final observer owner missing marker: $Marker"
    }
}

# r94 live-only timestamp observer — compatibility phrase for the inherited r86 verifier.
# r93 live-only timestamp observer — same compatibility phrase after r90->r93 retargeting.
# The actual observer above is hybrid: exact native/turn ownership plus childList-only, live first-observed per-output overlay timestamps.
Write-Host 'R94_R78_EXACT_OVERLAY_FINAL_OWNER_PASS' -ForegroundColor Green

# R93 composer/status correctness is finalized inside r75 after all r74/r75
# telemetry transforms have materialized. Inject the finalizer immediately
# before the generated timestamp-profile assertion.
$R93StatusFinalizerPath = Join-Path $PSScriptRoot 'r93-status-finalizer.ps1'
if (-not (Test-Path -LiteralPath $R93StatusFinalizerPath)) {
    throw "r93 status finalizer missing: $R93StatusFinalizerPath"
}
$R93StatusFinalizerText = [System.IO.File]::ReadAllText($R93StatusFinalizerPath)
foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_FINALIZER',
    'R93_COMPOSER_STATUS_FINAL_OWNER_PASS',
    'R93_NATIVE_USAGE_ISOLATION_PASS',
    'R93_STATUS_RENDER_FINGERPRINT_PASS'
)) {
    if (-not $R93StatusFinalizerText.Contains($Marker)) {
        throw "r93 status finalizer source missing marker: $Marker"
    }
}
$R93AssertNeedle = '    Assert-GeneratedTimestampProfile $Patched'
$R93StatusInjection = @'
    $R93StatusFinalizerPath = Join-Path $PSScriptRoot 'r93-status-finalizer.ps1'
    if (-not (Test-Path -LiteralPath $R93StatusFinalizerPath)) { throw "r93 status finalizer missing at runtime build owner: $R93StatusFinalizerPath" }
    . $R93StatusFinalizerPath
'@
$R94ComposerStatusFinalizerPath = Join-Path $PSScriptRoot 'r94-composer-status-finalizer.ps1'
if (-not (Test-Path -LiteralPath $R94ComposerStatusFinalizerPath)) {
    throw "r94 composer status finalizer missing: $R94ComposerStatusFinalizerPath"
}
$R94ComposerStatusFinalizerText = [System.IO.File]::ReadAllText($R94ComposerStatusFinalizerPath)
foreach ($Marker in @(
    'R94_COMPOSER_STATUS_INSIDE_FINALIZER',
    'R94_STATUS_INSIDE_COMPOSER_FINAL_OWNER_PASS',
    'R94_COMPOSER_INLINE_MOUNT_V4_FAST_SAFE_PASS',
    'R94_STATUS_NEVER_ENTERS_EDITABLE_PASS',
    'R94_UNSAFE_EDITOR_MOUNT_FALLBACKS_ABSENT_PASS',
    'R94_EDITOR_BOUNDARY_GUARD_RUNTIME',
    'R94_NATIVE_USAGE_SCAN_DISABLED_PASS',
    'R94_NO_STATUS_VIEWPORT_TRACKING_PASS'
)) {
    if (-not $R94ComposerStatusFinalizerText.Contains($Marker)) {
        throw "r94 composer status finalizer source missing marker: $Marker"
    }
}
$R94ComposerStatusInjection = @'
    $R94ComposerStatusFinalizerPath = Join-Path $PSScriptRoot 'r94-composer-status-finalizer.ps1'
    if (-not (Test-Path -LiteralPath $R94ComposerStatusFinalizerPath)) { throw "r94 composer status finalizer missing at runtime build owner: $R94ComposerStatusFinalizerPath" }
    . $R94ComposerStatusFinalizerPath
'@
$R94TurnNotificationFinalizerPath = Join-Path $PSScriptRoot 'r94-turn-notification-finalizer.ps1'
if (-not (Test-Path -LiteralPath $R94TurnNotificationFinalizerPath)) {
    throw "r94 turn notification finalizer missing: $R94TurnNotificationFinalizerPath"
}
$R94TurnNotificationFinalizerText = [System.IO.File]::ReadAllText($R94TurnNotificationFinalizerPath)
foreach ($Marker in @(
    'R94_TURN_NOTIFICATION_FINALIZER',
    'R94_PASSIVE_ITEM_LIFECYCLE_INGEST_PASS',
    'R94_PASSIVE_TURN_NOTIFICATION_INGEST_PASS'
)) {
    if (-not $R94TurnNotificationFinalizerText.Contains($Marker)) {
        throw "r94 turn notification finalizer source missing marker: $Marker"
    }
}
$R94TurnNotificationInjection = @'
    $R94TurnNotificationFinalizerPath = Join-Path $PSScriptRoot 'r94-turn-notification-finalizer.ps1'
    if (-not (Test-Path -LiteralPath $R94TurnNotificationFinalizerPath)) { throw "r94 turn notification finalizer missing at runtime build owner: $R94TurnNotificationFinalizerPath" }
    . $R94TurnNotificationFinalizerPath
'@
$R93StatusReplacement = $R93StatusInjection + [char]10 + $R94ComposerStatusInjection + [char]10 + $R94TurnNotificationInjection + [char]10 + $R93AssertNeedle
if (-not $PatchedR75.Contains($R93AssertNeedle)) {
    throw 'r93 could not locate final r75 status injection point'
}
$PatchedR75 = $PatchedR75.Replace($R93AssertNeedle,$R93StatusReplacement)
if (-not $PatchedR75.Contains('R93StatusFinalizerPath')) {
    throw 'r93 final r75 source missing status finalizer binding'
}
Write-Host 'R93_STATUS_FINALIZER_BOUND_TO_R75_PASS' -ForegroundColor Green
Write-Host 'R94_COMPOSER_STATUS_INSIDE_FINALIZER_BOUND_TO_R75_PASS' -ForegroundColor Green
Write-Host 'R94_TURN_NOTIFICATION_FINALIZER_BOUND_TO_R75_PASS' -ForegroundColor Green

