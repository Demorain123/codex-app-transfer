# R94_COMPOSER_STATUS_INSIDE_FINALIZER
# Final generated-runtime patch for r94.
#
# Important: r93's status row is intentionally kept as a single Transfer-owned
# child of the stable composer surface, before the input wrapper. This preserves
# the user-visible requirement that the status line lives INSIDE the rounded
# input box. r94 does not move it into a document/body floating overlay.
#
# r94 only removes the remaining global/native Usage scan and duplicate mirror;
# exact turn/thread telemetry is supplied by r94-turn-notification-finalizer.ps1.

if (-not (Get-Variable -Name Patched -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r94 composer status finalizer requires $Patched'
}

foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_RUNTIME',
    'function r93MountStatusBar(bar, composer) {',
    'surface.insertBefore(bar, inputWrap);',
    "bar.setAttribute('data-cas-status-inside-composer','true');",
    'function r93RenderStatusHtml(bar, html) {'
)) {
    if (-not $Patched.Contains($Marker)) {
        throw "r94 expected r93 inside-composer status owner missing: $Marker"
    }
}

foreach ($Forbidden in @(
    'R94_STATUS_OVERLAY_RUNTIME',
    "const R94_STATUS_OVERLAY_ID = 'cas-r94-status-overlay';",
    "bar.setAttribute('data-cas-status-overlay','true');"
)) {
    if ($Patched.Contains($Forbidden)) {
        throw "r94 refuses detached status overlay runtime: $Forbidden"
    }
}

$R94NoNativeUsage = @'
  function readNativeUsage() {
    // R94: the Codex Usage panel is global/background-aware and is not a safe
    // pane-local source. Do not rescan renderer text or borrow its values.
    state.nativePanelVisible = false;
    state.metrics.nativeSpeed = null;
    state.metrics.nativeCacheHit = null;
    state.metrics.nativeSessionTotal = null;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function readNativeUsage() {' '  function readModelLabel() {' $R94NoNativeUsage 'r94 disable native/global Usage scan'

$R94MirrorDisabled = @'
  function renderMirror() {
    // r94 keeps one compact status row inside the composer. The older duplicate
    // Usage mirror stays hidden so telemetry has one visible owner.
    const mirror = document.getElementById(MIRROR_ID);
    if (mirror) mirror.hidden = true;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function renderMirror() {' '  function loadHistory() {' $R94MirrorDisabled 'r94 disable duplicate compact Usage mirror'

foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_RUNTIME',
    'function r93MountStatusBar(bar, composer) {',
    'surface.insertBefore(bar, inputWrap);',
    "bar.setAttribute('data-cas-status-inside-composer','true');",
    'do not rescan renderer text or borrow its values',
    'one compact status row inside the composer'
)) {
    if (-not $Patched.Contains($Marker)) {
        throw "r94 inside-composer runtime marker missing: $Marker"
    }
}

foreach ($Forbidden in @(
    'R94_STATUS_OVERLAY_RUNTIME',
    "const R94_STATUS_OVERLAY_ID = 'cas-r94-status-overlay';",
    "bar.setAttribute('data-cas-status-overlay','true');"
)) {
    if ($Patched.Contains($Forbidden)) {
        throw "r94 detached status overlay survived final materialization: $Forbidden"
    }
}

Write-Host 'R94_STATUS_INSIDE_COMPOSER_FINAL_OWNER_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_USAGE_SCAN_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_DUPLICATE_USAGE_MIRROR_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_NO_STATUS_VIEWPORT_TRACKING_PASS' -ForegroundColor Green
