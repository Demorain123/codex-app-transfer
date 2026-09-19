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
  function r94ComposerStatusDiagnostics() {
    const current = window.__casR94ComposerStatusDiagnostics;
    if (current && typeof current === 'object') return current;
    const created = {
      protocol: 'R94_COMPOSER_MOUNT_V2',
      attempts: 0,
      mounted: 0,
      lastReason: 'init',
      surface: '',
      anchor: '',
    };
    window.__casR94ComposerStatusDiagnostics = created;
    return created;
  }

  function r94VisibleComposerEditable(scope) {
    const selector = '.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea';
    const candidates = [];
    if (scope instanceof Element && scope.matches(selector)) candidates.push(scope);
    const root = scope instanceof Element ? scope : document;
    root.querySelectorAll(selector).forEach(function(node) { candidates.push(node); });
    for (const node of candidates) {
      if (node instanceof Element && isVisible(node)) return node;
    }
    return null;
  }

  function r94NearestComposerSurface(editable) {
    if (!(editable instanceof Element)) return null;
    // Do not use [data-thread-find-composer] as the final rounded surface: on
    // current Codex it can be a larger locator wrapper around the real input.
    const selector = '.composer-surface-chrome,[data-codex-composer="true"],[data-codex-composer-root],[data-testid*="composer"],form';
    const nearest = editable.closest(selector);
    if (nearest instanceof Element && isVisible(nearest)) return nearest;

    let current = editable.parentElement;
    for (let depth = 0; depth < 6 && current; depth += 1) {
      if (isVisible(current)) {
        const rect = current.getBoundingClientRect();
        if (rect.width >= 260 && rect.height >= 48 && rect.height <= 360) return current;
      }
      current = current.parentElement;
    }
    return editable.parentElement instanceof Element ? editable.parentElement : null;
  }

  function r93ComposerSurfaceFor(composer) {
    // R94_COMPOSER_SURFACE_COMPAT_RUNTIME
    // Prefer the visible editor and its nearest semantic ancestor. This mirrors
    // the robust inline-mount strategy used by current Codex UI extensions:
    // discover from a stable interactive child instead of trusting the first
    // globally-matched composer-ish wrapper.
    const scopedEditable = r94VisibleComposerEditable(composer instanceof Element ? composer : null);
    const globalEditable = scopedEditable || r94VisibleComposerEditable(null);
    const fromEditable = r94NearestComposerSurface(globalEditable);
    if (fromEditable instanceof Element) return fromEditable;

    if (!(composer instanceof Element)) return null;
    const nested = composer.querySelector('.composer-surface-chrome,[data-codex-composer="true"],[data-codex-composer-root],[data-testid*="composer"],form');
    if (nested instanceof Element && isVisible(nested)) return nested;
    return isVisible(composer) ? composer : null;
  }

'@
$Patched = Replace-BlockRequired $Patched '  function r93ComposerSurfaceFor(composer) {' '  function r93MountStatusBar(bar, composer) {' $R94ComposerSurfaceCompat 'r94 current Codex composer surface compatibility'

$R94FindComposerRootCompat = @'
  function findComposerRoot() {
    // R94_CURRENT_COMPOSER_ROOT_RUNTIME
    // Resolve from the one visible editable first so stale outer
    // [data-thread-find-composer] wrappers cannot steal the mount.
    const editable = r94VisibleComposerEditable(null);
    const surface = r94NearestComposerSurface(editable);
    if (surface instanceof Element) return surface;

    const fallbacks = document.querySelectorAll(
      '.composer-surface-chrome,[data-codex-composer="true"],[data-codex-composer-root],[data-testid*="composer"],form,[data-thread-find-composer="true"]'
    );
    for (const node of fallbacks) {
      if (node instanceof Element && isVisible(node)) return node;
    }
    return null;
  }
'@
if ($Patched.Contains('  function paneForComposer(composer) {')) {
    $Patched = Replace-BlockRequired $Patched '  function findComposerRoot() {' '  function paneForComposer(composer) {' $R94FindComposerRootCompat 'r94 current pane composer root resolver'
} elseif ($Patched.Contains('  function ensureStatusBar() {')) {
    $Patched = Replace-BlockRequired $Patched '  function findComposerRoot() {' '  function ensureStatusBar() {' $R94FindComposerRootCompat 'r94 current base composer root resolver'
} else {
    throw 'r94 could not locate composer root resolver boundary'
}

$R94ComposerMountCompat = @'
  function r93MountStatusBar(bar, composer) {
    // R94_COMPOSER_INLINE_MOUNT_RUNTIME
    if (!(bar instanceof Element)) return false;
    const diagnostics = r94ComposerStatusDiagnostics();
    diagnostics.attempts += 1;

    const surface = r93ComposerSurfaceFor(composer);
    if (!(surface instanceof Element) || !surface.isConnected) {
      diagnostics.lastReason = 'no-surface';
      return false;
    }

    const editable = r94VisibleComposerEditable(surface) || r94VisibleComposerEditable(null);
    let before = null;
    if (editable instanceof Element && surface.contains(editable)) {
      before = editable;
      while (before.parentElement instanceof Element && before.parentElement !== surface) {
        before = before.parentElement;
      }
      if (before.parentElement !== surface) before = null;
    }
    if (!(before instanceof Element)) {
      before =
        surface.querySelector('.composer-input-wrap') ||
        surface.querySelector('.ProseMirror,[role="textbox"],textarea')?.parentElement ||
        surface.firstElementChild;
    }

    try {
      if (before instanceof Element) {
        if (bar.parentElement !== surface || bar.nextElementSibling !== before) {
          surface.insertBefore(bar, before);
        }
      } else if (bar.parentElement !== surface) {
        surface.prepend(bar);
      }
    } catch {
      diagnostics.lastReason = 'insert-failed';
      return false;
    }

    bar.setAttribute('data-cas-status-inside-composer','true');
    bar.setAttribute('data-cas-status-owner','r94-inline');
    diagnostics.mounted += 1;
    diagnostics.lastReason = 'mounted';
    diagnostics.surface = String(surface.tagName || '').toLowerCase() +
      (surface.id ? ('#' + surface.id) : '') +
      (surface.getAttribute('data-testid') ? ('[data-testid=' + surface.getAttribute('data-testid') + ']') : '');
    diagnostics.anchor = before instanceof Element ? String(before.tagName || '').toLowerCase() : 'prepend';
    return true;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function r93MountStatusBar(bar, composer) {' '  function r93IntegratedStatusStyle() {' $R94ComposerMountCompat 'r94 current Codex inline status mount'

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
    "bar.setAttribute('data-cas-status-inside-composer','true');",
    'R94_COMPOSER_SURFACE_COMPAT_RUNTIME',
    'R94_CURRENT_COMPOSER_ROOT_RUNTIME',
    'R94_COMPOSER_INLINE_MOUNT_RUNTIME',
    'R94_COMPOSER_MOUNT_V2',
    "bar.setAttribute('data-cas-status-owner','r94-inline');",
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
Write-Host 'R94_COMPOSER_INLINE_MOUNT_V2_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_USAGE_SCAN_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_DUPLICATE_USAGE_MIRROR_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_NO_STATUS_VIEWPORT_TRACKING_PASS' -ForegroundColor Green
