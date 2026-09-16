// R88_PANE_RUNTIME_JS
// This file contains syntax-checkable JavaScript fragments injected into the
// existing r74 telemetry runtime by the r88 generated r75 overlay. It performs
// no network calls and never writes session/auth/provider data.

// R88_COMPOSER_BLOCK_START
  function findComposerRoots() {
    const roots = [];
    const seen = new Set();
    const add = function(node) {
      if (!(node instanceof Element) || seen.has(node) || !isVisible(node)) return;
      seen.add(node);
      roots.push(node);
    };
    document.querySelectorAll('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"]').forEach(add);
    document.querySelectorAll('.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea').forEach(function(editable) {
      if (!(editable instanceof Element) || !isVisible(editable)) return;
      if (roots.some(function(root) { return root.contains(editable); })) return;
      add(editable.closest('[data-testid*="composer"],.composer-surface-chrome,form') || editable.parentElement);
    });
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
    for (let depth = 0; depth < 10; depth += 1) {
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

  function normalizePaneThreadId(value) {
    return String(value || '').replace(/^local:/i, '').trim().toLowerCase();
  }

  function threadIdFromNode(node) {
    if (!(node instanceof Element)) return '';
    const attrs = [
      'data-above-composer-conversation-id', 'data-conversation-id', 'data-thread-id',
      'data-session-id', 'data-app-action-sidebar-thread-id', 'data-turn-thread-id',
    ];
    for (const attr of attrs) {
      const value = normalizePaneThreadId(node.getAttribute(attr));
      if (value) return value;
    }
    return '';
  }

  function paneThreadId(pane, composer) {
    let current = composer instanceof Element ? composer : null;
    for (let depth = 0; depth < 12 && current; depth += 1) {
      const value = threadIdFromNode(current);
      if (value) return value;
      if (pane instanceof Element && current === pane) break;
      current = current.parentElement;
    }
    const scope = pane instanceof Element ? pane : (composer instanceof Element ? composer.parentElement : null);
    if (scope instanceof Element) {
      const selectors = [
        '[data-above-composer-conversation-id]', '[data-conversation-id]', '[data-thread-id]',
        '[data-session-id]', '[data-app-action-sidebar-thread-id]', '[data-turn-thread-id]',
      ];
      for (const selector of selectors) {
        const nodes = scope.querySelectorAll(selector);
        for (const node of nodes) {
          const value = threadIdFromNode(node);
          if (value) return value;
        }
      }
      const links = scope.querySelectorAll('a[href]');
      for (const link of links) {
        const href = String(link.getAttribute('href') || '');
        const match = href.match(/([0-9a-f]{8}-[0-9a-f-]{20,})/i);
        if (match) return normalizePaneThreadId(match[1]);
      }
    }
    return '';
  }

  function paneAgentId(pane) {
    if (!(pane instanceof Element)) return '';
    const text = normalizedText(pane).slice(0, 700);
    const match = text.match(/\bagent-([0-9a-f]{8,36})\b/i);
    return match ? String(match[1]).toLowerCase() : '';
  }

  function shortPaneThreadId(value) {
    const id = normalizePaneThreadId(value);
    if (!id) return '--';
    return id.length > 12 ? id.slice(0, 8) + '…' : id;
  }

  function statusBarInlineStyle() {
    return 'box-sizing:border-box;width:100%;margin:0 0 22px 0;padding:4px 9px;display:flex;align-items:center;gap:8px;overflow:hidden;border:1px solid color-mix(in srgb,CanvasText 12%,transparent);border-radius:11px;background:color-mix(in srgb,Canvas 90%,transparent);color:color-mix(in srgb,CanvasText 72%,transparent);box-shadow:0 1px 5px color-mix(in srgb,CanvasText 7%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);font:10px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-app-region:no-drag;cursor:pointer;position:relative;z-index:1;container-type:inline-size;';
  }

  function ensureStatusBars() {
    const composers = findComposerRoots();
    const active = new Set();
    const bars = [];
    composers.forEach(function(composer, index) {
      const parent = composer.parentElement;
      if (!(parent instanceof Element)) return;
      const pane = paneForComposer(composer);
      let threadId = paneThreadId(pane, composer);
      if (!threadId && index === 0) threadId = normalizePaneThreadId(state.metrics && state.metrics.externalThreadId);
      const agentId = paneAgentId(pane);
      let bar = null;
      for (const child of Array.from(parent.children || [])) {
        if (child instanceof Element && child.getAttribute(PANE_STATUS_ATTR) === 'true') {
          bar = child;
          break;
        }
      }
      if (!bar) {
        bar = document.createElement('div');
        bar.setAttribute(PANE_STATUS_ATTR, 'true');
        bar.title = 'Click for live telemetry charts';
        bar.addEventListener('click', function(event) {
          event.stopPropagation();
          const paneId = normalizePaneThreadId(bar.getAttribute(PANE_THREAD_ATTR));
          const externalId = normalizePaneThreadId(state.metrics && state.metrics.externalThreadId);
          if (paneId && externalId && paneId !== externalId) return;
          toggleAnalytics(bar);
        });
      }
      if (index === 0) {
        bar.id = STATUS_ID;
      } else if (bar.id === STATUS_ID) {
        bar.removeAttribute('id');
      }
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

  function statusHtmlForPane(threadId, agentId) {
    const paneId = normalizePaneThreadId(threadId);
    const externalId = normalizePaneThreadId(state.metrics && state.metrics.externalThreadId);
    const ownsExactMetrics = !!paneId && !!externalId && paneId === externalId;
    const singleUnknown = !paneId && findComposerRoots().length === 1;
    const sidTitle = paneId ? ('session/thread id: ' + paneId) : 'session/thread id unavailable';
    const sid = '<span class="cas-status-item cas-status-muted" title="' + escapeStatusText(sidTitle) + '">sid ' + shortPaneThreadId(paneId) + '</span>';
    const agent = agentId ? '<span class="cas-status-item cas-status-muted cas-status-secondary" title="agent id: ' + escapeStatusText(agentId) + '">agent ' + escapeStatusText(agentId) + '</span>' : '';
    if (ownsExactMetrics || singleUnknown) return statusHtml() + sid + agent;
    return [
      '<span class="cas-status-item">ctx --</span>',
      '<span class="cas-status-item">in --</span>',
      '<span class="cas-status-item">out --</span>',
      '<span class="cas-status-item cas-status-secondary">cache --</span>',
      '<span class="cas-status-item">-- tok/s</span>',
      '<span class="cas-status-item cas-status-tertiary">total --</span>',
      '<span class="cas-status-spacer"></span>',
      sid,
      agent,
    ].join('');
  }
// R88_COMPOSER_BLOCK_END

// R88_REFRESH_BLOCK_START
  function refreshUi() {
    ensureStyle();
    readModelLabel();
    const bars = ensureStatusBars();
    for (const bar of bars) {
      const threadId = bar.getAttribute(PANE_THREAD_ATTR) || '';
      const agentId = bar.getAttribute(PANE_AGENT_ATTR) || '';
      bar.innerHTML = statusHtmlForPane(threadId, agentId);
      let width = 9999;
      try { width = bar.getBoundingClientRect().width; } catch {}
      bar.querySelectorAll('.cas-status-item').forEach(function(node) { node.style.whiteSpace = 'nowrap'; });
      bar.querySelectorAll('.cas-status-muted').forEach(function(node) { node.style.color = 'color-mix(in srgb,CanvasText 44%,transparent)'; });
      bar.querySelectorAll('.cas-status-spacer').forEach(function(node) { node.style.flex = '1 1 auto'; node.style.minWidth = '2px'; });
      bar.querySelectorAll('.cas-status-secondary').forEach(function(node) { node.style.display = width <= 720 ? 'none' : ''; });
      bar.querySelectorAll('.cas-status-tertiary').forEach(function(node) { node.style.display = width <= 560 ? 'none' : ''; });
    }
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }
// R88_REFRESH_BLOCK_END
