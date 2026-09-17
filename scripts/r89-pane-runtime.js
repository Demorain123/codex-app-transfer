// R89_PANE_RUNTIME_JS
// Pane runtime correctness overlay: canonical composer discovery, exactly one
// status bar per visible pane, full copyable identity values, and fail-closed
// telemetry ownership. No network calls or session/provider writes.

// R89_COMPOSER_BLOCK_START
  const R89_COMPOSER_SELECTOR = '[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"],[data-testid*="composer"],.composer-surface-chrome,form';
  const R89_EDITABLE_SELECTOR = '.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea';

  function canonicalComposerForEditable(editable) {
    if (!(editable instanceof Element) || !isVisible(editable)) return null;
    return editable.closest(R89_COMPOSER_SELECTOR) || editable.parentElement;
  }

  function findComposerRoots() {
    const roots = [];
    const seen = new Set();
    const add = function(node) {
      if (!(node instanceof Element) || seen.has(node) || !isVisible(node)) return;
      seen.add(node);
      roots.push(node);
    };

    // One visible editor defines one canonical composer. This deliberately does
    // not enumerate every nested composer-ish ancestor, which caused r88 to
    // mount duplicate bars for a single pane.
    const editables = Array.from(document.querySelectorAll(R89_EDITABLE_SELECTOR))
      .filter(function(node) { return node instanceof Element && isVisible(node); });
    for (const editable of editables) add(canonicalComposerForEditable(editable));
    if (roots.length) return roots;

    // Defensive fallback for transient mounts before the editor itself exists.
    document.querySelectorAll('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"]').forEach(add);
    return roots;
  }

  function findComposerRoot() {
    const roots = findComposerRoots();
    return roots.length ? roots[0] : null;
  }

  function paneForComposer(composer) {
    if (!(composer instanceof Element)) return null;
    const all = findComposerRoots();
    let best = composer.parentElement || composer;
    let current = best;
    for (let depth = 0; depth < 12; depth += 1) {
      const parent = current && current.parentElement;
      if (!(parent instanceof Element) || parent === document.body || parent === document.documentElement) break;
      const count = all.filter(function(item) { return parent.contains(item); }).length;
      if (count !== 1) break;
      best = parent;
      current = parent;
    }
    return best;
  }

  function paneForNode(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    const composers = findComposerRoots();
    if (!composers.length) return null;
    for (const composer of composers) {
      const pane = paneForComposer(composer);
      if (pane instanceof Element && element instanceof Element && pane.contains(element)) return pane;
    }
    if (!(element instanceof Element)) return paneForComposer(composers[0]);
    let rect;
    try { rect = element.getBoundingClientRect(); } catch { rect = null; }
    if (!rect) return paneForComposer(composers[0]);
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    let best = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const composer of composers) {
      let cr;
      try { cr = composer.getBoundingClientRect(); } catch { continue; }
      const dx = cx - (cr.left + cr.width / 2);
      const dy = cy - (cr.top + cr.height / 2);
      const distance = Math.abs(dx) + Math.abs(dy) * 0.2;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = paneForComposer(composer);
      }
    }
    return best || paneForComposer(composers[0]);
  }

  function composerForPane(pane) {
    if (!(pane instanceof Element)) return findComposerRoot();
    for (const composer of findComposerRoots()) {
      if (paneForComposer(composer) === pane || pane.contains(composer)) return composer;
    }
    return null;
  }

  function normalizePaneId(value) {
    return String(value || '').replace(/^local:/i, '').trim().toLowerCase();
  }

  function normalizePaneThreadId(value) {
    return normalizePaneId(value);
  }

  function idFromNode(node, attrs) {
    if (!(node instanceof Element)) return '';
    for (const attr of attrs) {
      const value = normalizePaneId(node.getAttribute(attr));
      if (value) return value;
    }
    return '';
  }

  function paneIdentityFromAttrs(pane, composer, attrs) {
    let current = composer instanceof Element ? composer : null;
    for (let depth = 0; depth < 14 && current; depth += 1) {
      const value = idFromNode(current, attrs);
      if (value) return value;
      if (pane instanceof Element && current === pane) break;
      current = current.parentElement;
    }
    const scope = pane instanceof Element ? pane : (composer instanceof Element ? composer.parentElement : null);
    if (!(scope instanceof Element)) return '';
    for (const attr of attrs) {
      const nodes = scope.querySelectorAll('[' + attr + ']');
      for (const node of nodes) {
        const value = idFromNode(node, [attr]);
        if (value) return value;
      }
    }
    return '';
  }

  function canonicalUuidFromText(text, label) {
    const source = String(text || '');
    const pattern = new RegExp('(?:^|\\b)' + label + '\\s*[:#]?\\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\\b|$)', 'i');
    const match = source.match(pattern);
    return match ? normalizePaneId(match[1]) : '';
  }

  function sessionIdFromVisibleMetadata(scope) {
    if (!(scope instanceof Element)) return '';
    const direct = paneIdentityFromAttrs(scope, scope, ['data-session-id','data-session-uuid']);
    if (direct) return direct;
    const metadata = scope.querySelectorAll('[title],[aria-label]');
    for (const node of metadata) {
      const values = [node.getAttribute('title'), node.getAttribute('aria-label')];
      for (const value of values) {
        const hit = canonicalUuidFromText(value, 'session');
        if (hit) return hit;
      }
    }
    const visible = canonicalUuidFromText(normalizedText(scope).slice(0, 1600), 'session');
    if (visible) return visible;
    return canonicalUuidFromText(document.title, 'session');
  }

  function paneSessionId(pane, composer) {
    const direct = paneIdentityFromAttrs(pane, composer, ['data-session-id','data-session-uuid']);
    if (direct) return direct;
    return sessionIdFromVisibleMetadata(pane instanceof Element ? pane : composer);
  }

  function paneThreadId(pane, composer) {
    const value = paneIdentityFromAttrs(pane, composer, [
      'data-above-composer-conversation-id', 'data-conversation-id', 'data-thread-id',
      'data-app-action-sidebar-thread-id', 'data-turn-thread-id',
    ]);
    if (value) return value;
    const scope = pane instanceof Element ? pane : (composer instanceof Element ? composer.parentElement : null);
    if (scope instanceof Element) {
      const links = scope.querySelectorAll('a[href]');
      for (const link of links) {
        const href = String(link.getAttribute('href') || '');
        const match = href.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
        if (match) return normalizePaneId(match[1]);
      }
    }
    return '';
  }

  function paneAgentId(pane) {
    if (!(pane instanceof Element)) return '';
    const candidates = [];
    pane.querySelectorAll('[title],[aria-label]').forEach(function(node) {
      candidates.push(node.getAttribute('title'), node.getAttribute('aria-label'));
    });
    candidates.push(normalizedText(pane).slice(0, 1200));
    for (const text of candidates) {
      const match = String(text || '').match(/\bagent-([0-9a-f]{8,36})\b/i);
      if (match) return String(match[1]).toLowerCase();
    }
    return '';
  }

  function statusBarInlineStyle() {
    return 'box-sizing:border-box;width:100%;margin:0 0 24px 0;padding:5px 9px;display:block;overflow:visible;border:1px solid color-mix(in srgb,CanvasText 12%,transparent);border-radius:11px;background:color-mix(in srgb,Canvas 90%,transparent);color:color-mix(in srgb,CanvasText 72%,transparent);box-shadow:0 1px 5px color-mix(in srgb,CanvasText 7%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);font:10px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-app-region:no-drag;cursor:pointer;position:relative;z-index:1;container-type:inline-size;user-select:text;';
  }

  function removeLegacyOrDuplicateStatusBars() {
    document.querySelectorAll('#' + STATUS_ID + ',[' + PANE_STATUS_ATTR + '=true]').forEach(function(node) {
      if (!(node instanceof Element)) return;
      if (node.getAttribute(PANE_STATUS_ATTR) !== 'true') node.remove();
    });
  }

  function statusBarForComposer(composer) {
    if (!(composer instanceof Element) || !(composer.parentElement instanceof Element)) return null;
    const parent = composer.parentElement;
    const matches = Array.from(parent.children || []).filter(function(child) {
      return child instanceof Element && child.getAttribute(PANE_STATUS_ATTR) === 'true' && child.nextSibling === composer;
    });
    const keep = matches.shift() || null;
    matches.forEach(function(extra) { extra.remove(); });
    return keep;
  }

  function ensureStatusBars() {
    removeLegacyOrDuplicateStatusBars();
    const composers = findComposerRoots();
    const active = new Set();
    const bars = [];
    composers.forEach(function(composer, index) {
      const parent = composer.parentElement;
      if (!(parent instanceof Element)) return;
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
      if (bar.parentElement !== parent || bar.nextSibling !== composer) parent.insertBefore(bar, composer);
      active.add(bar);
      bars.push(bar);
    });
    document.querySelectorAll('[' + PANE_STATUS_ATTR + '=true]').forEach(function(bar) {
      if (!active.has(bar)) bar.remove();
    });
    return bars;
  }

  function ensureStatusBar() {
    const bars = ensureStatusBars();
    return bars.length ? bars[0] : null;
  }

  function escapeStatusText(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function identityChip(label, value, title) {
    const id = normalizePaneId(value);
    if (!id) return '<span class="cas-status-identity cas-status-muted">' + label + ' --</span>';
    const safe = escapeStatusText(id);
    return '<span class="cas-status-identity" data-cas-copy-value="' + safe + '" title="Click to copy ' + escapeStatusText(title) + '">' + label + ' ' + safe + '</span>';
  }

  function statusHtmlForPane(sessionId, threadId, agentId) {
    const paneThread = normalizePaneId(threadId);
    const externalThread = normalizePaneId(state.metrics && state.metrics.externalThreadId);
    const ownsExactMetrics = !!paneThread && !!externalThread && paneThread === externalThread;
    const singleUnknown = !paneThread && findComposerRoots().length === 1;
    const metrics = ownsExactMetrics || singleUnknown
      ? statusHtml()
      : [
          '<span class="cas-status-item">ctx --</span>',
          '<span class="cas-status-item">in --</span>',
          '<span class="cas-status-item">out --</span>',
          '<span class="cas-status-item cas-status-secondary">cache --</span>',
          '<span class="cas-status-item">-- tok/s</span>',
          '<span class="cas-status-item cas-status-tertiary">total --</span>',
        ].join('');
    return '<div class="cas-status-metrics-row">' + metrics + '</div>' +
      '<div class="cas-status-identity-row">' +
        identityChip('sid', sessionId, 'session id') +
        identityChip('tid', threadId, 'thread id') +
        (agentId ? identityChip('agent', agentId, 'agent id') : '') +
      '</div>';
  }

  function bindIdentityCopy(bar) {
    if (!(bar instanceof Element)) return;
    bar.querySelectorAll('[data-cas-copy-value]').forEach(function(node) {
      node.style.cursor = 'copy';
      node.style.userSelect = 'text';
      node.addEventListener('click', async function(event) {
        event.stopPropagation();
        const value = node.getAttribute('data-cas-copy-value') || '';
        if (!value) return;
        try {
          await navigator.clipboard.writeText(value);
          node.setAttribute('data-cas-copied', 'true');
          const oldTitle = node.title;
          node.title = 'Copied: ' + value;
          setTimeout(function() { node.title = oldTitle; node.removeAttribute('data-cas-copied'); }, 1200);
        } catch {}
      });
    });
  }
// R89_COMPOSER_BLOCK_END

// R89_REFRESH_BLOCK_START
  function refreshUi() {
    ensureStyle();
    readModelLabel();
    const bars = ensureStatusBars();
    for (const bar of bars) {
      const sessionId = bar.getAttribute(PANE_SESSION_ATTR) || '';
      const threadId = bar.getAttribute(PANE_THREAD_ATTR) || '';
      const agentId = bar.getAttribute(PANE_AGENT_ATTR) || '';
      bar.innerHTML = statusHtmlForPane(sessionId, threadId, agentId);
      const metricsRow = bar.querySelector('.cas-status-metrics-row');
      if (metricsRow instanceof Element) metricsRow.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0;overflow:hidden;';
      const identityRow = bar.querySelector('.cas-status-identity-row');
      if (identityRow instanceof Element) identityRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:3px 12px;margin-top:3px;padding-top:3px;border-top:1px solid color-mix(in srgb,CanvasText 8%,transparent);font-size:9px;line-height:1.3;overflow-wrap:anywhere;word-break:break-all;user-select:text;';
      let width = 9999;
      try { width = bar.getBoundingClientRect().width; } catch {}
      bar.querySelectorAll('.cas-status-item').forEach(function(node) { node.style.whiteSpace = 'nowrap'; });
      bar.querySelectorAll('.cas-status-muted').forEach(function(node) { node.style.color = 'color-mix(in srgb,CanvasText 44%,transparent)'; });
      bar.querySelectorAll('.cas-status-spacer').forEach(function(node) { node.style.flex = '1 1 auto'; node.style.minWidth = '2px'; });
      bar.querySelectorAll('.cas-status-secondary').forEach(function(node) { node.style.display = width <= 720 ? 'none' : ''; });
      bar.querySelectorAll('.cas-status-tertiary').forEach(function(node) { node.style.display = width <= 560 ? 'none' : ''; });
      bindIdentityCopy(bar);
    }
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }
// R89_REFRESH_BLOCK_END
