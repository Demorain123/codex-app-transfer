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
      protocol: 'R94_COMPOSER_MOUNT_V3',
      attempts: 0,
      mounted: 0,
      unsafeRejects: 0,
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

  function r94DirectChildOf(parent, node) {
    if (!(parent instanceof Element) || !(node instanceof Element) || !parent.contains(node) || parent === node) return null;
    let current = node;
    while (current.parentElement instanceof Element && current.parentElement !== parent) {
      current = current.parentElement;
    }
    return current.parentElement === parent ? current : null;
  }

  function r94UnsafeEditorBoundary(node) {
    if (!(node instanceof Element)) return true;
    const editorSelector = '.ProseMirror,[contenteditable="true"],[role="textbox"],textarea,input';
    if (node.matches(editorSelector)) return true;
    return !!node.closest('.ProseMirror[contenteditable="true"],[contenteditable="true"],[role="textbox"][contenteditable="true"]');
  }

  function r94VisibleControlOutsideEditor(surface, editable) {
    if (!(surface instanceof Element)) return false;
    const selector = '.composer-footer,[data-codex-intelligence-trigger="true"],button,[role="button"],[aria-haspopup]';
    for (const node of surface.querySelectorAll(selector)) {
      if (!(node instanceof Element) || !isVisible(node)) continue;
      if (editable instanceof Element && (node === editable || editable.contains(node))) continue;
      return true;
    }
    return false;
  }

  function r94SafeComposerSurface(editable) {
    // R94_EDITOR_BOUNDARY_GUARD_RUNTIME
    // Never use the ProseMirror/contenteditable tree itself as a mount host.
    // Walk outward until a small composer shell is found that contains both the
    // editor and independent composer controls/footer evidence.
    if (!(editable instanceof Element) || !editable.isConnected) return null;
    const stableSelector = '.composer-surface-chrome,[data-codex-composer="true"],[data-codex-composer-root],[data-testid*="composer"],form';
    const candidates = [];
    let current = editable.parentElement;
    for (let depth = 0; depth < 10 && current && current !== document.body; depth += 1) {
      if (!(current instanceof Element)) break;
      if (!current.contains(editable) || r94UnsafeEditorBoundary(current)) {
        current = current.parentElement;
        continue;
      }
      let rect = null;
      try { rect = current.getBoundingClientRect(); } catch {}
      if (!rect || rect.width < 260 || rect.height < 48 || rect.height > Math.min(560, innerHeight * 0.65)) {
        current = current.parentElement;
        continue;
      }
      const before = r94DirectChildOf(current, editable);
      if (!(before instanceof Element)) {
        current = current.parentElement;
        continue;
      }
      const semantic = current.matches(stableSelector);
      const controls = r94VisibleControlOutsideEditor(current, editable);
      const footer = !!current.querySelector('.composer-footer');
      const modelTrigger = !!current.querySelector('[data-codex-intelligence-trigger="true"]');
      const score = (semantic ? 8 : 0) + (footer ? 8 : 0) + (modelTrigger ? 6 : 0) + (controls ? 4 : 0) - depth * 0.1;
      if (semantic || controls || footer || modelTrigger) {
        candidates.push({ node: current, before, score });
      }
      current = current.parentElement;
    }
    if (!candidates.length) return null;
    candidates.sort(function(a,b) { return b.score - a.score; });
    return candidates[0];
  }

  function r94DescribeMountNode(node) {
    if (!(node instanceof Element)) return '';
    const className = typeof node.className === 'string'
      ? node.className.trim().split(/\s+/).slice(0,2).join('.')
      : '';
    return String(node.tagName || '').toLowerCase() +
      (node.id ? ('#' + node.id) : '') +
      (node.getAttribute('data-testid') ? ('[data-testid=' + node.getAttribute('data-testid') + ']') : '') +
      (className ? ('.' + className) : '');
  }

  function r94RemoveUnsafeStatusNodes() {
    document.querySelectorAll('#' + STATUS_ID + ',[' + PANE_STATUS_ATTR + '=true]').forEach(function(node) {
      if (!(node instanceof Element)) return;
      const editor = node.closest('.ProseMirror[contenteditable="true"],[contenteditable="true"],[role="textbox"][contenteditable="true"]');
      if (editor instanceof Element) node.remove();
    });
  }

  function r93ComposerSurfaceFor(composer) {
    // R94_COMPOSER_SURFACE_COMPAT_RUNTIME
    const scopedEditable = r94VisibleComposerEditable(composer instanceof Element ? composer : null);
    const editable = scopedEditable || r94VisibleComposerEditable(null);
    const mount = r94SafeComposerSurface(editable);
    return mount && mount.node instanceof Element ? mount.node : null;
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
    // R94_COMPOSER_FAIL_CLOSED_MOUNT_RUNTIME
    if (!(bar instanceof Element)) return false;
    const diagnostics = r94ComposerStatusDiagnostics();
    diagnostics.attempts += 1;
    r94RemoveUnsafeStatusNodes();

    const editable = r94VisibleComposerEditable(composer instanceof Element ? composer : null) ||
      r94VisibleComposerEditable(null);
    const mount = r94SafeComposerSurface(editable);
    const surface = mount && mount.node instanceof Element ? mount.node : null;
    const before = mount && mount.before instanceof Element ? mount.before : null;

    if (!(editable instanceof Element) || !(surface instanceof Element) || !(before instanceof Element) ||
        !surface.isConnected || !surface.contains(editable) || r94UnsafeEditorBoundary(surface)) {
      diagnostics.unsafeRejects += 1;
      diagnostics.lastReason = 'no-safe-surface';
      diagnostics.surface = r94DescribeMountNode(surface);
      diagnostics.anchor = r94DescribeMountNode(before);
      if (bar.isConnected) bar.remove();
      return false;
    }

    // The bar must be a sibling of the editor branch, never a child of the
    // ProseMirror/contenteditable subtree. This is the hard guard that prevents
    // telemetry HTML from becoming draft/prompt text.
    if (editable === surface || editable.contains(surface) || editable.contains(before) ||
        before === surface || before.parentElement !== surface) {
      diagnostics.unsafeRejects += 1;
      diagnostics.lastReason = 'unsafe-editor-branch';
      diagnostics.surface = r94DescribeMountNode(surface);
      diagnostics.anchor = r94DescribeMountNode(before);
      if (bar.isConnected) bar.remove();
      return false;
    }

    try {
      bar.setAttribute('contenteditable','false');
      bar.setAttribute('data-cas-status-inside-composer','true');
      bar.setAttribute('data-cas-status-owner','r94-inline-safe');
      if (bar.parentElement !== surface || bar.nextElementSibling !== before) {
        surface.insertBefore(bar, before);
      }
    } catch {
      diagnostics.lastReason = 'insert-failed';
      if (bar.isConnected) bar.remove();
      return false;
    }

    const escapedIntoEditor = bar.closest('.ProseMirror[contenteditable="true"],[contenteditable="true"],[role="textbox"][contenteditable="true"]');
    if (escapedIntoEditor instanceof Element) {
      diagnostics.unsafeRejects += 1;
      diagnostics.lastReason = 'post-insert-editor-boundary';
      bar.remove();
      return false;
    }

    diagnostics.mounted += 1;
    diagnostics.lastReason = 'mounted-safe';
    diagnostics.surface = r94DescribeMountNode(surface);
    diagnostics.anchor = r94DescribeMountNode(before);
    return true;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function r93MountStatusBar(bar, composer) {' '  function r93IntegratedStatusStyle() {' $R94ComposerMountCompat 'r94 safe current Codex inline status mount'

# The inherited r93 fallback mounted a failed inline bar beside the composer.
# r94 must fail closed instead: an unsafe/no-surface result means no bar.
$R94PaneFallback = @'
      if (!r93MountStatusBar(bar, composer)) {
        if (bar.parentElement !== parent || bar.nextSibling !== composer) parent.insertBefore(bar, composer);
      }
'@
$R94PaneFailClosed = @'
      if (!r93MountStatusBar(bar, composer)) {
        if (bar.isConnected) bar.remove();
        return;
      }
'@
if ($Patched.Contains($R94PaneFallback)) {
    $Patched = $Patched.Replace($R94PaneFallback,$R94PaneFailClosed)
}

$R94BaseFallback = @'
    if (!r93MountStatusBar(bar, composer) && composer.parentElement) {
      if (bar.parentElement !== composer.parentElement || bar.nextSibling !== composer) {
        composer.parentElement.insertBefore(bar, composer);
      }
    }
'@
$R94BaseFailClosed = @'
    if (!r93MountStatusBar(bar, composer)) {
      if (bar.isConnected) bar.remove();
      return null;
    }
'@
if ($Patched.Contains($R94BaseFallback)) {
    $Patched = $Patched.Replace($R94BaseFallback,$R94BaseFailClosed)
}

foreach ($UnsafeRuntimeMount in @(
    'if (bar.parentElement !== parent || bar.nextSibling !== composer) parent.insertBefore(bar, composer);',
    'composer.parentElement.insertBefore(bar, composer);'
)) {
    if ($Patched.Contains($UnsafeRuntimeMount)) {
        throw "r94 unsafe status fallback survived final materialization: $UnsafeRuntimeMount"
    }
}
Write-Host 'R94_UNSAFE_EDITOR_MOUNT_FALLBACKS_ABSENT_PASS' -ForegroundColor Green

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
    'R94_COMPOSER_MOUNT_V3',
    'R94_EDITOR_BOUNDARY_GUARD_RUNTIME',
    'R94_COMPOSER_FAIL_CLOSED_MOUNT_RUNTIME',
    "bar.setAttribute('data-cas-status-owner','r94-inline-safe');",
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
Write-Host 'R94_COMPOSER_INLINE_MOUNT_V3_EDITOR_SAFE_PASS' -ForegroundColor Green
Write-Host 'R94_STATUS_NEVER_ENTERS_EDITABLE_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_USAGE_SCAN_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_DUPLICATE_USAGE_MIRROR_DISABLED_PASS' -ForegroundColor Green
Write-Host 'R94_NO_STATUS_VIEWPORT_TRACKING_PASS' -ForegroundColor Green
