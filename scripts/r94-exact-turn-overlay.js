// R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME
// R94_EXACT_TURN_CAPABILITY_RUNTIME
// Exact-only, one-timestamp-per-turn renderer.
// Native Codex conversation DOM is treated as read-only: this module never
// inserts children into a turn/action row and never writes timestamp attrs.

  const R94_OVERLAY_ID = 'cas-r94-timestamp-overlay';
  const R94_BADGE_CLASS = 'cas-r94-turn-time';
  const R94_TURN_SELECTOR = '[data-turn-key],[data-content-search-turn-key]';
  const R94_FINAL_SELECTOR = '[data-local-conversation-final-assistant],[data-content-search-assistant-turn-key],[data-message-author-role="assistant"]';
  const R94_NATIVE_TIME_SELECTOR = '[data-assistant-message-sent-time],time[datetime]';
  const R94_HISTORY_TURN_PREFIX = 'history-content:turn:';
  const R94_LOCAL_THREAD_PREFIX = 'local:';
  const R94_CACHE_LIMIT = 512;
  const R94_MAX_PENDING_SCAN_ROOTS = 64;

  function r94Decode(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    try { return decodeURIComponent(text); } catch { return text; }
  }

  function r94CurrentThreadId() {
    const pathname = String(location && location.pathname || '');
    const patterns = [
      /\/local\/([^/?#]+)/,
      /\/hotkey-window\/thread\/([^/?#]+)/,
      /\/thread\/([^/?#]+)/,
      /\/conversation\/([^/?#]+)/,
    ];
    for (const pattern of patterns) {
      const match = pattern.exec(pathname);
      if (match && match[1]) return r94Decode(match[1]);
    }
    const active = document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active="true"]');
    const raw = String(active && active.getAttribute('data-app-action-sidebar-thread-id') || '');
    if (raw.startsWith(R94_LOCAL_THREAD_PREFIX)) return r94Decode(raw.slice(R94_LOCAL_THREAD_PREFIX.length));
    return '';
  }

  function r94NormalizeTurnId(value) {
    let raw = r94Decode(value);
    if (!raw) return '';
    if (raw.startsWith(R94_HISTORY_TURN_PREFIX)) raw = raw.slice(R94_HISTORY_TURN_PREFIX.length);
    const uuid = raw.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    if (uuid) return uuid[0];
    if (/^(turn-index-|expanded-review-composer-preview|:)/i.test(raw)) return '';
    return raw;
  }

  function r94CanonicalTurn(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return null;
    const keyed = element.closest('[data-turn-key]');
    if (keyed instanceof Element) return keyed;
    const searched = element.closest('[data-content-search-turn-key]');
    return searched instanceof Element ? searched : null;
  }

  function r94IdsForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const rawTurn =
      turn.getAttribute('data-turn-key') ||
      turn.getAttribute('data-content-search-turn-key') ||
      '';
    const turnId = r94NormalizeTurnId(rawTurn);
    if (!turnId) return null;
    const threadId = r94CurrentThreadId();
    return {
      threadId: threadId || null,
      turnId,
      key: (threadId || '__unknown_thread__') + '\u0000' + turnId,
    };
  }

  function r94CleanTimeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function r94TimeRecordFromElement(node) {
    if (!(node instanceof Element)) return null;
    if (node.closest('[data-message-author-role="user"],[data-message-author="user"]')) return null;

    const candidates = [
      node.getAttribute('datetime'),
      node.getAttribute('data-timestamp'),
      node.getAttribute('title'),
      node.getAttribute('aria-label'),
      node.textContent,
    ].map(r94CleanTimeText).filter(Boolean);

    for (const value of candidates) {
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 1000000000) {
        const epoch = numeric > 10000000000 ? numeric : numeric * 1000;
        return {
          epoch,
          label: clock(epoch),
          title: fullTime(epoch) + ' · exact: Codex native sent time',
          source: 'codex-native-sent-time',
        };
      }

      const parsed = Date.parse(value);
      const containsDate = /\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}/.test(value);
      if (Number.isFinite(parsed) && containsDate) {
        return {
          epoch: parsed,
          label: clock(parsed),
          title: fullTime(parsed) + ' · exact: Codex native sent time',
          source: 'codex-native-sent-time',
        };
      }

      const timeMatch = value.match(/(?:^|\b)(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)(?:\b|$)/i);
      if (timeMatch && timeMatch[1]) {
        const label = r94CleanTimeText(timeMatch[1]).replace(/\s+(am|pm)$/i, ' $1').toUpperCase();
        return {
          epoch: null,
          label,
          title: label + ' · exact: Codex native sent time',
          source: 'codex-native-sent-time',
        };
      }
    }
    return null;
  }

  function r94NativeExactForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const nodes = Array.from(turn.querySelectorAll(R94_NATIVE_TIME_SELECTOR))
      .filter(function(node) {
        return node instanceof Element &&
          !node.closest('[data-message-author-role="user"],[data-message-author="user"]');
      });
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const record = r94TimeRecordFromElement(nodes[index]);
      if (record) return { record, sourceElement: nodes[index] };
    }
    return null;
  }

  function r94TrimCache(cache) {
    while (cache.size > R94_CACHE_LIMIT) {
      const oldest = cache.keys().next().value;
      if (oldest == null) break;
      cache.delete(oldest);
    }
  }

  function r94CreateCapability() {
    const exactByKey = new Map();

    function keyFor(threadId, turnId) {
      const t = String(threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const u = r94NormalizeTurnId(turnId);
      return u ? ((t || '__unknown_thread__') + '\\u0000' + u) : '';
    }

    function ensureRecord(ids) {
      if (!ids || !ids.key) return null;
      let current = exactByKey.get(ids.key);
      if (!current) {
        current = {
          threadId: ids.threadId || null,
          turnId: ids.turnId,
          timestamp: null,
          usage: null,
          status: null,
          startedAt: null,
          completedAt: null,
          durationMs: null,
        };
      }
      return current;
    }

    function remember(ids, record) {
      if (!ids || !ids.key || !record || !record.label) return record || null;
      const current = ensureRecord(ids) || {};
      current.timestamp = {
        epoch: Number.isFinite(record.epoch) ? record.epoch : null,
        label: String(record.label),
        title: String(record.title || record.label),
        source: String(record.source || 'exact'),
      };
      exactByKey.delete(ids.key);
      exactByKey.set(ids.key, current);
      r94TrimCache(exactByKey);
      return current.timestamp;
    }

    function rememberLifecycle(threadId, turn) {
      if (!turn || typeof turn !== 'object') return null;
      const turnId = r94NormalizeTurnId(turn.id || turn.turnId || turn.turn_id);
      if (!turnId) return null;
      const ids = {
        threadId: String(threadId || '').replace(/^local:/i, '').trim().toLowerCase() || null,
        turnId,
        key: keyFor(threadId, turnId),
      };
      if (!ids.key) return null;
      const current = ensureRecord(ids) || {};
      const started = Number(turn.startedAt ?? turn.started_at);
      const completed = Number(turn.completedAt ?? turn.completed_at);
      const duration = Number(turn.durationMs ?? turn.duration_ms);
      const nextStatus = String(turn.status || current.status || '') || null;
      const nextStartedAt = Number.isFinite(started) ? started : current.startedAt;
      const nextCompletedAt = Number.isFinite(completed) ? completed : current.completedAt;
      const nextDurationMs = Number.isFinite(duration) ? duration : current.durationMs;
      const lifecycleFingerprint = [
        nextStatus, nextStartedAt, nextCompletedAt, nextDurationMs,
      ].join('|');

      if (current.lifecycleFingerprint === lifecycleFingerprint) return current;

      current.status = nextStatus;
      current.startedAt = nextStartedAt;
      current.completedAt = nextCompletedAt;
      current.durationMs = nextDurationMs;
      current.lifecycleFingerprint = lifecycleFingerprint;
      if (Number.isFinite(completed) && completed > 0) {
        const epoch = completed > 10000000000 ? completed : completed * 1000;
        current.timestamp = {
          epoch,
          label: clock(epoch),
          title: fullTime(epoch) + ' · exact: Codex turn/completed',
          source: 'turn/completed',
        };
      }
      exactByKey.delete(ids.key);
      exactByKey.set(ids.key, current);
      r94TrimCache(exactByKey);
      try {
        window.dispatchEvent(new CustomEvent('cas-r94-turn-capability-update', {
          detail: { threadId: ids.threadId, turnId: ids.turnId, kind: 'lifecycle' },
        }));
      } catch {}
      return current;
    }

    function rememberUsage(threadId, turnId, usage) {
      const key = keyFor(threadId, turnId);
      if (!key || !usage || typeof usage !== 'object') return null;
      const ids = {
        threadId: String(threadId || '').replace(/^local:/i, '').trim().toLowerCase() || null,
        turnId: r94NormalizeTurnId(turnId),
        key,
      };
      const current = ensureRecord(ids) || {};
      const last = usage.last && typeof usage.last === 'object'
        ? usage.last
        : (usage.last_token_usage && typeof usage.last_token_usage === 'object' ? usage.last_token_usage : {});
      const total = usage.total && typeof usage.total === 'object'
        ? usage.total
        : (usage.total_token_usage && typeof usage.total_token_usage === 'object' ? usage.total_token_usage : {});
      const metric = function(object, camel, snake) {
        const value = Number(object && (object[camel] ?? object[snake]));
        return Number.isFinite(value) ? value : null;
      };
      const modelContextWindow = Number(usage.modelContextWindow ?? usage.model_context_window);
      const fingerprint = [
        metric(last,'inputTokens','input_tokens'),
        metric(last,'cachedInputTokens','cached_input_tokens'),
        metric(last,'outputTokens','output_tokens'),
        metric(last,'reasoningOutputTokens','reasoning_output_tokens'),
        metric(last,'totalTokens','total_tokens'),
        metric(total,'totalTokens','total_tokens'),
        Number.isFinite(modelContextWindow) ? modelContextWindow : null,
      ].join('|');

      // Codex rollout can emit token_count for non-turn changes while repeating
      // the previous last_token_usage. Do not convert that into a fake new turn
      // update or force an unnecessary renderer refresh.
      if (current.usageFingerprint === fingerprint) return current;

      current.usage = usage;
      current.usageFingerprint = fingerprint;
      exactByKey.delete(key);
      exactByKey.set(key, current);
      r94TrimCache(exactByKey);
      try {
        window.dispatchEvent(new CustomEvent('cas-r94-turn-capability-update', {
          detail: { threadId: ids.threadId, turnId: ids.turnId, kind: 'usage' },
        }));
      } catch {}
      return current;
    }

    function ingestNotification(value) {
      if (!value || typeof value !== 'object') return false;
      const params = value.params && typeof value.params === 'object'
        ? value.params
        : (value.payload && typeof value.payload === 'object' ? value.payload : value);
      const nestedMethod = params && typeof params === 'object'
        ? String(params.method || params.type || '')
        : '';
      const outerMethod = String(value.method || value.type || '');
      const method = outerMethod === 'event_msg' && nestedMethod ? nestedMethod : (outerMethod || nestedMethod);
      if (method === 'turn/completed' || method === 'turn_completed' || method === 'task_complete') {
        const threadId = params.threadId || params.thread_id || value.threadId || value.thread_id || r94CurrentThreadId() || null;
        const turn = params.turn && typeof params.turn === 'object'
          ? params.turn
          : {
              id: params.turnId || params.turn_id,
              status: params.status,
              startedAt: params.startedAt ?? params.started_at,
              completedAt: params.completedAt ?? params.completed_at,
              durationMs: params.durationMs ?? params.duration_ms,
            };
        return !!rememberLifecycle(threadId, turn);
      }
      if (method === 'turn/started' || method === 'turn_started' || method === 'task_started') {
        const threadId = params.threadId || params.thread_id || value.threadId || value.thread_id || r94CurrentThreadId() || null;
        const turn = params.turn && typeof params.turn === 'object'
          ? params.turn
          : {
              id: params.turnId || params.turn_id,
              status: params.status || 'inProgress',
              startedAt: params.startedAt ?? params.started_at,
            };
        return !!rememberLifecycle(threadId, turn);
      }
      if (method === 'thread/tokenUsage/updated' || method === 'thread_token_usage_updated') {
        return !!rememberUsage(
          params.threadId || params.thread_id || value.threadId || value.thread_id || r94CurrentThreadId() || null,
          params.turnId || params.turn_id,
          params.tokenUsage || params.token_usage
        );
      }
      return false;
    }

    function getForTurn(turn, ids) {
      const native = r94NativeExactForTurn(turn);
      if (native && native.record) {
        return {
          record: remember(ids, native.record),
          sourceElement: native.sourceElement,
        };
      }
      const cached = ids && exactByKey.get(ids.key);
      const record = cached && cached.timestamp ? cached.timestamp : null;
      return record ? { record, sourceElement: null } : null;
    }

    function getRecord(threadId, turnId) {
      const key = keyFor(threadId, turnId);
      return key ? (exactByKey.get(key) || null) : null;
    }

    function latestForThread(threadId) {
      const normalized = String(threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      if (!normalized) return null;
      const values = Array.from(exactByKey.values());
      for (let index = values.length - 1; index >= 0; index -= 1) {
        const record = values[index];
        const candidate = String(record && record.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
        if (candidate === normalized) return record;
      }
      return null;
    }

    function clear() {
      exactByKey.clear();
    }

    return Object.freeze({
      getForTurn,
      getRecord,
      latestForThread,
      remember,
      rememberLifecycle,
      rememberUsage,
      ingestNotification,
      clear,
      size: function() { return exactByKey.size; },
    });
  }

  function r94EnsureOverlayRoot() {
    let root = document.getElementById(R94_OVERLAY_ID);
    if (root instanceof HTMLElement) return root;
    root = document.createElement('div');
    root.id = R94_OVERLAY_ID;
    root.setAttribute('aria-hidden', 'true');
    root.style.cssText = [
      'position:fixed',
      'inset:0',
      'z-index:2147482000',
      'pointer-events:none',
      'overflow:hidden',
      'contain:layout style paint',
    ].join(';') + ';';
    (document.body || document.documentElement).appendChild(root);
    return root;
  }

  function r94CreateBadge(root, record) {
    const badge = document.createElement('div');
    badge.className = R94_BADGE_CLASS;
    badge.setAttribute('aria-hidden', 'true');
    badge.textContent = record.label;
    badge.title = record.title || record.label;
    badge.style.cssText = [
      'position:absolute',
      'left:0',
      'top:0',
      'display:block',
      'max-width:180px',
      'padding:0 2px',
      'border:0',
      'background:transparent',
      'box-shadow:none',
      'color:color-mix(in srgb,CanvasText 54%,transparent)',
      'font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'font-variant-numeric:tabular-nums',
      'white-space:nowrap',
      'pointer-events:none',
      'user-select:none',
      'opacity:.72',
      'will-change:transform',
    ].join(';') + ';';
    root.appendChild(badge);
    return badge;
  }

  function r94AnchorUsable(node) {
    if (!(node instanceof Element) || !node.isConnected) return false;
    try { return node.getClientRects().length > 0; } catch { return true; }
  }

  function r94AnchorForTurn(turn, sourceElement) {
    if (!(turn instanceof Element)) return null;
    if (sourceElement instanceof Element && sourceElement.isConnected) {
      const row = sourceElement.parentElement;
      if (r94AnchorUsable(row)) return { node: row, mode: 'action-row' };
      if (r94AnchorUsable(sourceElement)) return { node: sourceElement, mode: 'action-row' };
    }
    const final = turn.querySelector(R94_FINAL_SELECTOR);
    if (r94AnchorUsable(final)) return { node: final, mode: 'final' };
    return r94AnchorUsable(turn) ? { node: turn, mode: 'final' } : null;
  }

  function installOutputObserver() {
    if (!document.body) {
      setTimeout(installOutputObserver, 120);
      return;
    }

    const overlayRoot = r94EnsureOverlayRoot();
    const capability = r94CreateCapability();
    state.r94TimestampCapability = capability;
    window.__casR94TurnCapability = capability;

    const diagnostics = {
      exactOnly: true,
      observedTurns: 0,
      visibleTurns: 0,
      badges: 0,
      cacheSize: 0,
      lastSource: '',
      nativeTimestampSuppressed: 0,
    };
    window.__casR94TimestampDiagnostics = diagnostics;

    const observedTurns = new Set();
    const visibleTurns = new Set();
    const pendingRoots = new Set();
    const entryByTurn = new WeakMap();
    const visibleEntries = new Set();
    let disposed = false;
    let mutationObserver = null;
    let frameId = 0;
    let scanFrameId = 0;

    const resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(function() { r94SchedulePosition(); })
      : null;

    const intersectionObserver = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver(function(entries) {
          for (const entry of entries) {
            const turn = entry.target;
            if (!(turn instanceof Element)) continue;
            if (entry.isIntersecting) {
              visibleTurns.add(turn);
              if (resizeObserver) resizeObserver.observe(turn);
              r94RefreshTurn(turn);
            } else {
              visibleTurns.delete(turn);
              if (resizeObserver) resizeObserver.unobserve(turn);
              r94RemoveTurnBadge(turn);
            }
          }
          r94SyncDiagnostics();
          r94SchedulePosition();
        }, { root: null, rootMargin: '120px 0px 120px 0px', threshold: 0 })
      : null;

    function r94SyncDiagnostics() {
      diagnostics.observedTurns = observedTurns.size;
      diagnostics.visibleTurns = visibleTurns.size;
      diagnostics.badges = visibleEntries.size;
      diagnostics.cacheSize = capability.size();
    }

    function r94RemoveTurnBadge(turn) {
      const entry = entryByTurn.get(turn);
      if (!entry) return;
      visibleEntries.delete(entry);
      if (entry.badge && entry.badge.isConnected) entry.badge.remove();
      entry.badge = null;
    }

    function r94EnsureTurnBadge(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      const ids = r94IdsForTurn(turn);
      if (!ids) return;
      const exact = capability.getForTurn(turn, ids);
      if (!exact || !exact.record || !exact.record.label) {
        r94RemoveTurnBadge(turn);
        return;
      }

      if (exact.sourceElement instanceof Element && r94AnchorUsable(exact.sourceElement)) {
        // Codex already renders this exact timestamp. Keep native UI as the
        // single source of truth and suppress our fallback overlay duplicate.
        r94RemoveTurnBadge(turn);
        diagnostics.nativeTimestampSuppressed = (diagnostics.nativeTimestampSuppressed || 0) + 1;
        diagnostics.lastSource = exact.record.source || '';
        r94SyncDiagnostics();
        return;
      }

      let entry = entryByTurn.get(turn);
      const anchor = r94AnchorForTurn(turn, null);
      if (!anchor || !(anchor.node instanceof Element)) return;

      if (!entry) {
        entry = {
          turn,
          ids,
          record: exact.record,
          anchor: anchor.node,
          mode: anchor.mode,
          badge: null,
        };
        entryByTurn.set(turn, entry);
      } else {
        entry.ids = ids;
        entry.record = exact.record;
        entry.anchor = anchor.node;
        entry.mode = anchor.mode;
      }

      if (!entry.badge || !entry.badge.isConnected) {
        entry.badge = r94CreateBadge(overlayRoot, exact.record);
      } else if (entry.badge.textContent !== exact.record.label) {
        entry.badge.textContent = exact.record.label;
        entry.badge.title = exact.record.title || exact.record.label;
      }

      visibleEntries.add(entry);
      diagnostics.lastSource = exact.record.source || '';
      r94SyncDiagnostics();
    }

    function r94RefreshTurn(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (intersectionObserver && !visibleTurns.has(turn)) return;
      r94EnsureTurnBadge(turn);
      r94SchedulePosition();
    }

    function r94PositionVisible() {
      frameId = 0;
      if (disposed || document.visibilityState === 'hidden') return;

      const writes = [];
      for (const entry of Array.from(visibleEntries)) {
        if (!entry.turn || !entry.turn.isConnected || !entry.badge || !entry.badge.isConnected) {
          visibleEntries.delete(entry);
          continue;
        }
        const anchor = entry.anchor instanceof Element && entry.anchor.isConnected
          ? entry.anchor
          : entry.turn;
        let rect;
        try { rect = anchor.getBoundingClientRect(); } catch { rect = null; }
        if (!rect || rect.width <= 0 || rect.height <= 0 || rect.bottom < -120 || rect.top > innerHeight + 120) {
          entry.badge.style.display = 'none';
          continue;
        }

        const x = Math.max(12, Math.min(innerWidth - 6, rect.right - 3));
        const y = entry.mode === 'action-row'
          ? Math.max(12, Math.min(innerHeight - 6, rect.top - 2))
          : Math.max(12, Math.min(innerHeight - 6, rect.bottom - 2));
        writes.push({ entry, x, y });
      }

      for (const item of writes) {
        const badge = item.entry.badge;
        badge.style.display = 'block';
        badge.style.transform = 'translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,-100%)';
      }
      r94SyncDiagnostics();
    }

    function r94SchedulePosition() {
      if (disposed || frameId || document.visibilityState === 'hidden') return;
      frameId = requestAnimationFrame(r94PositionVisible);
    }

    function r94ObserveTurn(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (turn.closest('#' + R94_OVERLAY_ID)) return;
      if (insideComposer(turn) || insideOwnUi(turn)) return;
      const ids = r94IdsForTurn(turn);
      if (!ids) return;

      if (!observedTurns.has(turn)) {
        observedTurns.add(turn);
        if (intersectionObserver) {
          intersectionObserver.observe(turn);
        } else {
          visibleTurns.add(turn);
          r94RefreshTurn(turn);
        }
      } else if (!intersectionObserver || visibleTurns.has(turn)) {
        r94RefreshTurn(turn);
      }
    }

    function r94ScanRoot(root) {
      if (disposed || !root || document.visibilityState === 'hidden') return;
      const element = root instanceof Element ? root : root.parentElement;
      if (!(element instanceof Element)) return;

      const seen = new Set();
      const add = function(candidate) {
        const turn = r94CanonicalTurn(candidate);
        if (!(turn instanceof Element) || seen.has(turn)) return;
        seen.add(turn);
        r94ObserveTurn(turn);
      };

      if (element.matches(R94_TURN_SELECTOR)) add(element);
      const closest = r94CanonicalTurn(element);
      if (closest) add(closest);
      element.querySelectorAll(R94_TURN_SELECTOR).forEach(add);
    }

    function r94PruneDisconnected() {
      for (const turn of Array.from(observedTurns)) {
        if (turn.isConnected) continue;
        observedTurns.delete(turn);
        visibleTurns.delete(turn);
        if (intersectionObserver) intersectionObserver.unobserve(turn);
        if (resizeObserver) resizeObserver.unobserve(turn);
        r94RemoveTurnBadge(turn);
      }
      r94SyncDiagnostics();
    }

    function r94FlushScans() {
      scanFrameId = 0;
      r94PruneDisconnected();
      const roots = Array.from(pendingRoots);
      pendingRoots.clear();
      for (const root of roots) {
        if (root && root.isConnected) r94ScanRoot(root);
      }
    }

    function r94ScheduleScan(root) {
      if (disposed || !root || document.visibilityState === 'hidden') return;
      const element = root instanceof Element ? root : root.parentElement;
      if (!(element instanceof Element) || element.closest('#' + R94_OVERLAY_ID)) return;

      for (const existing of Array.from(pendingRoots)) {
        if (existing === element || existing.contains(element)) return;
        if (element.contains(existing)) pendingRoots.delete(existing);
      }
      pendingRoots.add(element);
      if (pendingRoots.size > R94_MAX_PENDING_SCAN_ROOTS) {
        pendingRoots.clear();
        pendingRoots.add(document.documentElement);
      }
      if (!scanFrameId) scanFrameId = requestAnimationFrame(r94FlushScans);
    }

    function r94HandleMutations(records) {
      if (disposed || document.visibilityState === 'hidden') return;
      let removed = false;
      for (const record of records) {
        if (record.type !== 'childList') continue;
        const mutationTarget = record.target instanceof Element
          ? record.target
          : record.target && record.target.parentElement;
        if (mutationTarget instanceof Element &&
            (mutationTarget.id === R94_OVERLAY_ID || mutationTarget.closest('#' + R94_OVERLAY_ID))) {
          continue;
        }
        if (record.removedNodes && record.removedNodes.length) removed = true;
        for (const added of record.addedNodes || []) {
          const element = added instanceof Element ? added : added && added.parentElement;
          if (!(element instanceof Element) || element.closest('#' + R94_OVERLAY_ID)) continue;
          const owner = r94CanonicalTurn(element);
          if (owner) {
            r94ScheduleScan(owner);
            if (!intersectionObserver || visibleTurns.has(owner)) r94RefreshTurn(owner);
            continue;
          }
          if (element.matches(R94_TURN_SELECTOR) || element.querySelector(R94_TURN_SELECTOR)) {
            r94ScheduleScan(element);
          }
        }
      }
      if (removed) r94ScheduleScan(document.documentElement);
    }

    function r94StartMutationObservation() {
      if (mutationObserver || disposed || document.visibilityState === 'hidden') return;
      mutationObserver = new MutationObserver(r94HandleMutations);
      mutationObserver.observe(document.documentElement, { childList: true, subtree: true });
    }

    function r94StopMutationObservation() {
      if (!mutationObserver) return;
      mutationObserver.disconnect();
      mutationObserver = null;
    }

    function r94ClearVisibleBadges() {
      for (const entry of Array.from(visibleEntries)) {
        if (entry.badge && entry.badge.isConnected) entry.badge.remove();
        entry.badge = null;
      }
      visibleEntries.clear();
      visibleTurns.clear();
      r94SyncDiagnostics();
    }

    function r94HandleCapabilityUpdate(event) {
      const detail = event && event.detail && typeof event.detail === 'object' ? event.detail : null;
      const turnId = r94NormalizeTurnId(detail && detail.turnId);
      if (!turnId) return;
      const threadId = String(detail && detail.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      for (const turn of Array.from(visibleTurns)) {
        const ids = r94IdsForTurn(turn);
        if (!ids || ids.turnId !== turnId) continue;
        const idsThread = String(ids.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
        if (threadId && idsThread && threadId !== idsThread) continue;
        r94RefreshTurn(turn);
      }
    }

    function r94HandleVisibility() {
      if (document.visibilityState === 'hidden') {
        overlayRoot.hidden = true;
        r94StopMutationObservation();
        if (intersectionObserver) intersectionObserver.disconnect();
        if (resizeObserver) resizeObserver.disconnect();
        if (scanFrameId) cancelAnimationFrame(scanFrameId);
        scanFrameId = 0;
        pendingRoots.clear();
        r94ClearVisibleBadges();
        return;
      }

      overlayRoot.hidden = false;
      r94StartMutationObservation();
      if (intersectionObserver) {
        for (const turn of Array.from(observedTurns)) {
          if (turn.isConnected) intersectionObserver.observe(turn);
        }
      }
      r94ScheduleScan(document.documentElement);
      r94SchedulePosition();
    }

    function r94Cleanup() {
      if (disposed) return;
      disposed = true;
      r94StopMutationObservation();
      if (intersectionObserver) intersectionObserver.disconnect();
      if (resizeObserver) resizeObserver.disconnect();
      if (frameId) cancelAnimationFrame(frameId);
      if (scanFrameId) cancelAnimationFrame(scanFrameId);
      window.removeEventListener('resize', r94SchedulePosition);
      window.removeEventListener('scroll', r94SchedulePosition, true);
      document.removeEventListener('visibilitychange', r94HandleVisibility);
      window.removeEventListener('cas-r94-turn-capability-update', r94HandleCapabilityUpdate);
      pendingRoots.clear();
      observedTurns.clear();
      visibleTurns.clear();
      visibleEntries.clear();
      capability.clear();
      if (overlayRoot.isConnected) overlayRoot.remove();
      if (window.__casR94TimestampDiagnostics === diagnostics) delete window.__casR94TimestampDiagnostics;
      if (window.__casR94TurnCapability === capability) delete window.__casR94TurnCapability;
    }

    // Compatibility no-op: r75's old poll hook is removed by the r94 owner-layer
    // patch. Keeping this symbol prevents legacy generated checks from inventing
    // a fallback sweep; it intentionally does no timestamp work.
    function sweepOutputSegments() {}

    window.addEventListener('resize', r94SchedulePosition, { passive: true });
    window.addEventListener('scroll', r94SchedulePosition, { passive: true, capture: true });
    document.addEventListener('visibilitychange', r94HandleVisibility);
    window.addEventListener('cas-r94-turn-capability-update', r94HandleCapabilityUpdate);

    r94StartMutationObservation();
    r94ScanRoot(document.documentElement);
    r94SchedulePosition();

    // r74 cleanup already calls state.observer.disconnect(). Expose one composed
    // controller so cleanup tears down Mutation/Intersection/Resize observers,
    // listeners, cache and the Transfer-owned overlay root in one operation.
    state.observer = { disconnect: r94Cleanup };
  }
