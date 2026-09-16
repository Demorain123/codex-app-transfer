# R88_PANE_RUNTIME_GENERATION_PATCH_V4
# This code executes inside the generated r88/r86 builder after r86 has produced
# the temporary r75 source. The large JavaScript body lives in the separately
# syntax-checked r88-pane-runtime.js file; this include only wires it into the
# real r74 telemetry-runtime owner layer through generated r75 source.

$R88R75InjectionPoint = '# r75 is deliberately a tiny local finalizer layered on r74.'
if (-not $PatchedR75.Contains($R88R75InjectionPoint)) {
    throw 'r88 could not locate r75 pane-runtime injection point'
}

$R88R75RuntimePatch = @'
# R88_PANE_RUNTIME_PATCH
$R88PaneJsPath = Join-Path $PSScriptRoot 'r88-pane-runtime.js'
if (-not (Test-Path -LiteralPath $R88PaneJsPath)) { throw "r88 pane JavaScript source missing: $R88PaneJsPath" }
$R88PaneJs = [System.IO.File]::ReadAllText($R88PaneJsPath)

function Get-R88PaneJsBlock([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r88 pane JS start marker missing: $Label" }
    $Start += $StartMarker.Length
    $End = $Text.IndexOf($EndMarker,$Start)
    if ($End -le $Start) { throw "r88 pane JS end marker missing: $Label" }
    return $Text.Substring($Start,$End-$Start).Trim([char[]]"`r`n")
}

$R88ComposerBlock = Get-R88PaneJsBlock $R88PaneJs '// R88_COMPOSER_BLOCK_START' '// R88_COMPOSER_BLOCK_END' 'composer block'
$R88RefreshBlock = Get-R88PaneJsBlock $R88PaneJs '// R88_REFRESH_BLOCK_START' '// R88_REFRESH_BLOCK_END' 'refresh block'

$R88StatusConstantOld = "  const STATUS_ID = 'cas-live-statusbar';"
$R88StatusConstantNew = $R88StatusConstantOld + "`n  const PANE_STATUS_ATTR = 'data-cas-pane-statusbar';`n  const PANE_SESSION_ATTR = 'data-cas-pane-session-id';`n  const PANE_THREAD_ATTR = 'data-cas-pane-thread-id';`n  const PANE_AGENT_ATTR = 'data-cas-pane-agent-id';"
$Original = Replace-Required $Original $R88StatusConstantOld $R88StatusConstantNew 'r88 pane status constants'

$R88InsideOwnOld = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID);"
$R88InsideOwnNew = "    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID + ',[' + PANE_STATUS_ATTR + '=true]');"
$Original = Replace-Required $Original $R88InsideOwnOld $R88InsideOwnNew 'r88 own-ui pane status exclusion'

$Original = Replace-BlockRequired $Original '  function findComposerRoot() {' '  function effectiveSpeed() {' $R88ComposerBlock 'r88 pane-scoped composer/status mounting'
$Original = Replace-BlockRequired $Original '  function refreshUi() {' '  function poll() {' $R88RefreshBlock 'r88 pane status refresh'

$R88CleanupOld = '    for (const id of [STATUS_ID, MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {'
$R88CleanupNew = "    document.querySelectorAll('[' + PANE_STATUS_ATTR + '=true]').forEach(function(node) { node.remove(); });`n    for (const id of [MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {"
$Original = Replace-Required $Original $R88CleanupOld $R88CleanupNew 'r88 cleanup all pane status bars'
'@

$PatchedR75 = $PatchedR75.Replace(
    $R88R75InjectionPoint,
    $R88R75RuntimePatch + "`r`n`r`n" + $R88R75InjectionPoint
)

foreach ($Marker in @(
    'R88_PANE_RUNTIME_PATCH',
    "const PANE_STATUS_ATTR = 'data-cas-pane-statusbar';",
    "const PANE_SESSION_ATTR = 'data-cas-pane-session-id';",
    'r88-pane-runtime.js',
    'Get-R88PaneJsBlock',
    'r88 pane-scoped composer/status mounting',
    'r88 pane status refresh'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r88 pane-runtime generated r75 source missing marker: $Marker"
    }
}
Write-Host 'R88_PANE_RUNTIME_R75_SOURCE_PASS' -ForegroundColor Green
