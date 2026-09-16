# R87_MULTI_PANE_STATUS_OVERLAY
# This include executes inside the generated r87 wrapper after $PatchedR75 and
# $R87Core exist. It patches the semantic owner layers in memory only; tracked
# historical builders stay untouched until their existing post-clean gates.

$R87PaneRuntimePath = Join-Path $PSScriptRoot 'r87-pane-status-runtime.js'
$R87ExternalIngestPath = Join-Path $PSScriptRoot 'r87-external-usage-ingest.js'
$R87MainCollectorPath = Join-Path $PSScriptRoot 'r87-main-usage-collector.js'
foreach ($R87PanePath in @($R87PaneRuntimePath,$R87ExternalIngestPath,$R87MainCollectorPath)) {
    if (-not (Test-Path -LiteralPath $R87PanePath)) { throw "r87 pane-status helper missing: $R87PanePath" }
}

$R87PaneRuntimeBody = [System.IO.File]::ReadAllText($R87PaneRuntimePath)

# ---------------------------------------------------------------------------
# Renderer/status runtime: make r75 patch the r74 telemetry runtime when the
# r75 generated builder actually executes. This avoids editing r74/r76 tracked
# sources before nested clean-worktree gates.
# ---------------------------------------------------------------------------
$R87R75PatchNeedle = "$Patched = $Original.Replace('r74', 'r75').Replace('R74', 'R75').Replace('+74', '+75')"
$R87R75PatchCode = @'

    # R87_MULTI_PANE_STATUS_RUNTIME_PATCH
    $R87PaneRuntimePath = Join-Path $PSScriptRoot 'r87-pane-status-runtime.js'
    if (-not (Test-Path -LiteralPath $R87PaneRuntimePath)) { throw "r87 pane runtime missing: $R87PaneRuntimePath" }
    $R87PaneRuntimeBody = [System.IO.File]::ReadAllText($R87PaneRuntimePath)

    $R87OldStatusConst = "  const STATUS_ID = 'cas-live-statusbar';"
    $R87NewStatusConst = @'
  const STATUS_ID = 'cas-live-statusbar';
  const STATUS_ATTR = 'data-cas-live-statusbar';
  const STATUS_HOST_ATTR = 'data-cas-statusbar-host';
'@
    $Patched = Replace-Required $Patched $R87OldStatusConst $R87NewStatusConst 'r87 multi-pane status constants'

    $R87OldInsideOwnUi = @'
  function insideOwnUi(node) {
    if (!(node instanceof Element)) return false;
    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID);
  }
'@
    $R87NewInsideOwnUi = @'
  function insideOwnUi(node) {
    if (!(node instanceof Element)) return false;
    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID + ',[' + STATUS_ATTR + '=\"true\"],[' + STATUS_HOST_ATTR + '=\"true\"]');
  }
'@
    $Patched = Replace-Required $Patched $R87OldInsideOwnUi $R87NewInsideOwnUi 'r87 own-ui multi-pane guard'

    $Patched = Replace-BlockRequired `
        $Patched `
        '  function findComposerRoot() {' `
        '  function ensureMirror() {' `
        $R87PaneRuntimeBody `
        'r87 multi-pane composer/status runtime'

    $R87OldRefreshUi = @'
  function refreshUi() {
    ensureStyle();
    readModelLabel();
    const bar = ensureStatusBar();
    if (bar) bar.innerHTML = statusHtml();
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }
'@
    $R87NewRefreshUi = @'
  function refreshUi() {
    ensureStyle();
    readModelLabel();
    ensureStatusBars();
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }
'@
    $Patched = Replace-Required $Patched $R87OldRefreshUi $R87NewRefreshUi 'r87 render every visible pane statusbar'

    $R87OldCleanupIds = @'
    for (const id of [STATUS_ID, MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {
      const node = document.getElementById(id);
      if (node) node.remove();
    }
'@
    $R87NewCleanupIds = @'
    document.querySelectorAll('[' + STATUS_HOST_ATTR + '=\"true\"]').forEach(function(node) { node.remove(); });
    const paneStyle = document.getElementById('cas-r87-pane-status-style');
    if (paneStyle) paneStyle.remove();
    for (const id of [MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {
      const node = document.getElementById(id);
      if (node) node.remove();
    }
'@
    $Patched = Replace-Required $Patched $R87OldCleanupIds $R87NewCleanupIds 'r87 multi-pane cleanup'

    $R87OldOutsideClick = @'
    const bar = document.getElementById(STATUS_ID);
    const mirror = document.getElementById(MIRROR_ID);
    if ((bar && bar.contains(event.target)) || (mirror && mirror.contains(event.target))) return;
'@
    $R87NewOutsideClick = @'
    const bar = event.target instanceof Element ? event.target.closest('[' + STATUS_ATTR + '=\"true\"]') : null;
    const mirror = document.getElementById(MIRROR_ID);
    if (bar || (mirror && mirror.contains(event.target))) return;
'@
    $Patched = Replace-Required $Patched $R87OldOutsideClick $R87NewOutsideClick 'r87 multi-pane analytics outside-click guard'

    foreach ($R87PaneMarker in @(
        'function findComposerRoots() {',
        'function threadIdForComposer(composer) {',
        'function ensureStatusBars() {',
        'data-cas-statusbar-host',
        'data-cas-session-id',
        'sid ',
        'tid ',
        'data-cas-status-placement-depth'
    )) {
        if (-not $Patched.Contains($R87PaneMarker)) { throw "r87 generated renderer pane invariant missing: $R87PaneMarker" }
    }
'@
if (-not $PatchedR75.Contains($R87R75PatchNeedle)) {
    throw 'r87 could not locate r75 runtime materialization point for multi-pane status overlay'
}
$PatchedR75 = $PatchedR75.Replace($R87R75PatchNeedle,$R87R75PatchNeedle + $R87R75PatchCode)

# ---------------------------------------------------------------------------
# Exact local collector: replace the r76 JS here-strings from inside the r83
# generated source. The collector now resolves all visible pane thread ids and
# forwards persisted session_id/parent_thread_id from session_meta.
# ---------------------------------------------------------------------------
$R87R83PatchNeedle = @'
$PatchedR76Output = Replace-Required $PatchedR76Output $OldSafeEnvelope $NewSafeEnvelope 'r76 collector safe model envelope'
'@
$R87R83PatchCode = @'

# R87_MULTI_PANE_COLLECTOR_PATCH
$R87ExternalIngestPath = Join-Path $PSScriptRoot 'r87-external-usage-ingest.js'
$R87MainCollectorPath = Join-Path $PSScriptRoot 'r87-main-usage-collector.js'
foreach ($R87CollectorPath in @($R87ExternalIngestPath,$R87MainCollectorPath)) {
    if (-not (Test-Path -LiteralPath $R87CollectorPath)) { throw "r87 collector helper missing: $R87CollectorPath" }
}
$R87ExternalIngestBody = [System.IO.File]::ReadAllText($R87ExternalIngestPath).Replace("`r`n","`n").Replace("`r","`n")
$R87MainCollectorBody = [System.IO.File]::ReadAllText($R87MainCollectorPath).Replace("`r`n","`n").Replace("`r","`n")
$R87R76Normalized = $PatchedR76Output.Replace("`r`n","`n").Replace("`r","`n")

$R87IngestRegex = [regex]::new("(?s)\$ExternalUsageIngest\s*=\s*@'\n.*?\n'@\n\n(?=\$MainProcessCollector\s*=)")
if (-not $R87IngestRegex.IsMatch($R87R76Normalized)) { throw 'r87 could not locate r76 external usage ingest block' }
$R87IngestAssignment = '$ExternalUsageIngest = @''' + "`n" + $R87ExternalIngestBody.TrimEnd("`n") + "`n'@`n`n"
$R87R76Normalized = $R87IngestRegex.Replace($R87R76Normalized,$R87IngestAssignment,1)

$R87CollectorRegex = [regex]::new("(?s)\$MainProcessCollector\s*=\s*@'\n.*?\n'@\n\n(?=try\s*\{)")
if (-not $R87CollectorRegex.IsMatch($R87R76Normalized)) { throw 'r87 could not locate r76 main-process collector block' }
$R87CollectorAssignment = '$MainProcessCollector = @''' + "`n" + $R87MainCollectorBody.TrimEnd("`n") + "`n'@`n`n"
$PatchedR76Output = $R87CollectorRegex.Replace($R87R76Normalized,$R87CollectorAssignment,1)

foreach ($R87CollectorMarker in @(
    'CAS-R87-MULTI-PANE-EXACT-TOKEN-TELEMETRY',
    'const visibleThreadExpression = "(() => {" +',
    'const readUsageIdentity = async (filePath, fallbackThreadId) => {',
    'sessionId: identity && typeof identity.sessionId === ''string'' ? identity.sessionId : null,',
    'parentThreadId: identity && typeof identity.parentThreadId === ''string'' ? identity.parentThreadId : null,',
    'for (const threadId of Array.from(new Set(threadIds)).slice(0, 8)) {'
)) {
    if (-not $PatchedR76Output.Contains($R87CollectorMarker)) { throw "r87 generated collector invariant missing: $R87CollectorMarker" }
}
'@
if (-not $R87Core.Contains($R87R83PatchNeedle)) {
    throw 'r87 could not locate r83 collector materialization point'
}
$R87Core = $R87Core.Replace($R87R83PatchNeedle,$R87R83PatchNeedle + $R87R83PatchCode)

# r83's original preflight expected the single-active-thread expression. The
# r87 overlay deliberately replaces that contract with visible multi-pane ids.
$R87Core = $R87Core.Replace(
    "@('const activeThreadExpression = \"(() => {\" +','r76 active-thread expression')",
    "@('const visibleThreadExpression = \"(() => {\" +','r87 visible-thread expression')"
)

foreach ($R87OverlayMarker in @(
    'R87_MULTI_PANE_STATUS_RUNTIME_PATCH',
    'R87_MULTI_PANE_COLLECTOR_PATCH',
    'r87-pane-status-runtime.js',
    'r87-external-usage-ingest.js',
    'r87-main-usage-collector.js'
)) {
    if (-not ($PatchedR75.Contains($R87OverlayMarker) -or $R87Core.Contains($R87OverlayMarker))) {
        throw "r87 pane overlay materialization marker missing: $R87OverlayMarker"
    }
}
Write-Host 'R87_MULTI_PANE_STATUS_OVERLAY_PREFLIGHT_PASS' -ForegroundColor Green
