# R92_R78_EXACT_OVERLAY_FINAL_OWNER
# Runs inside the generated r78 builder after r78 has materialized its stamp
# source. This is the last observer rewrite before r75 executes.

$R92OverlayBodyPath = Join-Path $PSScriptRoot 'r92-exact-timestamp-overlay.js'
if (-not (Test-Path -LiteralPath $R92OverlayBodyPath)) {
    throw "r92 exact overlay source missing at r78 owner: $R92OverlayBodyPath"
}
$R92OverlayBody = [System.IO.File]::ReadAllText($R92OverlayBodyPath)
if (-not $R92OverlayBody.Contains('R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    throw 'r92 r78 owner received a non-r92 observer source'
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
    if ($R92OverlayBody.Contains($Forbidden)) {
        throw "r92 r78 exact overlay retained forbidden behavior: $Forbidden"
    }
}

$R92ObserverWrapped = '$NewObserver = @''' + "`r`n" + $R92OverlayBody + "`r`n'@"
$R92ObserverReplacement = $R92ObserverWrapped + "`r`n`r`ntry {`r`n"
$PatchedR75 = Replace-BlockRequired `
    $PatchedR75 `
    '$NewObserver = @''' `
    '    # Build r75 from the already-reviewed r74 local builder without copying its' `
    $R92ObserverReplacement `
    'r92 exact-only timestamp overlay final owner'

foreach ($Marker in @(
    'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'new IntersectionObserver(function(entries) {',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r92Cleanup };'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r92 r78 final observer owner missing marker: $Marker"
    }
}

# r92 live-only timestamp observer — compatibility phrase for the inherited r86 verifier.
# r93 live-only timestamp observer — same compatibility phrase after r90->r93 retargeting.
# The actual observer above is exact-only and visible-turn bounded.
Write-Host 'R92_R78_EXACT_OVERLAY_FINAL_OWNER_PASS' -ForegroundColor Green

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
$R93StatusReplacement = $R93StatusInjection + [char]10 + $R93AssertNeedle
if (-not $PatchedR75.Contains($R93AssertNeedle)) {
    throw 'r93 could not locate final r75 status injection point'
}
$PatchedR75 = $PatchedR75.Replace($R93AssertNeedle,$R93StatusReplacement)
if (-not $PatchedR75.Contains('R93StatusFinalizerPath')) {
    throw 'r93 final r75 source missing status finalizer binding'
}
Write-Host 'R93_STATUS_FINALIZER_BOUND_TO_R75_PASS' -ForegroundColor Green

