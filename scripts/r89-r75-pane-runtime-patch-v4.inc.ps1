# R89_PANE_RUNTIME_GENERATION_PATCH_V4
# This code executes inside the generated r89/r86 builder after r86 has produced
# the temporary r75 source. Large JavaScript bodies live in separately syntax-
# checked sources; this include wires them into the real r74/r76 telemetry owner
# layer through generated r75 source.

$R89R75InjectionPoint = '# r75 is deliberately a tiny local finalizer layered on r74.'
if (-not $PatchedR75.Contains($R89R75InjectionPoint)) {
    throw 'r89 could not locate r75 pane-runtime injection point'
}

$R89R75RuntimePatch = @'
# R89_PANE_RUNTIME_PATCH
$R89PaneJsPath = Join-Path $PSScriptRoot 'r89-pane-runtime.js'
$R89TelemetryTruthJsPath = Join-Path $PSScriptRoot 'r89-telemetry-truth.js'
foreach ($Path in @($R89PaneJsPath,$R89TelemetryTruthJsPath)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r89 runtime JavaScript source missing: $Path" }
}
$R89PaneJs = [System.IO.File]::ReadAllText($R89PaneJsPath)
$R89TelemetryTruthJs = [System.IO.File]::ReadAllText($R89TelemetryTruthJsPath)

function Get-R89PaneJsBlock([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r89 JS start marker missing: $Label" }
    $Start += $StartMarker.Length
    $End = $Text.IndexOf($EndMarker,$Start)
    if ($End -le $Start) { throw "r89 JS end marker missing: $Label" }
    return $Text.Substring($Start,$End-$Start).Trim([char[]]"`r`n")
}

$R89ComposerBlock = Get-R89PaneJsBlock $R89PaneJs '// R89_COMPOSER_BLOCK_START' '// R89_COMPOSER_BLOCK_END' 'composer block'
$R89RefreshBlock = Get-R89PaneJsBlock $R89PaneJs '// R89_REFRESH_BLOCK_START' '// R89_REFRESH_BLOCK_END' 'refresh block'
$R89ExternalIngestBlock = Get-R89PaneJsBlock $R89TelemetryTruthJs '// R89_EXTERNAL_INGEST_BLOCK_START' '// R89_EXTERNAL_INGEST_BLOCK_END' 'external exact ingest block'
$R89GlobalSpeedBlock = Get-R89PaneJsBlock $R89TelemetryTruthJs '// R89_GLOBAL_SPEED_BLOCK_START' '// R89_GLOBAL_SPEED_BLOCK_END' 'global speed isolation block'
$R89PaneTruthBlock = Get-R89PaneJsBlock $R89TelemetryTruthJs '// R89_PANE_TRUTH_BLOCK_START' '// R89_PANE_TRUTH_BLOCK_END' 'pane telemetry truth block'

$R89StatusConstantOld = "  const STATUS_ID = 'cas-live-statusbar';"
$R89StatusConstantNew = $R89StatusConstantOld + "`n  const PANE_STATUS_ATTR = 'data-cas-pane-statusbar';`n  const PANE_SESSION_ATTR = 'data-cas-pane-session-id';`n  const PANE_THREAD_ATTR = 'data-cas-pane-thread-id';`n  const PANE_AGENT_ATTR = 'data-cas-pane-agent-id';"
$Original = Replace-Required $Original $R89StatusConstantOld $R89StatusConstantNew 'r89 pane status constants'

$R89InsideOwnOld = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID);"
$R89InsideOwnNew = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID + ',[' + PANE_STATUS_ATTR + '=true]');"
$Original = Replace-Required $Original $R89InsideOwnOld $R89InsideOwnNew 'r89 own-ui pane status exclusion'

$Original = Replace-BlockRequired $Original '  function findComposerRoot() {' '  function effectiveSpeed() {' $R89ComposerBlock 'r89 canonical pane status mounting'
$Original = Replace-BlockRequired $Original '  function effectiveSpeed() {' '  function effectiveCacheHit() {' $R89GlobalSpeedBlock 'r89 isolate global/native speed from custom pane telemetry'
$Original = Replace-BlockRequired $Original '  function statusHtmlForPane(sessionId, threadId, agentId) {' '  function bindIdentityCopy(bar) {' $R89PaneTruthBlock 'r89 pane-owned exact telemetry presentation'
$Original = Replace-BlockRequired $Original '  function refreshUi() {' '  function poll() {' $R89RefreshBlock 'r89 pane status refresh'
$Original = Replace-Required $Original 'bar.innerHTML = statusHtmlForPane(sessionId, threadId, agentId);' 'bar.innerHTML = statusHtmlForPane(sessionId, threadId, agentId, bar);' 'r89 pass bar to pane-live truth renderer'

# r76 owns authoritative local-session JSONL ingestion. Replace that function at
# its owner layer so exact fields are copied to a dedicated snapshot before the
# legacy/native Usage poll can overwrite generic display fields.
$Original = Replace-BlockRequired $Original '  function ingestExternalUsage(envelope) {' '  state.refresh = refreshUi;' $R89ExternalIngestBlock 'r89 exact external JSONL snapshot ingest'

# The legacy analytics widget is global, not pane-scoped. Label that explicitly
# instead of implying that its samples belong to the pane whose bar was clicked.
$Original = Replace-Required $Original 'Live telemetry · recent samples' 'Global/native telemetry · not pane-scoped' 'r89 legacy analytics ownership label'

$R89CleanupOld = '    for (const id of [STATUS_ID, MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {'
$R89CleanupNew = "    document.querySelectorAll('#' + STATUS_ID + ',[' + PANE_STATUS_ATTR + '=true]').forEach(function(node) { node.remove(); });`n    for (const id of [MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {"
$Original = Replace-Required $Original $R89CleanupOld $R89CleanupNew 'r89 cleanup all legacy and pane status bars'
'@

$PatchedR75 = $PatchedR75.Replace(
    $R89R75InjectionPoint,
    $R89R75RuntimePatch + "`r`n`r`n" + $R89R75InjectionPoint
)

foreach ($Marker in @(
    'R89_PANE_RUNTIME_PATCH',
    "const PANE_STATUS_ATTR = 'data-cas-pane-statusbar';",
    "const PANE_SESSION_ATTR = 'data-cas-pane-session-id';",
    'r89-pane-runtime.js',
    'r89-telemetry-truth.js',
    'Get-R89PaneJsBlock',
    'r89 canonical pane status mounting',
    'r89 isolate global/native speed from custom pane telemetry',
    'r89 pane-owned exact telemetry presentation',
    'r89 exact external JSONL snapshot ingest',
    'r89 cleanup all legacy and pane status bars'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r89 pane-runtime generated r75 source missing marker: $Marker"
    }
}
Write-Host 'R89_PANE_RUNTIME_R75_SOURCE_PASS' -ForegroundColor Green
