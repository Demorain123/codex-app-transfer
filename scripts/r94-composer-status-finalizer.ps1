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

$R94ComposerSurfaceCompat = @'
  function r93ComposerSurfaceFor(composer) {
    // R94_COMPOSER_SURFACE_COMPAT_RUNTIME
    // r89's canonical composer may be the <form> or a data-testid composer
    // wrapper on newer Codex builds. Treat that canonical visible root as the
    // rounded composer surface instead of requiring the older
    // .composer-surface-chrome/data-codex-composer markers.
    if (!(composer instanceof Element)) return null;
    const selector = '[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"],[data-testid*="composer"],.composer-surface-chrome,form';
    if (composer.matches(selector) && isVisible(composer)) return composer;

    const nested = composer.querySelector(selector);
    if (nested instanceof Element && isVisible(nested)) return nested;

    const editable = composer.matches('.ProseMirror,[role="textbox"],textarea')
      ? composer
      : composer.querySelector('.ProseMirror,[role="textbox"],textarea');
    if (editable instanceof Element) {
      const semantic = editable.closest(selector);
      if (semantic instanceof Element && isVisible(semantic)) return semantic;
      // The canonical composer supplied by r89 can intentionally fall back to
      // editable.parentElement when Codex removes semantic wrapper attrs.
      if (composer.contains(editable) && isVisible(composer)) return composer;
      const parent = editable.parentElement;
      if (parent instanceof Element && isVisible(parent)) return parent;
    }
    return isVisible(composer) ? composer : null;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function r93ComposerSurfaceFor(composer) {' '  function r93MountStatusBar(bar, composer) {' $R94ComposerSurfaceCompat 'r94 current Codex composer surface compatibility'

$R94NoNativeUsage = @'
  function readNativeUsage() {
    // R94_NATIVE_USAGE_SCAN_DISABLED_RUNTIME
    // The Codex Usage panel is global/background-aware and is not a safe
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
    // R94_DUPLICATE_USAGE_MIRROR_DISABLED_RUNTIME
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
    'R94_COMPOSER_SURFACE_COMPAT_RUNTIME',
    '[data-testid*="composer"]',
    'R94_NATIVE_USAGE_SCAN_DISABLED_RUNTIME',
    'R94_DUPLICATE_USAGE_MIRROR_DISABLED_RUNTIME'
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
