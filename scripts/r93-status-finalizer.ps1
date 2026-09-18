# R93_COMPOSER_STATUS_STABILITY_FINALIZER
# Dot-sourced by the final r75 build stage. Mutates only generated $Patched text.

if (-not (Get-Variable -Name Patched -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r93 status finalizer requires $Patched'
}

$R93Helpers = @'
  // R93_COMPOSER_STATUS_STABILITY_RUNTIME
  function r93ComposerSurfaceFor(composer) {
    if (!(composer instanceof Element)) return null;
    if (composer.matches('.composer-surface-chrome,[data-codex-composer="true"]')) return composer;
    const nested = composer.querySelector('.composer-surface-chrome,[data-codex-composer="true"]');
    if (nested instanceof Element && isVisible(nested)) return nested;
    const editable = composer.matches('.ProseMirror,[role="textbox"],textarea')
      ? composer
      : composer.querySelector('.ProseMirror,[role="textbox"],textarea');
    const surface = editable instanceof Element
      ? editable.closest('.composer-surface-chrome,[data-codex-composer="true"]')
      : null;
    return surface instanceof Element ? surface : null;
  }

  function r93MountStatusBar(bar, composer) {
    if (!(bar instanceof Element) || !(composer instanceof Element)) return false;
    const surface = r93ComposerSurfaceFor(composer);
    if (!(surface instanceof Element)) return false;
    const inputWrap =
      surface.querySelector('.composer-input-wrap') ||
      surface.querySelector('.ProseMirror,[role="textbox"],textarea')?.parentElement ||
      surface.firstElementChild;
    if (inputWrap instanceof Element) {
      if (bar.parentElement !== surface || bar.nextElementSibling !== inputWrap) {
        surface.insertBefore(bar, inputWrap);
      }
    } else if (bar.parentElement !== surface) {
      surface.prepend(bar);
    }
    bar.setAttribute('data-cas-status-inside-composer','true');
    return true;
  }

  function r93IntegratedStatusStyle() {
    return 'box-sizing:border-box;width:calc(100% - 16px);margin:3px 8px 0;padding:2px 3px 3px;display:block;min-height:16px;overflow:hidden;border:0;border-bottom:1px solid color-mix(in srgb,CanvasText 9%,transparent);border-radius:0;background:transparent;color:color-mix(in srgb,CanvasText 62%,transparent);box-shadow:none;backdrop-filter:none;-webkit-backdrop-filter:none;font:9px/1.25 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-app-region:no-drag;cursor:pointer;position:relative;z-index:1;container-type:inline-size;user-select:text;';
  }

  function r93RenderStatusHtml(bar, html) {
    if (!(bar instanceof Element)) return false;
    const next = String(html || '');
    if ((bar.getAttribute('data-cas-render-fingerprint') || '') === next) return false;
    bar.innerHTML = next;
    bar.setAttribute('data-cas-render-fingerprint', next);
    return true;
  }
'@

if (-not $Patched.Contains('R93_COMPOSER_STATUS_STABILITY_RUNTIME')) {
    $Patched = Replace-Required $Patched '  function findComposerRoot() {' ($R93Helpers + [char]10 + [char]10 + '  function findComposerRoot() {') 'r93 composer/status helpers'
}

$R93NativeUsage = @'
  function readNativeUsage() {
    const candidate = findNativeUsagePanel();
    state.nativePanelVisible = !!candidate;
    if (!candidate) return;
    // Native Usage is global/background-aware. Keep it isolated in native*
    // fields; never overwrite pane/local counters shown in the composer line.
    const text = candidate.text;
    const speedMatch = text.match(/([\d.]+)\s*tokens?\/?s/i);
    state.metrics.nativeSpeed = speedMatch ? Number(speedMatch[1]) : null;
    const cacheMatch = text.match(/(?:缓存命中|cache\s*hit)\s*([\d.]+)%/i);
    state.metrics.nativeCacheHit = cacheMatch ? Number(cacheMatch[1]) : null;
    const totalMatch = text.match(/(?:累计|session\s*total|total)\s*([\d.,]+\s*[KMB]?)/i);
    state.metrics.nativeSessionTotal = totalMatch
      ? parseCompactNumber(totalMatch[1].replace(/\s+/g, ''))
      : null;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function readNativeUsage() {' '  function readModelLabel() {' $R93NativeUsage 'r93 isolate native Usage'

$R93EffectiveMetrics = @'
  function effectiveSpeed() {
    // R93: native/global throughput is not pane-local model throughput.
    return null;
  }
  function effectiveCacheHit() {
    const m = state.metrics;
    return Number.isFinite(m.cacheHitPercent) ? m.cacheHitPercent : null;
  }
  function effectiveSessionTotal() {
    const m = state.metrics;
    return Number.isFinite(m.sessionTotalTokens) ? m.sessionTotalTokens : null;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function effectiveSpeed() {' '  function statusHtml() {' $R93EffectiveMetrics 'r93 local-only status metrics'

if ($Patched.Contains('  function statusBarInlineStyle() {')) {
    $R93PaneStyle = @'
  function statusBarInlineStyle() {
    return r93IntegratedStatusStyle();
  }
'@
    $Patched = Replace-BlockRequired $Patched '  function statusBarInlineStyle() {' '  function removeLegacyOrDuplicateStatusBars() {' $R93PaneStyle 'r93 pane status style'

    $R93PaneLookup = @'
  function statusBarForComposer(composer) {
    if (!(composer instanceof Element)) return null;
    const surface = r93ComposerSurfaceFor(composer);
    if (!(surface instanceof Element)) return null;
    const matches = Array.from(surface.children || []).filter(function(child) {
      return child instanceof Element && child.getAttribute(PANE_STATUS_ATTR) === 'true';
    });
    const keep = matches.shift() || null;
    matches.forEach(function(extra) { extra.remove(); });
    return keep;
  }
'@
    $Patched = Replace-BlockRequired $Patched '  function statusBarForComposer(composer) {' '  function ensureStatusBars() {' $R93PaneLookup 'r93 pane status lookup'

    $OldPaneMount = '      if (bar.parentElement !== parent || bar.nextSibling !== composer) parent.insertBefore(bar, composer);'
    $NewPaneMount = @'
      if (!r93MountStatusBar(bar, composer)) {
        if (bar.parentElement !== parent || bar.nextSibling !== composer) parent.insertBefore(bar, composer);
      }
'@
    if (-not $Patched.Contains($OldPaneMount)) { throw 'r93 pane status mount anchor missing' }
    $Patched = $Patched.Replace($OldPaneMount,$NewPaneMount)

    $OldPaneActivity = @'
    const composer = bar.nextElementSibling;
    if (!(composer instanceof Element)) return 'unknown';
    const pane = paneForNode(composer);
'@
    $NewPaneActivity = @'
    const composer =
      bar.closest('[data-codex-composer-root]') ||
      bar.closest('.composer-surface-chrome,[data-codex-composer="true"]') ||
      bar.parentElement;
    if (!(composer instanceof Element)) return 'unknown';
    const pane = paneForNode(composer);
'@
    if ($Patched.Contains($OldPaneActivity)) {
        $Patched = $Patched.Replace($OldPaneActivity,$NewPaneActivity)
    }

    $OldPaneRefresh = '      bar.innerHTML = statusHtmlForPane(sessionId, threadId, agentId, bar);'
    $NewPaneRefresh = @'
      const r93Html = statusHtmlForPane(sessionId, threadId, agentId, bar);
      const r93Changed = r93RenderStatusHtml(bar, r93Html);
'@
    if (-not $Patched.Contains($OldPaneRefresh)) { throw 'r93 pane status refresh anchor missing' }
    $Patched = $Patched.Replace($OldPaneRefresh,$NewPaneRefresh)
    $Patched = $Patched.Replace('      bindIdentityCopy(bar);','      if (r93Changed) bindIdentityCopy(bar);')
} else {
    $R93BaseStatus = @'
  function ensureStatusBar() {
    let bar = document.getElementById(STATUS_ID);
    if (!bar) {
      bar = document.createElement('div');
      bar.id = STATUS_ID;
      bar.title = 'Click for telemetry charts';
      bar.addEventListener('click', function(event) {
        event.stopPropagation();
        toggleAnalytics(bar);
      });
    }
    const composer = findComposerRoot();
    if (!(composer instanceof Element)) return bar;
    if (!r93MountStatusBar(bar, composer) && composer.parentElement) {
      if (bar.parentElement !== composer.parentElement || bar.nextSibling !== composer) {
        composer.parentElement.insertBefore(bar, composer);
      }
    }
    bar.style.cssText = r93IntegratedStatusStyle();
    return bar;
  }
'@
    $Patched = Replace-BlockRequired $Patched '  function ensureStatusBar() {' '  function effectiveSpeed() {' $R93BaseStatus 'r93 base status mount'

    $R93BaseRefresh = @'
  function refreshUi() {
    ensureStyle();
    readModelLabel();
    const bar = ensureStatusBar();
    if (bar) {
      bar.style.cssText = r93IntegratedStatusStyle();
      r93RenderStatusHtml(bar, statusHtml());
    }
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }
'@
    $Patched = Replace-BlockRequired $Patched '  function refreshUi() {' '  function poll() {' $R93BaseRefresh 'r93 base status fingerprint refresh'
}

foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_RUNTIME',
    'data-cas-status-inside-composer',
    'function r93RenderStatusHtml(bar, html) {',
    'native/global throughput is not pane-local model throughput'
)) {
    if (-not $Patched.Contains($Marker)) { throw "r93 final status marker missing: $Marker" }
}
if ($Patched.Contains('state.metrics.contextTokens = used;') -or
    $Patched.Contains('state.metrics.contextWindow = limit;') -or
    $Patched.Contains('state.metrics.contextPercent = percent;')) {
    throw 'r93 native Usage poll still mutates local status context'
}

Write-Host 'R93_COMPOSER_STATUS_FINAL_OWNER_PASS' -ForegroundColor Green
Write-Host 'R93_NATIVE_USAGE_ISOLATION_PASS' -ForegroundColor Green
Write-Host 'R93_STATUS_RENDER_FINGERPRINT_PASS' -ForegroundColor Green
