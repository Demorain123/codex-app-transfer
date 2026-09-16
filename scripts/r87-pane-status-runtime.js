  function normalizeUiThreadId(value) {
    return String(value || '').replace(/^local:/i, '').trim().toLowerCase();
  }

  function escapeStatusText(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function shortIdentity(value) {
    const normalized = normalizeUiThreadId(value);
    return normalized ? normalized.slice(0, 8) : '--';
  }

  function ensurePaneStatusStyle() {
    const id = 'cas-r87-pane-status-style';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = [
      '[data-cas-statusbar-host="true"]{position:relative!important;display:block!important;box-sizing:border-box!important;min-width:0!important;min-height:0!important;flex:0 0 auto!important;z-index:3!important;margin:0 0 6px 0!important;padding:0!important;pointer-events:auto!important;}',
      '[data-cas-live-statusbar="true"]{position:relative!important;inset:auto!important;box-sizing:border-box!important;width:100%!important;max-width:100%!important;margin:0!important;padding:4px 9px!important;display:flex!important;align-items:center!important;gap:8px!important;overflow:hidden!important;border:1px solid color-mix(in srgb,CanvasText 12%,transparent)!important;border-radius:11px!important;background:color-mix(in srgb,Canvas 94%,transparent)!important;color:color-mix(in srgb,CanvasText 72%,transparent)!important;box-shadow:0 1px 5px color-mix(in srgb,CanvasText 7%,transparent)!important;backdrop-filter:blur(10px)!important;-webkit-backdrop-filter:blur(10px)!important;font:10px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace!important;-webkit-app-region:no-drag!important;cursor:pointer!important;container-type:inline-size!important;}',
      '[data-cas-live-statusbar="true"] .cas-status-item{white-space:nowrap;min-width:0;}',
      '[data-cas-live-statusbar="true"] .cas-status-identity{user-select:text;cursor:text;}',
      '[data-cas-live-statusbar="true"] .cas-status-muted{color:color-mix(in srgb,CanvasText 44%,transparent);}',
      '[data-cas-live-statusbar="true"] .cas-status-spacer{flex:1 1 auto;min-width:2px;}',
      '@container (max-width:720px){[data-cas-live-statusbar="true"] .cas-status-secondary{display:none!important;}}',
      '@container (max-width:560px){[data-cas-live-statusbar="true"] .cas-status-tertiary{display:none!important;}}',
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  const COMPOSER_SELECTOR = '[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"],.composer-surface-chrome,form';
  const EDITABLE_SELECTOR = '.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea';
  const THREAD_ID_SELECTOR = '[data-above-composer-conversation-id],[data-conversation-id],[data-thread-id]';

  function findComposerRoots() {
    const roots = [];
    const add = function(candidate) {
      if (!(candidate instanceof Element) || !isVisible(candidate) || insideOwnUi(candidate)) return;
      const editable = candidate.matches(EDITABLE_SELECTOR) ? candidate : candidate.querySelector(EDITABLE_SELECTOR);
      if (!(editable instanceof Element) || !isVisible(editable)) return;
      let root = candidate.matches(COMPOSER_SELECTOR)
        ? candidate
        : (editable.closest('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"],.composer-surface-chrome,form') || editable.parentElement);
      if (!(root instanceof Element) || !isVisible(root)) return;
      if (roots.some(function(existing) { return existing === root || existing.contains(root); })) return;
      for (let index = roots.length - 1; index >= 0; index -= 1) {
        if (root.contains(roots[index])) roots.splice(index, 1);
      }
      roots.push(root);
    };
    document.querySelectorAll('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"]').forEach(add);
    document.querySelectorAll(EDITABLE_SELECTOR).forEach(add);
    return roots;
  }

  // Keep the historical single-composer helper as a compatibility facade for
  // timestamp/live-generation code while multi-pane callers use the full list.
  function findComposerRoot() {
    const roots = findComposerRoots();
    return roots.length ? roots[0] : null;
  }

  function threadIdFromElement(node) {
    if (!(node instanceof Element)) return '';
    for (const attr of ['data-above-composer-conversation-id','data-conversation-id','data-thread-id']) {
      const value = normalizeUiThreadId(node.getAttribute(attr));
      if (value) return value;
    }
    return '';
  }

  function threadIdForComposer(composer) {
    if (!(composer instanceof Element)) return '';
    const roots = findComposerRoots();
    let current = composer;
    for (let depth = 0; current instanceof Element && current !== document.body && depth < 9; depth += 1) {
      const direct = threadIdFromElement(current);
      if (direct) return direct;
      const ids = new Set();
      current.querySelectorAll(THREAD_ID_SELECTOR).forEach(function(node) {
        const value = threadIdFromElement(node);
        if (value) ids.add(value);
      });
      if (ids.size === 1) return Array.from(ids)[0];
      const containedComposers = roots.filter(function(root) { return current === root || current.contains(root); });
      if (containedComposers.length > 1) break;
      current = current.parentElement;
    }
    if (roots.length === 1) return normalizeUiThreadId(state.metrics && state.metrics.externalThreadId);
    return '';
  }

  function externalEntryForThread(threadId) {
    const normalized = normalizeUiThreadId(threadId);
    if (!normalized || !(state.externalUsageByThread instanceof Map)) return null;
    return state.externalUsageByThread.get(normalized) || null;
  }

  function metricsFromExternalEntry(entry) {
    if (!entry || !entry.info || typeof entry.info !== 'object') return null;
    const info = entry.info;
    const last = info.last_token_usage || info.lastTokenUsage || info.usage || null;
    const total = info.total_token_usage || info.totalTokenUsage || null;
    if (!last || typeof last !== 'object') return null;
    const input = numberAt(last, [['input_tokens'], ['inputTokens'], ['prompt_tokens'], ['promptTokens']]);
    const cached = numberAt(last, [['cached_input_tokens'], ['cachedInputTokens'], ['cached_tokens'], ['cachedTokens']]);
    const output = numberAt(last, [['output_tokens'], ['outputTokens'], ['completion_tokens'], ['completionTokens']]);
    const reasoning = numberAt(last, [['reasoning_output_tokens'], ['reasoningTokens']]);
    const contextWindow = numberAt(info, [['model_context_window'], ['modelContextWindow']]);
    const sessionTotal = total ? numberAt(total, [['total_tokens'], ['totalTokens']]) : null;
    const contextPercent = Number.isFinite(input) && Number.isFinite(contextWindow) && contextWindow > 0
      ? Math.max(0, Math.min(100, (input / contextWindow) * 100))
      : null;
    const cacheHitPercent = Number.isFinite(cached) && Number.isFinite(input) && input > 0
      ? Math.max(0, Math.min(100, (cached / input) * 100))
      : null;
    return {
      seen: true,
      contextTokens: input,
      contextWindow,
      contextPercent,
      inputTokens: input,
      cachedInputTokens: cached,
      outputTokens: output,
      reasoningTokens: reasoning,
      sessionTotalTokens: sessionTotal,
      cacheHitPercent,
      outputSpeed: Number.isFinite(entry.outputSpeed) ? entry.outputSpeed : null,
      nativeSpeed: null,
      nativeCacheHit: null,
      nativeSessionTotal: null,
      model: typeof entry.model === 'string' ? entry.model : null,
      externalThreadId: typeof entry.threadId === 'string' ? entry.threadId : null,
      externalUpdatedAt: Number(entry.updatedAt) || 0,
    };
  }

  function identityForComposer(composer) {
    const threadId = threadIdForComposer(composer);
    const entry = externalEntryForThread(threadId);
    const sessionId = normalizeUiThreadId(entry && entry.sessionId);
    const parentThreadId = normalizeUiThreadId(entry && entry.parentThreadId);
    return {
      threadId,
      sessionId,
      parentThreadId,
      exactSession: !!sessionId,
    };
  }

  function metricsForComposer(composer) {
    const identity = identityForComposer(composer);
    const entry = externalEntryForThread(identity.threadId);
    const external = metricsFromExternalEntry(entry);
    if (external) return { metrics: external, identity };
    return { metrics: state.metrics, identity };
  }

  function statusHostForComposer(composer) {
    const hosts = Array.from(document.querySelectorAll('[data-cas-statusbar-host="true"]'));
    return hosts.find(function(host) { return host.__casComposer === composer; }) || null;
  }

  function placeStatusHost(host, composer) {
    if (!(host instanceof Element) || !(composer instanceof Element)) return;
    const composerRect = composer.getBoundingClientRect();
    let anchor = composer;
    for (let depth = 0; depth < 5; depth += 1) {
      const parent = anchor.parentElement;
      if (!(parent instanceof Element) || parent === document.body || insideOwnUi(parent)) break;
      if (host.parentElement !== parent || host.nextSibling !== anchor) parent.insertBefore(host, anchor);
      const parentRect = parent.getBoundingClientRect();
      host.style.width = Math.max(140, Math.round(composerRect.width)) + 'px';
      host.style.maxWidth = '100%';
      host.style.marginLeft = Math.max(0, Math.round(composerRect.left - parentRect.left)) + 'px';
      host.setAttribute('data-cas-status-placement-depth', String(depth));
      const hostRect = host.getBoundingClientRect();
      const anchorRect = anchor.getBoundingClientRect();
      if (hostRect.height > 0 && anchorRect.height > 0 && hostRect.bottom <= anchorRect.top + 1) return;
      anchor = parent;
    }
  }

  function ensureStatusBars() {
    ensurePaneStatusStyle();
    const composers = findComposerRoots();
    const liveHosts = new Set();
    composers.forEach(function(composer, index) {
      if (!(composer instanceof Element) || !composer.parentElement) return;
      let host = statusHostForComposer(composer);
      if (!host) {
        host = document.createElement('div');
        host.setAttribute('data-cas-statusbar-host', 'true');
        host.__casComposer = composer;
        const bar = document.createElement('div');
        bar.setAttribute('data-cas-live-statusbar', 'true');
        bar.title = 'Click for live telemetry charts';
        bar.addEventListener('click', function(event) {
          event.stopPropagation();
          toggleAnalytics(bar);
        });
        host.appendChild(bar);
      }
      host.__casComposer = composer;
      const bar = host.querySelector('[data-cas-live-statusbar="true"]');
      if (!(bar instanceof Element)) return;
      if (index === 0) bar.id = STATUS_ID;
      else if (bar.id === STATUS_ID) bar.removeAttribute('id');
      const resolved = metricsForComposer(composer);
      const identity = resolved.identity;
      if (identity.threadId) bar.setAttribute('data-cas-thread-id', identity.threadId);
      else bar.removeAttribute('data-cas-thread-id');
      if (identity.sessionId) bar.setAttribute('data-cas-session-id', identity.sessionId);
      else bar.removeAttribute('data-cas-session-id');
      bar.innerHTML = statusHtml(resolved.metrics, identity);
      placeStatusHost(host, composer);
      liveHosts.add(host);
    });
    document.querySelectorAll('[data-cas-statusbar-host="true"]').forEach(function(host) {
      if (!liveHosts.has(host)) host.remove();
    });
    return Array.from(liveHosts).map(function(host) { return host.querySelector('[data-cas-live-statusbar="true"]'); }).filter(Boolean);
  }

  function effectiveSpeedFor(m) {
    return Number.isFinite(m && m.nativeSpeed) ? m.nativeSpeed : (m && m.outputSpeed);
  }
  function effectiveCacheHitFor(m) {
    return Number.isFinite(m && m.nativeCacheHit) ? m.nativeCacheHit : (m && m.cacheHitPercent);
  }
  function effectiveSessionTotalFor(m) {
    return Number.isFinite(m && m.nativeSessionTotal) ? m.nativeSessionTotal : (m && m.sessionTotalTokens);
  }
  function effectiveSpeed() { return effectiveSpeedFor(state.metrics); }
  function effectiveCacheHit() { return effectiveCacheHitFor(state.metrics); }
  function effectiveSessionTotal() { return effectiveSessionTotalFor(state.metrics); }

  function statusHtml(m, identity) {
    m = m || state.metrics;
    identity = identity || {};
    const context = Number.isFinite(m.contextPercent) ? ('ctx ' + m.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = 'in ' + shortNumber(m.inputTokens);
    const output = 'out ' + shortNumber(m.outputTokens);
    const cacheValue = effectiveCacheHitFor(m);
    const cache = Number.isFinite(cacheValue) ? ('cache ' + cacheValue.toFixed(1) + '%') : 'cache --';
    const speedValue = effectiveSpeedFor(m);
    const speed = Number.isFinite(speedValue) ? (speedValue.toFixed(1) + ' tok/s') : '-- tok/s';
    const session = 'total ' + shortNumber(effectiveSessionTotalFor(m));
    const model = m.model || '';
    const sid = normalizeUiThreadId(identity.sessionId);
    const tid = normalizeUiThreadId(identity.threadId);
    const identityHtml = [];
    if (sid) {
      identityHtml.push('<span class="cas-status-item cas-status-identity cas-status-secondary" title="session ' + escapeStatusText(sid) + '">sid ' + escapeStatusText(shortIdentity(sid)) + '</span>');
    } else if (tid) {
      identityHtml.push('<span class="cas-status-item cas-status-muted cas-status-identity cas-status-secondary" title="session id unavailable; thread ' + escapeStatusText(tid) + '">sid ?</span>');
    }
    if (tid && (!sid || tid !== sid)) {
      identityHtml.push('<span class="cas-status-item cas-status-identity cas-status-tertiary" title="thread ' + escapeStatusText(tid) + '">tid ' + escapeStatusText(shortIdentity(tid)) + '</span>');
    }
    return [
      '<span class="cas-status-item">' + context + '</span>',
      '<span class="cas-status-item">' + input + '</span>',
      '<span class="cas-status-item">' + output + '</span>',
      '<span class="cas-status-item cas-status-secondary">' + cache + '</span>',
      '<span class="cas-status-item">' + speed + '</span>',
      '<span class="cas-status-item cas-status-tertiary">' + session + '</span>',
      identityHtml.join(''),
      '<span class="cas-status-spacer"></span>',
      '<span class="cas-status-item cas-status-muted cas-status-secondary">' + escapeStatusText(model) + '</span>',
    ].join('');
  }
