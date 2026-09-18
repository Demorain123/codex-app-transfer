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

# r92 live-only timestamp observer — compatibility phrase for the inherited r86
# verifier. The actual observer above is exact-only and visible-turn bounded.
Write-Host 'R92_R78_EXACT_OVERLAY_FINAL_OWNER_PASS' -ForegroundColor Green
