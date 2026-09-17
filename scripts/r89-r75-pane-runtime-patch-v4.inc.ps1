# R89_PANE_RUNTIME_GENERATION_PATCH_V4
# This code executes inside the generated r89/r86 builder after r86 has produced
# the temporary r75 source. Large JavaScript bodies live in separately syntax-
# checked r89-pane-runtime.js; this include only wires them into the real r74
# telemetry runtime owner layer through generated r75 source.

$R89R75InjectionPoint = '# r75 is deliberately a tiny local finalizer layered on r74.'
if (-not $PatchedR75.Contains($R89R75InjectionPoint)) {
    throw 'r89 could not locate r75 pane-runtime injection point'
}

$R89R75RuntimePatch = @'
# R89_PANE_RUNTIME_PATCH
$R89PaneJsPath = Join-Path $PSScriptRoot 'r89-pane-runtime.js'
if (-not (Test-Path -LiteralPath $R89PaneJsPath)) { throw "r89 pane JavaScript source missing: $R89PaneJsPath" }
$R89PaneJs = [System.IO.File]::ReadAllText($R89PaneJsPath)

function Get-R89PaneJsBlock([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r89 pane JS start marker missing: $Label" }
    $Start += $StartMarker.Length
    $End = $Text.IndexOf($EndMarker,$Start)
    if ($End -le $Start) { throw "r89 pane JS end marker missing: $Label" }
    return $Text.Substring($Start,$End-$Start).Trim([char[]]"`r`n")
}

$R89ComposerBlock = Get-R89PaneJsBlock $R89PaneJs '// R89_COMPOSER_BLOCK_START' '// R89_COMPOSER_BLOCK_END' 'composer block'
$R89RefreshBlock = Get-R89PaneJsBlock $R89PaneJs '// R89_REFRESH_BLOCK_START' '// R89_REFRESH_BLOCK_END' 'refresh block'

$R89StatusConstantOld = "  const STATUS_ID = 'cas-live-statusbar';"
$R89StatusConstantNew = $R89StatusConstantOld + "`n  const PANE_STATUS_ATTR = 'data-cas-pane-statusbar';`n  const PANE_SESSION_ATTR = 'data-cas-pane-session-id';`n  const PANE_THREAD_ATTR = 'data-cas-pane-thread-id';`n  const PANE_AGENT_ATTR = 'data-cas-pane-agent-id';"
$Original = Replace-Required $Original $R89StatusConstantOld $R89StatusConstantNew 'r89 pane status constants'

$R89InsideOwnOld = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID);"
$R89InsideOwnNew = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID + ',[' + PANE_STATUS_ATTR + '=true]');"
$Original = Replace-Required $Original $R89InsideOwnOld $R89InsideOwnNew 'r89 own-ui pane status exclusion'

$Original = Replace-BlockRequired $Original '  function findComposerRoot() {' '  function effectiveSpeed() {' $R89ComposerBlock 'r89 canonical pane status mounting'
$Original = Replace-BlockRequired $Original '  function refreshUi() {' '  function poll() {' $R89RefreshBlock 'r89 pane status refresh'

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
    'Get-R89PaneJsBlock',
    'r89 canonical pane status mounting',
    'r89 cleanup all legacy and pane status bars'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r89 pane-runtime generated r75 source missing marker: $Marker"
    }
}
Write-Host 'R89_PANE_RUNTIME_R75_SOURCE_PASS' -ForegroundColor Green
