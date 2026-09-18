# R94_STATUS_OVERLAY_FINALIZER
# Final generated-runtime patch: status bars are Transfer-owned overlay nodes.
# Native Codex composer/React children remain structurally read-only.

if (-not (Get-Variable -Name Patched -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r94 status overlay finalizer requires $Patched'
}

$R94StatusHelpers = @'
  // R94_STATUS_OVERLAY_RUNTIME
  const R94_STATUS_OVERLAY_ID = 'cas-r94-status-overlay';
  const r94StatusByComposer = new WeakMap();
  const r94ComposerByStatus = new WeakMap();
  const r94KnownStatusBars = new Set();
  let r94StatusFrame = 0;
  let r94StatusRuntimeArmed = false;

  const r94StatusResizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver(function() { r94ScheduleStatusPosition(); })
    : null;

  function r94EnsureStatusOverlayRoot() {
    let root = document.getElementById(R94_STATUS_OVERLAY_ID);
    if (root instanceof HTMLElement) return root;
    root = document.createElement('div');
    root.id = R94_STATUS_OVERLAY_ID;
    root.style.cssText = 'position:fixed;inset:0;z-index:2147481900;pointer-events:none;overflow:hidden;contain:layout style paint;';
    (document.body || document.documentElement).appendChild(root);
    return root;
  }

  function r94StatusSurfaceForComposer(composer) {
    return r93ComposerSurfaceFor(composer);
  }

  function r94ComposerForStatusBar(bar) {
    const composer = r94ComposerByStatus.get(bar);
    return composer instanceof Element && composer.isConnected ? composer : null;
  }

  function r94AttachStatusBar(bar, composer) {
    if (!(bar instanceof Element) || !(composer instanceof Element)) return false;
    const surface = r94StatusSurfaceForComposer(composer);
    if (!(surface instanceof Element) || !surface.isConnected) return false;
    const root = r94EnsureStatusOverlayRoot();
    if (bar.parentElement !== root) root.appendChild(bar);
    r94StatusByComposer.set(composer, bar);
    r94ComposerByStatus.set(bar, composer);
    r94KnownStatusBars.add(bar);
    bar.setAttribute('data-cas-status-overlay','true');
    bar.removeAttribute('data-cas-status-inside-composer');
    if (r94StatusResizeObserver) {
      try { r94StatusResizeObserver.observe(surface); } catch {}
    }
    r94ScheduleStatusPosition();
    return true;
  }

  function r94StatusBarForComposer(composer) {
    if (!(composer instanceof Element)) return null;
    const bar = r94StatusByComposer.get(composer);
    return bar instanceof Element && bar.isConnected ? bar : null;
  }

  function r94PositionStatusBars() {
    r94StatusFrame = 0;
    if (document.visibilityState === 'hidden') return;
    const root = document.getElementById(R94_STATUS_OVERLAY_ID);
    if (root instanceof HTMLElement) root.hidden = false;
    const writes = [];
    for (const bar of Array.from(r94KnownStatusBars)) {
      const composer = r94ComposerForStatusBar(bar);
      if (!(composer instanceof Element) || !bar.isConnected) {
        r94KnownStatusBars.delete(bar);
        if (bar && bar.isConnected) bar.remove();
        continue;
      }
      const surface = r94StatusSurfaceForComposer(composer);
      if (!(surface instanceof Element) || !surface.isConnected) {
        bar.style.display = 'none';
        continue;
      }
      let rect;
      try { rect = surface.getBoundingClientRect(); } catch { rect = null; }
      if (!rect || rect.width < 80 || rect.height < 30 || rect.bottom < 0 || rect.top > innerHeight) {
        bar.style.display = 'none';
        continue;
      }
      writes.push({
        bar,
        x: Math.max(4, rect.left + 8),
        y: Math.max(2, rect.top + 3),
        width: Math.max(80, rect.width - 16),
      });
    }
    for (const item of writes) {
      item.bar.style.display = 'block';
      item.bar.style.width = item.width + 'px';
      item.bar.style.transform = 'translate3d(' + item.x + 'px,' + item.y + 'px,0)';
    }
  }

  function r94ScheduleStatusPosition() {
    if (r94StatusFrame || document.visibilityState === 'hidden') return;
    r94StatusFrame = requestAnimationFrame(r94PositionStatusBars);
  }

  function r94PruneStatusBars(active) {
    for (const bar of Array.from(r94KnownStatusBars)) {
      if (active.has(bar) && bar.isConnected) continue;
      const composer = r94ComposerByStatus.get(bar);
      if (composer instanceof Element && r94StatusResizeObserver) {
        const surface = r94StatusSurfaceForComposer(composer);
        if (surface instanceof Element) {
          try { r94StatusResizeObserver.unobserve(surface); } catch {}
        }
      }
      r94KnownStatusBars.delete(bar);
      if (bar.isConnected) bar.remove();
    }
  }

  function r94HandleStatusVisibility() {
    const root = document.getElementById(R94_STATUS_OVERLAY_ID);
    if (document.visibilityState === 'hidden') {
      if (root instanceof HTMLElement) root.hidden = true;
      if (r94StatusFrame) cancelAnimationFrame(r94StatusFrame);
      r94StatusFrame = 0;
      return;
    }
    if (root instanceof HTMLElement) root.hidden = false;
    r94ScheduleStatusPosition();
  }

  function r94EnsureStatusOverlayRuntime() {
    if (r94StatusRuntimeArmed) return;
    r94StatusRuntimeArmed = true;
    window.addEventListener('resize', r94ScheduleStatusPosition, { passive: true });
    window.addEventListener('scroll', r94ScheduleStatusPosition, { passive: true, capture: true });
    document.addEventListener('visibilitychange', r94HandleStatusVisibility);
  }

  function r94CleanupStatusOverlay() {
    if (r94StatusFrame) cancelAnimationFrame(r94StatusFrame);
    r94StatusFrame = 0;
    window.removeEventListener('resize', r94ScheduleStatusPosition);
    window.removeEventListener('scroll', r94ScheduleStatusPosition, true);
    document.removeEventListener('visibilitychange', r94HandleStatusVisibility);
    if (r94StatusResizeObserver) {
      try { r94StatusResizeObserver.disconnect(); } catch {}
    }
    r94KnownStatusBars.clear();
    const root = document.getElementById(R94_STATUS_OVERLAY_ID);
    if (root) root.remove();
    r94StatusRuntimeArmed = false;
  }
'@

if (-not $Patched.Contains('R94_STATUS_OVERLAY_RUNTIME')) {
    $Patched = Replace-Required $Patched '  function statusBarInlineStyle() {' ($R94StatusHelpers + [char]10 + [char]10 + '  function statusBarInlineStyle() {') 'r94 status overlay helpers'
}

$R94RetiredNativeMount = @'
  function r93MountStatusBar() {
    return false;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function r93MountStatusBar(bar, composer) {' '  function r93IntegratedStatusStyle() {' $R94RetiredNativeMount 'r94 retire native composer child status mount'

$R94StatusStyle = @'
  function statusBarInlineStyle() {
    return 'box-sizing:border-box;position:absolute;left:0;top:0;margin:0;padding:2px 4px 3px;display:block;min-height:16px;max-height:32px;overflow:hidden;border:0;border-bottom:1px solid color-mix(in srgb,CanvasText 9%,transparent);border-radius:0;background:color-mix(in srgb,Canvas 86%,transparent);color:color-mix(in srgb,CanvasText 62%,transparent);box-shadow:none;backdrop-filter:blur(7px);-webkit-backdrop-filter:blur(7px);font:9px/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-app-region:no-drag;cursor:pointer;z-index:1;container-type:inline-size;user-select:text;pointer-events:auto;';
  }
'@
$Patched = Replace-BlockRequired $Patched '  function statusBarInlineStyle() {' '  function removeLegacyOrDuplicateStatusBars() {' $R94StatusStyle 'r94 overlay status style'

$R94RemoveLegacy = @'
  function removeLegacyOrDuplicateStatusBars() {
    document.querySelectorAll('#' + STATUS_ID + ',[' + PANE_STATUS_ATTR + '=true]').forEach(function(node) {
      if (!(node instanceof Element)) return;
      if (node.closest('#' + R94_STATUS_OVERLAY_ID)) return;
      node.remove();
    });
  }
'@
$Patched = Replace-BlockRequired $Patched '  function removeLegacyOrDuplicateStatusBars() {' '  function statusBarForComposer(composer) {' $R94RemoveLegacy 'r94 remove stale native-tree status bars'

$R94StatusLookup = @'
  function statusBarForComposer(composer) {
    return r94StatusBarForComposer(composer);
  }
'@
$Patched = Replace-BlockRequired $Patched '  function statusBarForComposer(composer) {' '  function ensureStatusBars() {' $R94StatusLookup 'r94 map composer to overlay status'

$R94EnsureBars = @'
  function ensureStatusBars() {
    r94EnsureStatusOverlayRuntime();
    removeLegacyOrDuplicateStatusBars();
    const composers = findComposerRoots();
    const active = new Set();
    const bars = [];
    composers.forEach(function(composer, index) {
      if (!(composer instanceof Element)) return;
      const pane = paneForComposer(composer);
      const sessionId = paneSessionId(pane, composer);
      let threadId = paneThreadId(pane, composer);
      const externalThreadId = normalizePaneId(state.metrics && state.metrics.externalThreadId);
      if (!threadId && index === 0) threadId = externalThreadId;
      const agentId = paneAgentId(pane);
      let bar = statusBarForComposer(composer);
      if (!bar) {
        bar = document.createElement('div');
        bar.setAttribute(PANE_STATUS_ATTR, 'true');
        bar.title = 'Click metrics for charts; click an identity value to copy it';
        bar.addEventListener('click', function(event) {
          if (event.target instanceof Element && event.target.closest('[data-cas-copy-value]')) return;
          event.stopPropagation();
          const paneThread = normalizePaneId(bar.getAttribute(PANE_THREAD_ATTR));
          const external = normalizePaneId(state.metrics && state.metrics.externalThreadId);
          if (paneThread && external && paneThread !== external) return;
          toggleAnalytics(bar);
        });
      }
      if (index === 0) bar.id = STATUS_ID;
      else if (bar.id === STATUS_ID) bar.removeAttribute('id');
      bar.setAttribute(PANE_SESSION_ATTR, sessionId || '');
      bar.setAttribute(PANE_THREAD_ATTR, threadId || '');
      bar.setAttribute(PANE_AGENT_ATTR, agentId || '');
      bar.style.cssText = statusBarInlineStyle();
      if (!r94AttachStatusBar(bar, composer)) return;
      active.add(bar);
      bars.push(bar);
    });
    r94PruneStatusBars(active);
    r94ScheduleStatusPosition();
    return bars;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function ensureStatusBars() {' '  function ensureStatusBar() {' $R94EnsureBars 'r94 Transfer-owned overlay status bars'

$R94PaneActivity = @'
  function paneActivityState(bar) {
    if (!(bar instanceof Element)) return 'unknown';
    const composer = r94ComposerForStatusBar(bar);
    if (!(composer instanceof Element)) return 'unknown';
    const surface = r94StatusSurfaceForComposer(composer);
    const scope = surface instanceof Element ? surface : composer;
    if (!(scope instanceof Element)) return 'unknown';

    const controls = scope.querySelectorAll('button,[role="button"]');
    let sendVisible = false;
    for (const control of controls) {
      if (!(control instanceof Element) || !isVisible(control) || insideOwnUi(control)) continue;
      const hint = [
        control.getAttribute('aria-label'), control.getAttribute('title'),
        control.getAttribute('data-testid'), control.getAttribute('data-state'),
        control.textContent,
      ].filter(Boolean).join(' ').toLowerCase();
      if (/(^|[\s:_-])(stop|cancel|interrupt|abort|pause)([\s:_-]|$)|停止|取消|中止|终止|暂停/i.test(hint)) return 'live';
      if (/(^|[\s:_-])(send|submit)([\s:_-]|$)|发送|提交/i.test(hint)) sendVisible = true;
    }

    const busy = scope.querySelectorAll('[aria-busy="true"],[data-loading="true"],[data-state="loading"],[data-state="pending"],[data-state="running"]');
    for (const node of busy) {
      if (node instanceof Element && isVisible(node) && !insideOwnUi(node)) return 'live';
    }
    return sendVisible ? 'idle' : 'unknown';
  }
'@
$Patched = Replace-BlockRequired $Patched '  function paneActivityState(bar) {' '  function paneIsLiveForStatus(bar) {' $R94PaneActivity 'r94 pane activity through native composer anchor'

$R94NoNativeUsage = @'
  function readNativeUsage() {
    // R94: do not rescan the full renderer DOM for global/native Usage every
    // poll. Pane status is exact/local-only; the native Usage UI remains owned
    // and rendered by Codex itself.
    state.nativePanelVisible = false;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function readNativeUsage() {' '  function readModelLabel() {' $R94NoNativeUsage 'r94 remove full-DOM native Usage scan'

$R94MirrorDisabled = @'
  function renderMirror() {
    const mirror = document.getElementById(MIRROR_ID);
    if (mirror) mirror.hidden = true;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function renderMirror() {' '  function loadHistory() {' $R94MirrorDisabled 'r94 disable duplicate compact Usage mirror'

$R94RefreshOld = '    renderMirror();' + [char]10 + '    sampleHistory(false);'
$R94RefreshNew = '    r94ScheduleStatusPosition();' + [char]10 + '    renderMirror();' + [char]10 + '    sampleHistory(false);'
$Patched = Replace-Required $Patched $R94RefreshOld $R94RefreshNew 'r94 schedule status overlay after refresh'
$R94CleanupNew = '  function cleanup() {' + [char]10 + '    try { r94CleanupStatusOverlay(); } catch {}'
$Patched = Replace-Required $Patched '  function cleanup() {' $R94CleanupNew 'r94 status overlay cleanup'

foreach ($Marker in @(
    'R94_STATUS_OVERLAY_RUNTIME',
    "const R94_STATUS_OVERLAY_ID = 'cas-r94-status-overlay';",
    'const r94StatusByComposer = new WeakMap();',
    'function r94AttachStatusBar(bar, composer) {',
    'function r94ComposerForStatusBar(bar) {',
    'function r94CleanupStatusOverlay() {',
    "bar.setAttribute('data-cas-status-overlay','true');",
    'do not rescan the full renderer DOM for global/native Usage',
    'function renderMirror() {'
)) {
    if (-not $Patched.Contains($Marker)) {
        throw "r94 status overlay runtime marker missing: $Marker"
    }
}
foreach ($Forbidden in @(
    'surface.insertBefore(bar, inputWrap)',
    'surface.prepend(bar)'
)) {
    if ($Patched.Contains($Forbidden)) {
        throw "r94 retained native composer child status mutation: $Forbidden"
    }
}

Write-Host 'R94_STATUS_OVERLAY_FINAL_OWNER_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_COMPOSER_DOM_READONLY_PASS' -ForegroundColor Green
Write-Host 'R94_STATUS_SHARED_RAF_PASS' -ForegroundColor Green
Write-Host 'R94_NO_NATIVE_USAGE_FULL_DOM_SCAN_PASS' -ForegroundColor Green
Write-Host 'R94_DUPLICATE_USAGE_MIRROR_DISABLED_PASS' -ForegroundColor Green
