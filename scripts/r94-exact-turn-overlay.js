// R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME
// R94_EXACT_TURN_CAPABILITY_RUNTIME
// Hybrid timestamp renderer: keep Codex/native exact sent-time ownership for
// prompts/final answers, and add host first-observed ≈ timestamps to live
// assistant/progress/tool output blocks. Native Codex conversation DOM stays
// read-only; every Transfer timestamp lives in the overlay root.

  const R94_OVERLAY_ID = 'cas-r94-timestamp-overlay';
  const R94_BADGE_CLASS = 'cas-r94-turn-time';
  const R94_TURN_SELECTOR = '[data-turn-key],[data-content-search-turn-key],[data-content-search-assistant-turn-key],[data-chatgpt-conversation-turn="true"]';
  const R94_FINAL_SELECTOR = '[data-local-conversation-final-assistant],[data-content-search-assistant-turn-key],[data-message-author-role="assistant"]';
  const R94_NATIVE_TIME_SELECTOR = '[data-assistant-message-sent-time],time[datetime]';
  const R94_HISTORY_TURN_PREFIX = 'history-content:turn:';
  const R94_LOCAL_THREAD_PREFIX = 'local:';
  const R94_CACHE_LIMIT = 512;
  const R94_MAX_PENDING_SCAN_ROOTS = 64;
  const R94_TIMELINE_RAIL_ID = 'cas-r94-timeline-rail';
  const R94_TIMELINE_MARKER_CLASS = 'cas-r94-timeline-marker';
  const R94_TIMELINE_LIMIT = 256;
  const r94TurnThreadIdCache = new WeakMap();

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

  // R94_MULTI_PANE_THREAD_OWNERSHIP_RUNTIME
  // Split-view and sub-agent panes are independent Codex threads. Never pair a
  // turn with location.pathname just because the root route still points at the
  // parent thread. Reuse the pane runtime's already-resolved thread identity.
  function r94KnownPaneThreadIds() {
    const ids = [];
    const seen = new Set();
    document.querySelectorAll('[data-cas-pane-statusbar="true"][data-cas-pane-thread-id],[data-cas-status-inside-composer="true"][data-cas-pane-thread-id]').forEach(function(bar) {
      const id = String(bar.getAttribute('data-cas-pane-thread-id') || '').replace(/^local:/i, '').trim().toLowerCase();
      if (!id || seen.has(id)) return;
      seen.add(id);
      ids.push(id);
    });
    return ids;
  }

  function r94ThreadIdForNode(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return '';

    const directAttrs = [
      'data-turn-thread-id',
      'data-thread-id',
      'data-conversation-id',
      'data-above-composer-conversation-id'
    ];
    let current = element;
    for (let depth = 0; depth < 12 && current instanceof Element; depth += 1) {
      for (const attr of directAttrs) {
        const value = String(current.getAttribute(attr) || '').replace(/^local:/i, '').trim().toLowerCase();
        if (value) return value;
      }
      current = current.parentElement;
    }

    try {
      if (typeof paneForNode === 'function') {
        const pane = paneForNode(element);
        if (pane instanceof Element) {
          const bar = pane.querySelector('[data-cas-pane-statusbar="true"][data-cas-pane-thread-id],[data-cas-status-inside-composer="true"][data-cas-pane-thread-id]');
          const barId = String(bar && bar.getAttribute('data-cas-pane-thread-id') || '').replace(/^local:/i, '').trim().toLowerCase();
          if (barId) return barId;

          if (typeof composerForPane === 'function' && typeof paneThreadId === 'function') {
            const composer = composerForPane(pane);
            const runtimeId = String(paneThreadId(pane, composer) || '').replace(/^local:/i, '').trim().toLowerCase();
            if (runtimeId) return runtimeId;
          }
        }
      }
    } catch {}

    const paneIds = r94KnownPaneThreadIds();
    if (paneIds.length === 1) return paneIds[0];
    if (paneIds.length > 1) return '';
    return String(r94CurrentThreadId() || '').replace(/^local:/i, '').trim().toLowerCase();
  }

  function r94NotificationFallbackThreadId() {
    const paneIds = r94KnownPaneThreadIds();
    if (paneIds.length === 1) return paneIds[0];
    if (paneIds.length > 1) return '';
    return String(r94CurrentThreadId() || '').replace(/^local:/i, '').trim().toLowerCase();
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
    const turn = element.closest(R94_TURN_SELECTOR);
    return turn instanceof Element ? turn : null;
  }

  function r94IdsForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const identityNode =
      (turn.matches('[data-turn-key],[data-content-search-turn-key],[data-content-search-assistant-turn-key]') ? turn : null) ||
      turn.querySelector('[data-turn-key],[data-content-search-turn-key],[data-content-search-assistant-turn-key]');
    const rawTurn =
      (identityNode && identityNode.getAttribute('data-turn-key')) ||
      (identityNode && identityNode.getAttribute('data-content-search-turn-key')) ||
      (identityNode && identityNode.getAttribute('data-content-search-assistant-turn-key')) ||
      '';
    const turnId = r94NormalizeTurnId(rawTurn);
    if (!turnId) return null;
    let threadId = r94TurnThreadIdCache.get(turn) || '';
    if (!threadId) {
      threadId = r94ThreadIdForNode(turn);
      if (threadId) r94TurnThreadIdCache.set(turn, threadId);
    }
    // R94_MULTI_PANE_FAIL_CLOSED_RUNTIME
    // In split view, an unowned turn must remain unstamped instead of borrowing
    // the parent route/thread identity and producing believable but wrong time.
    if (!threadId && r94KnownPaneThreadIds().length > 1) return null;
    return {
      threadId: threadId || null,
      turnId,
      key: (threadId || '__unknown_thread__') + '\u0000' + turnId,
    };
  }

  function r94CleanTimeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  // R94_FULL_DATE_TIMESTAMP_RUNTIME
  // Every Transfer-owned timestamp includes the local calendar date. We format
  // with local Date fields instead of UTC so the label follows the host system
  // clock/timezone exactly, while the title also exposes the short zone name.
  function r94LocalDateTimeStamp(epoch) {
    const d = new Date(epoch);
    if (!Number.isFinite(d.getTime())) return '';
    return String(d.getFullYear()).padStart(4,'0') + '-' +
      pad2(d.getMonth() + 1) + '-' +
      pad2(d.getDate()) + ' ' +
      pad2(d.getHours()) + ':' +
      pad2(d.getMinutes()) + ':' +
      pad2(d.getSeconds());
  }

  function r94LocalZoneName(epoch) {
    try {
      const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date(epoch));
      const zone = parts.find(function(part) { return part && part.type === 'timeZoneName'; });
      return zone && zone.value ? String(zone.value) : '';
    } catch {
      return '';
    }
  }

  function r94FullTimestampTitle(epoch, suffix) {
    const stamp = r94LocalDateTimeStamp(epoch);
    const zone = r94LocalZoneName(epoch);
    return stamp + (zone ? (' ' + zone) : '') + (suffix ? (' · ' + suffix) : '');
  }

  function r94TimelineCompactStamp(epoch) {
    const d = new Date(epoch);
    if (!Number.isFinite(d.getTime())) return '';
    return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' +
      pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  function r94TimeRecordFromElement(node, allowUser) {
    if (!(node instanceof Element)) return null;
    if (!allowUser && node.closest('[data-message-author-role="user"],[data-message-author="user"]')) return null;

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
          label: r94LocalDateTimeStamp(epoch),
          title: r94FullTimestampTitle(epoch, 'exact: Codex native sent time'),
          source: 'codex-native-sent-time',
        };
      }

      const parsed = Date.parse(value);
      const containsDate = /\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}/.test(value);
      if (Number.isFinite(parsed) && containsDate) {
        return {
          epoch: parsed,
          label: r94LocalDateTimeStamp(parsed),
          title: r94FullTimestampTitle(parsed, 'exact: Codex native sent time'),
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

  // R94_USER_PROMPT_TIMESTAMP_RUNTIME
  function r94UserSurfaceForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const selector = '[data-message-author-role="user"],[data-message-author="user"],[data-testid*="user-message"]';
    if (turn.matches(selector)) return turn;
    const user = turn.querySelector(selector);
    return user instanceof Element ? user : null;
  }

  function r94NativeUserExactForTurn(turn) {
    const user = r94UserSurfaceForTurn(turn);
    if (!(user instanceof Element)) return null;
    const nodes = [];
    if (user.matches(R94_NATIVE_TIME_SELECTOR)) nodes.push(user);
    user.querySelectorAll(R94_NATIVE_TIME_SELECTOR).forEach(function(node) { nodes.push(node); });
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const record = r94TimeRecordFromElement(nodes[index], true);
      if (record && Number.isFinite(record.epoch)) {
        record.title = r94FullTimestampTitle(record.epoch, 'exact: Codex native user sent time');
        record.source = 'codex-native-user-sent-time';
        return { record, sourceElement: nodes[index], anchor: user };
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
    const itemByKey = new Map();
    const latestKeyByThread = new Map();
    let capabilitySequence = 0;

    function keyFor(threadId, turnId) {
      const t = String(threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const u = r94NormalizeTurnId(turnId);
      return u ? ((t || '__unknown_thread__') + '\\u0000' + u) : '';
    }

    function itemKeyFor(threadId, turnId, itemId) {
      const t = String(threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const u = r94NormalizeTurnId(turnId);
      const i = String(itemId || '').trim().toLowerCase();
      return u && i ? ((t || '__unknown_thread__') + '\\u0000' + u + '\\u0000' + i) : '';
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
      current.capabilitySequence = ++capabilitySequence;
      if (ids.threadId) latestKeyByThread.set(ids.threadId, ids.key);
      if (Number.isFinite(completed) && completed > 0) {
        const epoch = completed > 10000000000 ? completed : completed * 1000;
        current.timestamp = {
          epoch,
          label: r94LocalDateTimeStamp(epoch),
          title: r94FullTimestampTitle(epoch, 'exact: Codex turn/completed'),
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

    function rememberItemLifecycle(threadId, turnId, item, eventAt, phase) {
      if (!item || typeof item !== 'object') return null;
      const normalizedTurn = r94NormalizeTurnId(turnId);
      const itemId = String(item.id || item.itemId || item.item_id || '').trim();
      const key = itemKeyFor(threadId, normalizedTurn, itemId);
      if (!key) return null;

      const current = itemByKey.get(key) || {
        threadId: String(threadId || '').replace(/^local:/i, '').trim().toLowerCase() || null,
        turnId: normalizedTurn,
        itemId,
        itemType: String(item.type || '').trim(),
        startedAtMs: null,
        completedAtMs: null,
      };

      const numericAt = Number(eventAt);
      if (String(phase || '').toLowerCase() === 'started' && Number.isFinite(numericAt) && numericAt > 0) {
        current.startedAtMs = numericAt > 10000000000 ? numericAt : numericAt * 1000;
      }
      if (String(phase || '').toLowerCase() === 'completed' && Number.isFinite(numericAt) && numericAt > 0) {
        current.completedAtMs = numericAt > 10000000000 ? numericAt : numericAt * 1000;
      }
      current.itemType = String(item.type || current.itemType || '').trim();
      itemByKey.delete(key);
      itemByKey.set(key, current);
      r94TrimCache(itemByKey);
      try {
        window.dispatchEvent(new CustomEvent('cas-r94-item-capability-update', {
          detail: { threadId: current.threadId, turnId: current.turnId, itemId: current.itemId, phase: String(phase || '') },
        }));
      } catch {}
      return current;
    }

    function getItemRecord(threadId, turnId, itemId) {
      const key = itemKeyFor(threadId, turnId, itemId);
      return key ? (itemByKey.get(key) || null) : null;
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
      // R94_PANE_TPS_SAMPLE_CLOCK_RUNTIME
      // Timestamp the exact token-usage change at ingestion time. Consecutive
      // samples from the same thread+turn let the status bar derive a pane-local
      // output-token rate without borrowing Codex's global/native tok/s.
      current.usageObservedAtMs = r94HostEpochNow();
      current.capabilitySequence = ++capabilitySequence;
      if (ids.threadId) latestKeyByThread.set(ids.threadId, key);
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
        const threadId = params.threadId || params.thread_id || value.threadId || value.thread_id || r94NotificationFallbackThreadId() || null;
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
        const threadId = params.threadId || params.thread_id || value.threadId || value.thread_id || r94NotificationFallbackThreadId() || null;
        const turn = params.turn && typeof params.turn === 'object'
          ? params.turn
          : {
              id: params.turnId || params.turn_id,
              status: params.status || 'inProgress',
              startedAt: params.startedAt ?? params.started_at,
            };
        return !!rememberLifecycle(threadId, turn);
      }
      if (method === 'item/started' || method === 'item_started') {
        return !!rememberItemLifecycle(
          params.threadId || params.thread_id || value.threadId || value.thread_id || r94NotificationFallbackThreadId() || null,
          params.turnId || params.turn_id,
          params.item && typeof params.item === 'object' ? params.item : (value.item && typeof value.item === 'object' ? value.item : null),
          params.startedAtMs ?? params.started_at_ms ?? value.startedAtMs ?? value.started_at_ms,
          'started'
        );
      }
      if (method === 'item/completed' || method === 'item_completed') {
        return !!rememberItemLifecycle(
          params.threadId || params.thread_id || value.threadId || value.thread_id || r94NotificationFallbackThreadId() || null,
          params.turnId || params.turn_id,
          params.item && typeof params.item === 'object' ? params.item : (value.item && typeof value.item === 'object' ? value.item : null),
          params.completedAtMs ?? params.completed_at_ms ?? value.completedAtMs ?? value.completed_at_ms,
          'completed'
        );
      }
      if (method === 'thread/tokenUsage/updated' || method === 'thread_token_usage_updated') {
        return !!rememberUsage(
          params.threadId || params.thread_id || value.threadId || value.thread_id || r94NotificationFallbackThreadId() || null,
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

      const directKey = latestKeyByThread.get(normalized);
      const direct = directKey ? exactByKey.get(directKey) : null;
      if (direct) return direct;

      // Native timestamp reads can touch historical visible turns. They must
      // never redefine which turn is the latest telemetry/lifecycle turn.
      let best = null;
      let bestSequence = -1;
      for (const record of exactByKey.values()) {
        const candidate = String(record && record.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
        const sequence = Number(record && record.capabilitySequence);
        if (candidate !== normalized || !Number.isFinite(sequence) || sequence <= bestSequence) continue;
        best = record;
        bestSequence = sequence;
      }
      if (best && best.turnId) latestKeyByThread.set(normalized, keyFor(normalized, best.turnId));
      return best;
    }

    function clear() {
      exactByKey.clear();
      itemByKey.clear();
      latestKeyByThread.clear();
      capabilitySequence = 0;
    }

    return Object.freeze({
      getForTurn,
      getRecord,
      getItemRecord,
      latestForThread,
      remember,
      rememberLifecycle,
      rememberUsage,
      ingestNotification,
      clear,
      size: function() { return exactByKey.size; },
      itemSize: function() { return itemByKey.size; },
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
      'max-width:240px',
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

  // R94_TIMELINE_NAV_RUNTIME
  // Conceptually follows the lightweight DOM-only navigation pattern used by
  // dsh-scroll-timeline (MIT): a self-rendered rail, hover metadata and
  // click-to-jump, without patching the host React tree or polling.
  function r94EnsureTimelineRailRoot() {
    let rail = document.getElementById(R94_TIMELINE_RAIL_ID);
    if (rail instanceof HTMLElement) return rail;
    rail = document.createElement('nav');
    rail.id = R94_TIMELINE_RAIL_ID;
    rail.setAttribute('aria-label','Transfer timeline');
    rail.style.cssText = [
      'position:fixed',
      'left:0',
      'top:72px',
      'width:150px',
      'height:calc(100vh - 144px)',
      'z-index:2147481900',
      'pointer-events:none',
      'overflow:visible',
      'contain:layout style',
    ].join(';') + ';';

    const line = document.createElement('div');
    line.setAttribute('data-cas-r94-timeline-line','true');
    line.style.cssText = [
      'position:absolute',
      'left:7px',
      'top:0',
      'bottom:0',
      'width:1px',
      'background:color-mix(in srgb,CanvasText 18%,transparent)',
      'pointer-events:none',
    ].join(';') + ';';
    rail.appendChild(line);
    (document.body || document.documentElement).appendChild(rail);
    return rail;
  }

  function r94CreateTimelineMarker(rail, entry) {
    const marker = document.createElement('button');
    marker.type = 'button';
    marker.className = R94_TIMELINE_MARKER_CLASS;
    marker.setAttribute('data-cas-r94-timeline-marker','true');
    marker.setAttribute('aria-label', entry.fullLabel + ' · ' + entry.kind + ' · click to jump');
    marker.title = entry.fullLabel + ' · ' + entry.kind +
      (entry.approx ? ' · first observed locally' : '') +
      (entry.preview ? (' · ' + entry.preview) : '');
    marker.style.cssText = [
      'position:absolute',
      'left:0',
      'top:0',
      'width:118px',
      'height:16px',
      'padding:0',
      'margin:0',
      'border:0',
      'background:transparent',
      'text-align:left',
      'pointer-events:auto',
      'cursor:pointer',
      'font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'color:color-mix(in srgb,CanvasText 58%,transparent)',
      'transform:translateY(-50%)',
      'outline:none',
    ].join(';') + ';';

    const tick = document.createElement('span');
    tick.setAttribute('data-cas-r94-timeline-tick','true');
    tick.style.cssText = [
      'position:absolute',
      'left:2px',
      'top:7px',
      'width:12px',
      'height:2px',
      'border-radius:2px',
      'background:currentColor',
      'opacity:.6',
      'transition:width .12s ease,opacity .12s ease',
      'pointer-events:none',
    ].join(';') + ';';

    const label = document.createElement('span');
    label.setAttribute('data-cas-r94-timeline-label','true');
    label.textContent = entry.compactLabel;
    label.style.cssText = [
      'position:absolute',
      'left:18px',
      'top:1px',
      'display:none',
      'padding:1px 4px',
      'border-radius:4px',
      'background:color-mix(in srgb,Canvas 92%,transparent)',
      'box-shadow:0 1px 5px color-mix(in srgb,CanvasText 12%,transparent)',
      'white-space:nowrap',
      'pointer-events:none',
    ].join(';') + ';';

    marker.appendChild(tick);
    marker.appendChild(label);

    const setExpanded = function(on) {
      const active = marker.getAttribute('data-cas-r94-timeline-active') === 'true';
      label.style.display = (on || active) ? 'block' : 'none';
      tick.style.width = (on || active) ? '24px' : '12px';
      tick.style.opacity = (on || active) ? '1' : '.6';
    };
    marker.addEventListener('mouseenter', function() { setExpanded(true); });
    marker.addEventListener('mouseleave', function() { setExpanded(false); });
    marker.addEventListener('focus', function() { setExpanded(true); });
    marker.addEventListener('blur', function() { setExpanded(false); });
    marker.__casR94SetExpanded = setExpanded;
    marker.__casR94Label = label;
    rail.appendChild(marker);
    return marker;
  }

  function r94FindScrollableAncestor(node) {
    let current = node instanceof Element ? node.parentElement : null;
    for (let depth = 0; depth < 16 && current; depth += 1) {
      try {
        const style = getComputedStyle(current);
        const overflowY = String(style && style.overflowY || '');
        if (/(auto|scroll)/.test(overflowY) && current.scrollHeight > current.clientHeight + 24) return current;
      } catch {}
      current = current.parentElement;
    }
    const fallback = document.scrollingElement;
    return fallback instanceof Element ? fallback : null;
  }

  function r94EpochMillis(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;
    return numeric > 10000000000 ? numeric : numeric * 1000;
  }

  function r94AnchorUsable(node) {
    if (!(node instanceof Element) || !node.isConnected) return false;
    try { return node.getClientRects().length > 0; } catch { return true; }
  }

  function r94NativeTimestampVisible(node) {
    if (!r94AnchorUsable(node)) return false;
    try {
      // R94_NATIVE_TIMESTAMP_ANCESTOR_VISIBILITY_RUNTIME
      // Hover/action rows often keep the <time> node mounted while an ancestor
      // is opacity:0. Inspect the bounded ancestor chain as well as the node;
      // connected DOM is not equivalent to a user-visible native timestamp.
      let current = node;
      for (let depth = 0; depth < 8 && current instanceof Element; depth += 1) {
        const style = getComputedStyle(current);
        if (!style || style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
        const opacity = Number(style.opacity);
        if (Number.isFinite(opacity) && opacity <= 0.05) return false;
        if (current.getAttribute('aria-hidden') === 'true') return false;
        current = current.parentElement;
      }
      return !!r94CleanTimeText(node.textContent || node.getAttribute('aria-label') || node.getAttribute('title'));
    } catch {
      return false;
    }
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

  // R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME
  // Reuses the proven r84/r90 visual segmentation model, but renders every
  // timestamp in the Transfer-owned overlay. Native Codex/React DOM stays
  // read-only and historical/remounted blocks are never assigned "now".
  const R94_SEGMENT_BADGE_CLASS = 'cas-r94-segment-time';
  const R94_SEGMENT_CACHE_LIMIT = 384;

  function r94HostEpochNow() {
    // User-facing wall-clock labels follow the current host system clock.
    // performance.timeOrigin is only a defensive fallback because it is
    // monotonic-ish and may not reflect a later OS clock/timezone adjustment.
    const systemEpoch = new Date().getTime();
    if (Number.isFinite(systemEpoch) && systemEpoch > 0) return systemEpoch;
    try {
      const origin = Number(performance && performance.timeOrigin);
      const offset = Number(performance && typeof performance.now === 'function' ? performance.now() : NaN);
      if (Number.isFinite(origin) && Number.isFinite(offset) && origin > 0) return origin + offset;
    } catch {}
    return 0;
  }

  function r94IsUserSurface(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return false;
    const userSelector = '[data-message-author-role="user"],[data-message-author="user"]';
    if (element.closest(userSelector)) return true;

    // Wrapper-only chains around a user bubble must not acquire assistant
    // timestamps. A mixed whole-turn wrapper is allowed to continue downward so
    // its assistant/tool descendants can still be segmented.
    const user = element.querySelector(userSelector);
    if (!(user instanceof Element)) return false;
    const assistant = element.querySelector(
      '[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]'
    );
    return !(assistant instanceof Element);
  }

  function r94SpecificSemanticOutputSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-local-conversation-final-assistant]')) return true;
    return node.matches('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
  }

  function r94AssistantMessageSurface(node) {
    if (!(node instanceof Element) || !node.matches('[data-message-author-role="assistant"]')) return false;
    const turn = r94CanonicalTurn(node);
    // A whole-turn identity wrapper is not one output event. A nested assistant
    // message node is: this maps the user's visible "update 1 / update 2 / update
    // 3" groups to one host timestamp per emitted assistant block.
    return turn instanceof Element && turn !== node;
  }

  function r94StrongSemanticOutputSurface(node) {
    return r94SpecificSemanticOutputSurface(node) || r94AssistantMessageSurface(node);
  }

  // R94_STRUCTURAL_STATUS_FALLBACK_RUNTIME
  // Current Codex Desktop does not expose stable data-testid/item-id attributes
  // on every visible progress/agent summary card. Recognize only coarse,
  // high-signal status blocks, then keep the most specific matching wrapper.
  // This avoids falling back to arbitrary Markdown paragraphs/list items.
  function r94FallbackSemanticSignature(node) {
    if (!(node instanceof Element)) return '';
    const text = normalizedText(node).replace(/\s+/g, ' ').trim();
    if (text.length < 2 || text.length > 1800) return '';

    const stepLabels = [
      /(?:^|\s)步骤\s*[:：]/g,
      /(?:^|\s)目的\s*[:：]/g,
      /(?:^|\s)执行\s*[:：]/g,
      /(?:^|\s)结果\s*[:：]/g,
      /(?:^|\s)证据\s*[:：]/g,
    ];
    let stepScore = 0;
    for (const pattern of stepLabels) {
      pattern.lastIndex = 0;
      if (pattern.test(text)) stepScore += 1;
    }
    if (stepScore >= 2) return 'status';

    if (/^(?:created an agent|closed an agent|worked for\s+\d+\s*[smh]?|called tool|talked to app|read resource)\b/i.test(text)) {
      return /agent/i.test(text) ? 'agent' : 'status';
    }
    if (/^(?:已?创建.*子代理|已?关闭.*子代理|子代理.*(?:已连接|已创建|已关闭|连接成功)|调用(?:了)?工具|读取(?:了)?资源)/i.test(text)) {
      return /子代理/.test(text) ? 'agent' : 'status';
    }
    return '';
  }

  function r94FallbackSemanticOutputSurfaces(turn) {
    if (!(turn instanceof Element)) return [];
    const raw = Array.from(turn.querySelectorAll('div,section,article,[role="group"],li'))
      .filter(function(node) {
        return node instanceof Element &&
          node !== turn &&
          node.isConnected &&
          isVisible(node) &&
          !insideComposer(node) &&
          !insideOwnUi(node) &&
          !r94IsUserSurface(node) &&
          !!r94FallbackSemanticSignature(node);
      });

    return raw.filter(function(node) {
      const signature = r94FallbackSemanticSignature(node);
      return !raw.some(function(other) {
        return other !== node &&
          node.contains(other) &&
          r94FallbackSemanticSignature(other) === signature;
      });
    });
  }

  // R94_SEMANTIC_OUTPUT_UNIT_RUNTIME
  // One timestamp belongs to one Codex output item/message/tool surface, not to
  // arbitrary visual descendants such as paragraphs, list items, table rows or
  // code-block internals. This prevents one assistant update from exploding
  // into dozens of unrelated timestamps when Markdown reflows.
  const R94_SEMANTIC_OUTPUT_SELECTOR = [
    '[data-message-author-role="assistant"]',
    '[data-local-conversation-final-assistant]',
    '[data-item-id]',
    '[data-content-search-item-id]',
    '[role="status"]',
    '[data-testid*="agent"]',
    '[data-testid*="tool"]',
    '[data-testid*="command"]',
    '[data-testid*="integration"]'
  ].join(',');

  function r94SemanticKind(node) {
    if (!(node instanceof Element)) return 'assistant';
    if (node.matches('[data-local-conversation-final-assistant]')) return 'final';
    const fallbackKind = r94FallbackSemanticSignature(node);
    if (fallbackKind) return fallbackKind;
    if (node.matches('[data-testid*="agent"]') || node.closest('[data-testid*="agent"]')) return 'agent';
    if (node.matches('[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]') ||
        node.closest('[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]')) return 'tool';
    if (node.matches('[role="status"]') || node.closest('[role="status"]')) return 'status';
    return 'assistant';
  }

  function r94SemanticOutputSurfaceUsable(node, turn) {
    if (!(node instanceof Element) || !node.isConnected || !isVisible(node)) return false;
    if (!(turn instanceof Element) || (!turn.contains(node) && node !== turn)) return false;
    if (insideComposer(node) || insideOwnUi(node) || r94IsUserSurface(node)) return false;
    if (normalizedText(node).length < 2 && !r94StrongSemanticOutputSurface(node)) return false;
    return true;
  }

  function r94AssistantWrapperHasOwnProse(node) {
    // R94_ASSISTANT_PROSE_WITH_TOOL_RUNTIME
    // An assistant message may contain an embedded tool/agent/status card and
    // still have its own prose before/after that card. Do not discard the
    // assistant timestamp merely because an operational child exists.
    if (!(node instanceof Element)) return false;
    let walker = null;
    try { walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT); } catch {}
    if (!walker) return normalizedText(node).length >= 2;

    let ownChars = 0;
    while (walker.nextNode()) {
      const textNode = walker.currentNode;
      const parent = textNode && textNode.parentElement;
      if (!(parent instanceof Element) || insideOwnUi(parent)) continue;
      const semanticOwner = parent.closest(R94_SEMANTIC_OUTPUT_SELECTOR);
      if (semanticOwner instanceof Element && semanticOwner !== node && node.contains(semanticOwner)) {
        continue;
      }
      ownChars += String(textNode.nodeValue || '').replace(/\s+/g, '').length;
      if (ownChars >= 2) return true;
    }
    return false;
  }

  function r94CollectSemanticOutputSurfaces(turn) {
    if (!(turn instanceof Element)) return [];
    const raw = [];
    if (turn.matches(R94_SEMANTIC_OUTPUT_SELECTOR)) raw.push(turn);
    turn.querySelectorAll(R94_SEMANTIC_OUTPUT_SELECTOR).forEach(function(node) { raw.push(node); });
    r94FallbackSemanticOutputSurfaces(turn).forEach(function(node) { raw.push(node); });

    const candidates = [];
    const seenNodes = new Set();
    for (const node of raw) {
      if (!r94SemanticOutputSurfaceUsable(node, turn) || seenNodes.has(node)) continue;
      seenNodes.add(node);
      candidates.push(node);
    }

    // R94_ITEM_ID_DEDUPE_SPECIFICITY_RUNTIME
    // Do not let an ancestor assistant wrapper steal a descendant tool/item id.
    // When the same direct item id appears on nested wrappers, keep the most
    // specific descendant (and prefer a concrete non-assistant surface).
    const directItemOwners = new Map();
    for (const node of candidates) {
      const itemId = r94DirectItemIdForSurface(node);
      if (!itemId) continue;
      const normalized = String(itemId).toLowerCase();
      const existing = directItemOwners.get(normalized);
      if (!(existing instanceof Element)) {
        directItemOwners.set(normalized, node);
        continue;
      }
      const existingKind = r94SemanticKind(existing);
      const nodeKind = r94SemanticKind(node);
      if (
        existing.contains(node) ||
        (existingKind === 'assistant' && nodeKind !== 'assistant')
      ) {
        directItemOwners.set(normalized, node);
      }
    }

    const filtered = candidates.filter(function(node) {
      const itemId = r94DirectItemIdForSurface(node);
      if (!itemId) return true;
      return directItemOwners.get(String(itemId).toLowerCase()) === node;
    });

    return filtered.filter(function(node) {
      const kind = r94SemanticKind(node);
      for (const other of filtered) {
        if (other === node || !other.contains(node)) continue;
        const otherKind = r94SemanticKind(other);

        // Nested controls/status fragments inside one tool/agent/status card are
        // presentation details of the same output item, not separate outputs.
        if (otherKind === kind && kind !== 'assistant') return false;
        if (otherKind === 'tool' || otherKind === 'agent' || otherKind === 'status') return false;
      }

      // A generic assistant wrapper that only contains a concrete operational
      // item is not an additional model-output timestamp. If it also owns
      // visible assistant prose, keep it: that prose is one of the user's
      // meaningful "model output before/after tool" timestamp units.
      if (kind === 'assistant') {
        let containsOperationalItem = false;
        for (const other of filtered) {
          if (other === node || !node.contains(other)) continue;
          const otherKind = r94SemanticKind(other);
          if (otherKind === 'tool' || otherKind === 'agent' || otherKind === 'status') {
            containsOperationalItem = true;
            break;
          }
        }
        if (containsOperationalItem && !r94AssistantWrapperHasOwnProse(node)) return false;
      }
      return true;
    });
  }

  function r94TopLevelSegments(turn) {
    return r94CollectSemanticOutputSurfaces(turn);
  }

  function r94NormalizeItemId(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const uuid = raw.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    return uuid ? uuid[0] : raw;
  }

  function r94DirectItemIdForSurface(surface) {
    if (!(surface instanceof Element)) return '';
    const attrs = [
      'data-item-id',
      'data-message-id',
      'data-content-search-item-id',
      'data-agent-item-id',
      'data-tool-call-id',
      'data-call-id'
    ];
    for (const attr of attrs) {
      const value = r94NormalizeItemId(surface.getAttribute(attr));
      if (value) return value;
    }
    return '';
  }

  function r94ItemIdForSurface(surface) {
    if (!(surface instanceof Element)) return '';
    const direct = r94DirectItemIdForSurface(surface);
    if (direct) return direct;
    const attrs = [
      'data-item-id',
      'data-message-id',
      'data-content-search-item-id',
      'data-agent-item-id',
      'data-tool-call-id',
      'data-call-id'
    ];

    // A descendant identity can still bind an otherwise identity-less exact
    // surface, but collector-level dedupe uses direct ids so ancestors cannot
    // suppress the concrete child item before it is timestamped.
    const child = surface.querySelector(
      '[data-item-id],[data-message-id],[data-content-search-item-id],[data-agent-item-id],[data-tool-call-id],[data-call-id]'
    );
    if (child instanceof Element) {
      for (const attr of attrs) {
        const value = r94NormalizeItemId(child.getAttribute(attr));
        if (value) return value;
      }
    }
    return '';
  }

  function r94ExactItemTimeForSurface(surface, turn, capability) {
    if (!(surface instanceof Element) || !(turn instanceof Element) || !capability ||
        typeof capability.getItemRecord !== 'function') return null;
    const ids = r94IdsForTurn(turn);
    if (!ids) return null;

    // R94_NO_DESCENDANT_EXACT_BORROW_RUNTIME
    // A prose-bearing assistant wrapper must not borrow the item id/time of an
    // embedded tool card. Only its own direct identity is exact; otherwise the
    // live first-observed timestamp remains an explicitly approximate value.
    const directItemId = r94DirectItemIdForSurface(surface);
    const kind = r94SemanticKind(surface);
    const ownsAssistantProse =
      kind === 'assistant' && r94AssistantWrapperHasOwnProse(surface);
    const itemId = directItemId || (ownsAssistantProse ? '' : r94ItemIdForSurface(surface));
    if (!itemId) return null;
    const record = capability.getItemRecord(ids.threadId, ids.turnId, itemId);
    if (!record) return null;
    const started = Number(record.startedAtMs);
    const completed = Number(record.completedAtMs);
    const epoch = Number.isFinite(started) && started > 0
      ? started
      : (Number.isFinite(completed) && completed > 0 ? completed : null);
    if (!Number.isFinite(epoch)) return null;
    return {
      epoch,
      source: Number.isFinite(started) && started > 0 ? 'item/started' : 'item/completed',
      itemId,
      itemType: String(record.itemType || '')
    };
  }

  function r94StructuralPath(node, stop) {
    const parts = [];
    let current = node;
    for (let depth = 0; depth < 18 && current instanceof Element && current !== stop; depth += 1) {
      const parent = current.parentElement;
      if (!(parent instanceof Element)) break;
      const siblings = Array.from(parent.children || []).filter(function(child) {
        return !(child instanceof Element && child.closest('#' + R94_OVERLAY_ID));
      });
      const index = siblings.indexOf(current);
      parts.unshift(index >= 0 ? index : 0);
      current = parent;
    }
    return parts.join('.');
  }

  function r94Hash(value) {
    const text = String(value || '');
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
  }

  function r94SegmentKey(segment, turn) {
    if (!(segment instanceof Element) || !(turn instanceof Element)) return '';
    const ids = r94IdsForTurn(turn);
    const rootId = ids && ids.turnId ? ids.turnId : r94StructuralPath(turn, document.body);
    const semanticId =
      r94ItemIdForSurface(segment) ||
      segment.getAttribute('data-message-id') ||
      segment.getAttribute('data-testid') ||
      segment.getAttribute('role') || '';
    const tag = String(segment.tagName || '').toLowerCase();
    // Do not hash mutable text. Streaming text changes must keep one stable
    // first-observed timestamp for the same visual block.
    return r94Hash(rootId + '|' + r94StructuralPath(segment, turn) + '|' + semanticId + '|' + tag);
  }

  function r94SegmentTimeIsExact(source) {
    return /^item\/(started|completed)$/i.test(String(source || ''));
  }

  function r94SegmentTimeLabel(epoch, source) {
    return (r94SegmentTimeIsExact(source) ? '' : '≈') + r94LocalDateTimeStamp(epoch);
  }

  function r94SegmentTimeTitle(epoch, source) {
    if (r94SegmentTimeIsExact(source)) {
      return r94FullTimestampTitle(epoch, 'exact: Codex app-server ' + String(source || 'item lifecycle'));
    }
    return r94FullTimestampTitle(epoch, 'approximate: first observed locally when this semantic output item appeared');
  }

  function r94CreateSegmentBadge(root, epoch, source) {
    const badge = document.createElement('div');
    badge.className = R94_SEGMENT_BADGE_CLASS;
    badge.setAttribute('aria-hidden','true');
    badge.textContent = r94SegmentTimeLabel(epoch, source);
    badge.title = r94SegmentTimeTitle(epoch, source);
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
      'color:color-mix(in srgb,CanvasText 48%,transparent)',
      'font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'font-variant-numeric:tabular-nums',
      'white-space:nowrap',
      'pointer-events:none',
      'user-select:none',
      'opacity:.78',
      'will-change:transform',
    ].join(';') + ';';
    root.appendChild(badge);
    return badge;
  }

  function r94ActiveGenerationUiPresentFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    const pane = typeof paneForNode === 'function' ? paneForNode(element) : null;
    const composer = typeof composerForPane === 'function'
      ? composerForPane(pane)
      : (typeof findComposerRoot === 'function' ? findComposerRoot() : null);
    const scope = pane instanceof Element
      ? pane
      : (composer instanceof Element ? (composer.parentElement || composer) : document);

    const controls = scope.querySelectorAll ? scope.querySelectorAll('button,[role="button"]') : [];
    for (const control of controls) {
      if (!(control instanceof Element) || !isVisible(control) || insideOwnUi(control)) continue;
      const hint = [
        control.getAttribute('aria-label'),
        control.getAttribute('title'),
        control.getAttribute('data-testid'),
        control.getAttribute('data-state'),
        control.textContent,
      ].filter(Boolean).join(' ').toLowerCase();
      if (/(^|[\s:_-])(stop|cancel|interrupt|abort|pause)([\s:_-]|$)|停止|取消|中止|终止|暂停/i.test(hint)) return true;
    }

    const busy = scope.querySelectorAll
      ? scope.querySelectorAll('[aria-busy="true"],[data-loading="true"],[data-state="loading"],[data-state="pending"],[data-state="running"],[class*="animate-spin"],[class*="spinner"]')
      : [];
    for (const node of busy) {
      if (node instanceof Element && isVisible(node) && !insideOwnUi(node)) return true;
    }
    return false;
  }

  function r94LatestVisibleAssistantTurnFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    const pane = typeof paneForNode === 'function' ? paneForNode(element) : null;
    const scope = pane instanceof Element ? pane : document;
    const all = Array.from(scope.querySelectorAll(R94_TURN_SELECTOR))
      .filter(function(candidate) {
        return candidate instanceof Element &&
          candidate.isConnected &&
          !insideComposer(candidate) &&
          !insideOwnUi(candidate) &&
          !r94IsUserSurface(candidate);
      });
    const seen = new Set();
    const ordered = [];
    for (const candidate of all) {
      const turn = r94CanonicalTurn(candidate);
      if (!(turn instanceof Element) || seen.has(turn)) continue;
      seen.add(turn);
      ordered.push(turn);
    }
    return ordered.length ? ordered[ordered.length - 1] : null;
  }

  function installOutputObserver() {
    if (!document.body) {
      setTimeout(installOutputObserver, 120);
      return;
    }

    const overlayRoot = r94EnsureOverlayRoot();
    // R94_NATIVE_RAIL_PRESERVE_RUNTIME
    // Codex already owns the compact conversation rail/minimap. Do not draw a
    // second Transfer rail on top of it; keep our timeline data internal only.
    const timelineRail = null;
    const capability = r94CreateCapability();
    state.r94TimestampCapability = capability;
    window.__casR94TurnCapability = capability;

    const diagnostics = {
      exactOnly: false,
      hybridSegmentMode: true,
      observedTurns: 0,
      visibleTurns: 0,
      badges: 0,
      userBadges: 0,
      cacheSize: 0,
      liveSegmentsStamped: 0,
      liveSegmentBadges: 0,
      liveSegmentCache: 0,
      semanticUnits: 0,
      exactItemBindings: 0,
      lastSource: '',
      lastLiveSegmentSource: '',
      nativeTimestampSuppressed: 0,
      timelineRailMode: false,
      nativeRailPreserved: true,
      timelineEntries: 0,
      timelineMarkers: 0,
      timelineActiveKey: '',
      timelineLastKind: '',
    };
    window.__casR94TimestampDiagnostics = diagnostics;

    const observedTurns = new Set();
    const visibleTurns = new Set();
    const pendingRoots = new Set();
    const entryByTurn = new WeakMap();
    const userEntryByTurn = new WeakMap();
    const visibleEntries = new Set();

    // Live per-output timestamp state. Existing DOM is baselined at install so
    // only blocks first appearing during an actually-live turn receive ≈ time.
    const baselineSegmentNodes = new WeakSet();
    const baselineSegmentKeys = new Set();
    const segmentTimeByKey = new Map();
    const segmentEntryByNode = new WeakMap();
    const visibleSegmentEntries = new Set();
    const pendingSegmentTurns = new Set();
    // R94_PANE_ORPHAN_SEMANTIC_TIMESTAMP_RUNTIME
    // Some current Desktop progress/agent cards are pane children rather than
    // descendants of a canonical turn wrapper. Track only newly-added live
    // semantic nodes so history/remounts are never assigned a fresh "now".
    const orphanSegmentNodes = new WeakSet();

    const timelineEntries = new Map();
    const timelineMarkers = new Map();
    let timelineScroller = null;
    let timelineActiveKey = '';
    let latestObservedTurn = null;
    const latestObservedTurnByThread = new Map();
    const generationUiCache = new WeakMap();

    let disposed = false;
    let mutationObserver = null;
    let frameId = 0;
    let scanFrameId = 0;
    let segmentFrameId = 0;
    let segmentTimerId = 0;

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
      let userBadgeCount = 0;
      for (const entry of visibleEntries) {
        if (entry && entry.mode === 'user') userBadgeCount += 1;
      }
      diagnostics.userBadges = userBadgeCount;
      diagnostics.cacheSize = capability.size();
      diagnostics.liveSegmentBadges = visibleSegmentEntries.size;
      diagnostics.liveSegmentCache = segmentTimeByKey.size;
      diagnostics.semanticUnits = segmentTimeByKey.size;
      diagnostics.timelineEntries = timelineEntries.size;
      diagnostics.timelineMarkers = timelineMarkers.size;
      diagnostics.timelineActiveKey = timelineActiveKey;
    }

    function r94TimelineKindLabel(kind) {
      const value = String(kind || 'event').toLowerCase();
      if (value === 'user') return 'U';
      if (value === 'final') return 'F';
      if (value === 'tool') return 'T';
      if (value === 'agent') return 'G';
      if (value === 'status') return 'S';
      return 'A';
    }

    function r94TimelineScrollerForEntry(entry) {
      if (entry && entry.anchor instanceof Element && entry.anchor.isConnected) {
        const found = r94FindScrollableAncestor(entry.anchor);
        if (found instanceof Element) return found;
      }
      if (timelineScroller instanceof Element && timelineScroller.isConnected) return timelineScroller;
      for (const item of timelineEntries.values()) {
        if (!(item.anchor instanceof Element) || !item.anchor.isConnected) continue;
        const found = r94FindScrollableAncestor(item.anchor);
        if (found instanceof Element) return found;
      }
      return null;
    }

    function r94ScrollerMetrics(scroller) {
      if (!(scroller instanceof Element)) return null;
      const isDocumentScroller =
        scroller === document.scrollingElement ||
        scroller === document.documentElement ||
        scroller === document.body;
      let rect = null;
      if (isDocumentScroller) {
        rect = { left: 0, top: 0, right: innerWidth, bottom: innerHeight, width: innerWidth, height: innerHeight };
      } else {
        try { rect = scroller.getBoundingClientRect(); } catch { return null; }
      }
      const scrollTop = isDocumentScroller ? (window.scrollY || scroller.scrollTop || 0) : scroller.scrollTop;
      const clientHeight = isDocumentScroller ? innerHeight : scroller.clientHeight;
      const scrollHeight = Math.max(clientHeight, Number(scroller.scrollHeight) || clientHeight);
      return { scroller, isDocumentScroller, rect, scrollTop, clientHeight, scrollHeight };
    }

    function r94TimelineRatioForAnchor(anchor, metrics) {
      if (!(anchor instanceof Element) || !anchor.isConnected || !metrics) return null;
      let rect;
      try { rect = anchor.getBoundingClientRect(); } catch { return null; }
      const absoluteTop = metrics.isDocumentScroller
        ? metrics.scrollTop + rect.top
        : metrics.scrollTop + rect.top - metrics.rect.top;
      const ratio = absoluteTop / Math.max(1, metrics.scrollHeight);
      return Math.max(0, Math.min(1, ratio));
    }

    function r94TrimTimelineEntries() {
      while (timelineEntries.size > R94_TIMELINE_LIMIT) {
        const oldestKey = timelineEntries.keys().next().value;
        if (oldestKey == null) break;
        timelineEntries.delete(oldestKey);
        const marker = timelineMarkers.get(oldestKey);
        if (marker && marker.isConnected) marker.remove();
        timelineMarkers.delete(oldestKey);
      }
    }

    function r94JumpTimelineEntry(key) {
      const entry = timelineEntries.get(key);
      if (!entry) return;
      const scroller = r94TimelineScrollerForEntry(entry);
      const metrics = r94ScrollerMetrics(scroller);
      if (!metrics) return;
      timelineScroller = scroller;

      let target = null;
      if (entry.anchor instanceof Element && entry.anchor.isConnected) {
        let rect;
        try { rect = entry.anchor.getBoundingClientRect(); } catch { rect = null; }
        if (rect) {
          target = metrics.isDocumentScroller
            ? metrics.scrollTop + rect.top - Math.max(12, metrics.clientHeight * 0.18)
            : metrics.scrollTop + rect.top - metrics.rect.top - Math.max(12, metrics.clientHeight * 0.18);
        }
      }
      if (!Number.isFinite(target) && Number.isFinite(entry.ratio)) {
        target = entry.ratio * metrics.scrollHeight - Math.max(12, metrics.clientHeight * 0.18);
      }
      if (!Number.isFinite(target)) return;
      target = Math.max(0, Math.min(Math.max(0, metrics.scrollHeight - metrics.clientHeight), target));

      const reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
      try {
        scroller.dispatchEvent(new WheelEvent('wheel', { deltaY: target < metrics.scrollTop ? -1 : 1, bubbles: true, cancelable: true }));
      } catch {}

      if (reduced || Math.abs(target - metrics.scrollTop) < 24) {
        if (metrics.isDocumentScroller) window.scrollTo(0, target);
        else scroller.scrollTop = target;
      } else {
        const start = metrics.scrollTop;
        const distance = target - start;
        const duration = Math.min(520, 180 + Math.abs(distance) * 0.22);
        const started = performance.now();
        const step = function(now) {
          const p = Math.min(1, (now - started) / duration);
          const eased = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
          try {
            scroller.dispatchEvent(new WheelEvent('wheel', { deltaY: distance < 0 ? -1 : 1, bubbles: true, cancelable: true }));
          } catch {}
          const next = start + distance * eased;
          if (metrics.isDocumentScroller) window.scrollTo(0, next);
          else scroller.scrollTop = next;
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }

      timelineActiveKey = key;
      diagnostics.timelineActiveKey = key;
      r94SchedulePosition();
    }

    function r94UpsertTimelineEntry(key, epoch, anchor, kind, approx, preview) {
      // R94_NATIVE_RAIL_METADATA_ONLY_RUNTIME
      // Keep bounded timestamp metadata for diagnostics/future native-rail
      // augmentation, but create no visible rail/marker DOM and do no scroll
      // geometry work during streaming.
      const normalizedEpoch = r94EpochMillis(epoch);
      if (!key || !Number.isFinite(normalizedEpoch)) return;
      let entry = timelineEntries.get(key);
      if (!entry) {
        entry = { key, epoch: normalizedEpoch, anchor: null, kind: kind || 'assistant', approx: !!approx, preview: '' };
      }
      entry.epoch = normalizedEpoch;
      if (anchor instanceof Element) entry.anchor = anchor;
      entry.kind = kind || entry.kind || 'assistant';
      entry.approx = !!approx;
      entry.preview = String(preview || entry.preview || '').replace(/\s+/g,' ').trim().slice(0,180);
      entry.fullLabel = (entry.approx ? '≈' : '') + r94LocalDateTimeStamp(normalizedEpoch);
      timelineEntries.delete(key);
      timelineEntries.set(key, entry);
      r94TrimTimelineEntries();
      diagnostics.timelineLastKind = entry.kind;
      r94SyncDiagnostics();
    }

    function r94PositionTimelineRail() {
      // R94_NATIVE_RAIL_NO_CUSTOM_PAINT_RUNTIME
      // Intentionally empty. Codex's official minimap/rail remains the only
      // visible navigation rail.
    }

    function r94RemoveTurnBadge(turn) {
      const entry = entryByTurn.get(turn);
      if (!entry) return;
      visibleEntries.delete(entry);
      if (entry.badge && entry.badge.isConnected) entry.badge.remove();
      entry.badge = null;
    }

    function r94RemoveUserBadge(turn) {
      const entry = userEntryByTurn.get(turn);
      if (!entry) return;
      visibleEntries.delete(entry);
      if (entry.badge && entry.badge.isConnected) entry.badge.remove();
      entry.badge = null;
    }

    function r94EnsureUserBadge(turn, ids) {
      if (!(turn instanceof Element) || !ids) return;
      const user = r94UserSurfaceForTurn(turn);
      if (!(user instanceof Element) || !user.isConnected) {
        r94RemoveUserBadge(turn);
        return;
      }

      let record = null;
      const nativeUser = r94NativeUserExactForTurn(turn);
      if (nativeUser && nativeUser.record && Number.isFinite(nativeUser.record.epoch)) {
        record = nativeUser.record;
      }

      if (!record) {
        const turnRecord = capability.getRecord(ids.threadId, ids.turnId);
        const startedEpoch = r94EpochMillis(turnRecord && turnRecord.startedAt);
        if (Number.isFinite(startedEpoch)) {
          record = {
            epoch: startedEpoch,
            label: r94LocalDateTimeStamp(startedEpoch),
            title: r94FullTimestampTitle(startedEpoch, 'exact: Codex turn/started for user prompt'),
            source: 'turn/started-user-prompt',
          };
        }
      }

      if (!record || !record.label) {
        r94RemoveUserBadge(turn);
        return;
      }

      let entry = userEntryByTurn.get(turn);
      if (!entry) {
        entry = { turn, ids, record, anchor: user, mode: 'user', badge: null };
        userEntryByTurn.set(turn, entry);
      } else {
        entry.ids = ids;
        entry.record = record;
        entry.anchor = user;
        entry.mode = 'user';
      }

      if (!entry.badge || !entry.badge.isConnected) {
        entry.badge = r94CreateBadge(overlayRoot, record);
      } else {
        if (entry.badge.textContent !== record.label) entry.badge.textContent = record.label;
        entry.badge.title = record.title || record.label;
      }
      visibleEntries.add(entry);
      r94SyncDiagnostics();
    }

    function r94TimelineKindForSegment(segment) {
      return r94SemanticKind(segment);
    }

    function r94RegisterTurnTimeline(turn, ids, exact) {
      if (!(turn instanceof Element) || !ids) return;
      const record = capability.getRecord(ids.threadId, ids.turnId);

      const startedEpoch = r94EpochMillis(record && record.startedAt);
      if (Number.isFinite(startedEpoch)) {
        const userAnchor =
          turn.querySelector('[data-message-author-role="user"],[data-message-author="user"]') ||
          turn;
        r94UpsertTimelineEntry(
          'turn-start:' + ids.key,
          startedEpoch,
          userAnchor,
          'user',
          false,
          normalizedText(userAnchor).slice(0,180)
        );
      }

      let finalEpoch = exact && exact.record ? r94EpochMillis(exact.record.epoch) : null;
      if (!Number.isFinite(finalEpoch)) finalEpoch = r94EpochMillis(record && record.completedAt);
      if (Number.isFinite(finalEpoch)) {
        const finalAnchor =
          (exact && exact.sourceElement instanceof Element ? exact.sourceElement : null) ||
          turn.querySelector(R94_FINAL_SELECTOR) ||
          turn;
        r94UpsertTimelineEntry(
          'turn-final:' + ids.key,
          finalEpoch,
          finalAnchor,
          'final',
          false,
          normalizedText(finalAnchor).slice(-180)
        );
      }
    }

    function r94EnsureTurnBadge(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      const ids = r94IdsForTurn(turn);
      if (!ids) return;
      r94EnsureUserBadge(turn, ids);
      let exact = capability.getForTurn(turn, ids);
      // R94_SHORT_NATIVE_TIME_LIFECYCLE_UPGRADE_RUNTIME
      // A visible native sent-time can be time-only ("8:30 PM"). If the same
      // turn has an exact app-server completion epoch, upgrade the presentation
      // record before either the native-visibility or generic overlay branch.
      // This keeps the React DOM read-only and avoids guessing a calendar date.
      if (exact && exact.record && !Number.isFinite(r94EpochMillis(exact.record.epoch))) {
        const lifecycleRecord = capability.getRecord(ids.threadId, ids.turnId);
        const completedEpoch = r94EpochMillis(lifecycleRecord && lifecycleRecord.completedAt);
        if (Number.isFinite(completedEpoch)) {
          exact = {
            record: {
              epoch: completedEpoch,
              label: r94LocalDateTimeStamp(completedEpoch),
              title: r94FullTimestampTitle(completedEpoch, 'exact: Codex turn/completed'),
              source: 'turn/completed-full-format',
            },
            sourceElement: exact.sourceElement instanceof Element ? exact.sourceElement : null,
          };
        }
      }
      r94RegisterTurnTimeline(turn, ids, exact);
      if (!exact || !exact.record || !exact.record.label) {
        r94RemoveTurnBadge(turn);
        return;
      }

      if (
        exact.sourceElement instanceof Element &&
        exact.sourceElement.isConnected
      ) {
        // R94_NATIVE_TIME_FULL_FORMAT_OVERLAY_RUNTIME
        // Keep the native React DOM read-only. If Codex visibly renders only a
        // short time such as "8:06 PM", but the native datetime/lifecycle gives
        // us an exact epoch, cover that text with one Transfer overlay using the
        // required YYYY-MM-DD HH:mm:ss format. This is one visual timestamp,
        // not a duplicate native+Transfer timestamp.
        const nativeVisibleText = normalizedText(exact.sourceElement);
        const nativeAlreadyFull = /\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\b/.test(nativeVisibleText);
        const nativeVisibilityGate = r94NativeTimestampVisible(exact.sourceElement);
        let nativeHasLayoutBox = false;
        try { nativeHasLayoutBox = exact.sourceElement.getClientRects().length > 0; } catch {}
        const lifecycleRecord = capability.getRecord(ids.threadId, ids.turnId);
        const lifecycleCompleted = r94EpochMillis(lifecycleRecord && lifecycleRecord.completedAt);
        const exactEpoch = r94EpochMillis(exact.record && exact.record.epoch);
        const coverEpoch = Number.isFinite(exactEpoch) ? exactEpoch : lifecycleCompleted;

        if (!nativeAlreadyFull && Number.isFinite(coverEpoch) && (nativeVisibilityGate || nativeHasLayoutBox)) {
          const coverRecord = {
            epoch: coverEpoch,
            label: r94LocalDateTimeStamp(coverEpoch),
            title: r94FullTimestampTitle(coverEpoch, 'exact: Codex native/turn completion time'),
            source: 'native-time-full-format-overlay',
          };
          let nativeEntry = entryByTurn.get(turn);
          if (!nativeEntry) {
            nativeEntry = {
              turn,
              ids,
              record: coverRecord,
              anchor: exact.sourceElement,
              mode: 'native-time-cover',
              badge: null,
            };
            entryByTurn.set(turn, nativeEntry);
          } else {
            nativeEntry.ids = ids;
            nativeEntry.record = coverRecord;
            nativeEntry.anchor = exact.sourceElement;
            nativeEntry.mode = 'native-time-cover';
          }
          if (!nativeEntry.badge || !nativeEntry.badge.isConnected) {
            nativeEntry.badge = r94CreateBadge(overlayRoot, coverRecord);
          } else {
            nativeEntry.badge.textContent = coverRecord.label;
            nativeEntry.badge.title = coverRecord.title;
          }
          nativeEntry.badge.setAttribute('data-cas-native-time-cover','true');
          nativeEntry.badge.style.background = 'Canvas';
          nativeEntry.badge.style.padding = '0 1px';
          nativeEntry.badge.style.opacity = '1';
          visibleEntries.add(nativeEntry);
          r94SuppressNativeFinalSegmentBadge(turn);
          diagnostics.nativeTimestampSuppressed = (diagnostics.nativeTimestampSuppressed || 0) + 1;
          diagnostics.lastSource = coverRecord.source;
          r94SyncDiagnostics();
          return;
        }

        // R94_NATIVE_TIMESTAMP_VISIBILITY_GATE_RUNTIME
        // Only a genuinely visible native timestamp that already satisfies the
        // full format owns the final timestamp. A mounted-but-hidden short
        // native node must not suppress the generic full-date overlay path.
        if (nativeVisibilityGate && nativeAlreadyFull) {
          r94RemoveTurnBadge(turn);
          r94SuppressNativeFinalSegmentBadge(turn);
          diagnostics.nativeTimestampSuppressed = (diagnostics.nativeTimestampSuppressed || 0) + 1;
          diagnostics.lastSource = exact.record.source || '';
          r94SyncDiagnostics();
          return;
        }
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

    function r94TrimSegmentCache() {
      while (segmentTimeByKey.size > R94_SEGMENT_CACHE_LIMIT) {
        const oldest = segmentTimeByKey.keys().next().value;
        if (oldest == null) break;
        segmentTimeByKey.delete(oldest);
      }
    }

    function r94SegmentIsNativeFinal(segment, turn) {
      if (!(segment instanceof Element) || !(turn instanceof Element)) return false;
      if (segment.matches('[data-local-conversation-final-assistant]')) return true;
      const native = turn.querySelector(R94_NATIVE_TIME_SELECTOR);
      if (!(native instanceof Element)) return false;
      return segment === native || segment.contains(native);
    }

    function r94SuppressNativeFinalSegmentBadge(turn) {
      if (!(turn instanceof Element)) return;
      const segments = r94TopLevelSegments(turn);
      if (!segments.length) return;
      const explicitFinal = turn.querySelector('[data-local-conversation-final-assistant]');
      let target = null;
      if (explicitFinal instanceof Element) {
        target = segments.find(function(segment) {
          return segment === explicitFinal || segment.contains(explicitFinal) || explicitFinal.contains(segment);
        }) || null;
      }
      if (!(target instanceof Element)) target = segments[segments.length - 1] || null;
      if (!(target instanceof Element)) return;
      const entry = segmentEntryByNode.get(target);
      if (!entry) return;
      visibleSegmentEntries.delete(entry);
      if (entry.badge && entry.badge.isConnected) entry.badge.remove();
      entry.badge = null;
    }

    function r94BaselineTurnSegments(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      for (const segment of r94TopLevelSegments(turn)) {
        if (!(segment instanceof Element)) continue;
        baselineSegmentNodes.add(segment);
        const key = r94SegmentKey(segment, turn);
        if (key) baselineSegmentKeys.add(key);
      }
    }

    function r94BaselineCurrentSegments() {
      const candidates = [];
      const seen = new Set();
      for (const node of Array.from(document.querySelectorAll(R94_TURN_SELECTOR))) {
        const turn = r94CanonicalTurn(node);
        if (!(turn instanceof Element) || seen.has(turn) || insideComposer(turn) || r94IsUserSurface(turn)) continue;
        seen.add(turn);
        candidates.push(turn);
      }
      // Current/near-current DOM is enough. Historical virtualization remains
      // protected by latest-turn + live-state gates below.
      for (const turn of candidates.slice(-12)) r94BaselineTurnSegments(turn);
    }

    function r94RememberLatestObservedTurn(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      latestObservedTurn = turn;
      const ids = r94IdsForTurn(turn);
      const threadId = String(ids && ids.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      if (threadId) latestObservedTurnByThread.set(threadId, turn);
    }

    function r94TurnIsLatest(turn) {
      const ids = r94IdsForTurn(turn);
      if (!ids) return false;
      const latest = ids.threadId ? capability.latestForThread(ids.threadId) : null;
      if (latest && latest.turnId) {
        const latestId = r94NormalizeTurnId(latest.turnId);
        if (latestId === ids.turnId) return true;
        const latestStatus = String(latest.status || '').toLowerCase();
        if (/inprogress|in_progress|running|started|pending/.test(latestStatus)) return false;
      }

      // R94_STREAMING_LATEST_OWNER_CACHE_RUNTIME
      // Retained as the compatibility contract name for the inherited r94
      // streaming-owner verifier. The implementation below is now per-thread.
      // R94_MULTI_PANE_LATEST_OWNER_CACHE_RUNTIME
      // Parent and sub-agent panes can stream concurrently. Keep one mutation
      // owner per thread instead of letting the last mutation in either pane
      // steal "latest turn" ownership from the other pane.
      const threadId = String(ids.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const scoped = threadId ? latestObservedTurnByThread.get(threadId) : null;
      const candidate = scoped instanceof Element ? scoped : latestObservedTurn;
      return !!(
        candidate instanceof Element &&
        candidate.isConnected &&
        (candidate === turn || candidate.contains(turn) || turn.contains(candidate))
      );
    }

    function r94ActiveGenerationCached(turn) {
      const now = performance.now();
      const cached = generationUiCache.get(turn);
      if (cached && now - cached.at < 750) return cached.value;
      const value = r94ActiveGenerationUiPresentFor(turn);
      generationUiCache.set(turn, { at: now, value });
      return value;
    }

    function r94TurnIsLive(turn) {
      const ids = r94IdsForTurn(turn);
      if (!ids) return false;
      const record = capability.getRecord(ids.threadId, ids.turnId);
      const status = String(record && record.status || '').toLowerCase();
      if (/inprogress|in_progress|running|started|pending/.test(status)) return true;
      if (/completed|failed|interrupted|cancelled|canceled/.test(status)) return false;

      const idsThread = String(ids.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const exactByThread = state.metrics && state.metrics.r94ExternalExactByThread;
      const scopedExact = idsThread && exactByThread instanceof Map ? exactByThread.get(idsThread) : null;
      const scopedUpdated = Number(scopedExact && scopedExact.updatedAt);
      if (Number.isFinite(scopedUpdated) && scopedUpdated > 0) {
        const age = r94HostEpochNow() - scopedUpdated;
        if (age >= -5000 && age <= 90000) return true;
      }

      // Backward-compatible single-pane fallback only. In split view the last
      // envelope may belong to a sub-agent, so a process-global externalThreadId
      // must never suppress or activate another pane.
      if (r94KnownPaneThreadIds().length <= 1) {
        const externalThread = String(state.metrics && state.metrics.externalThreadId || '').replace(/^local:/i, '').trim().toLowerCase();
        if (externalThread && idsThread && externalThread !== idsThread) return false;
        const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
        if (Number.isFinite(updated) && updated > 0) {
          const age = r94HostEpochNow() - updated;
          if (age >= -5000 && age <= 90000) return true;
        }
      }

      // DOM-wide control/busy scans are the expensive fallback. Cache them so
      // streaming childList bursts cannot run them every frame.
      return r94ActiveGenerationCached(turn);
    }

    function r94EnsureSegmentEntry(segment, turn, key, epoch, source) {
      if (!(segment instanceof Element) || !segment.isConnected || !key || !Number.isFinite(epoch)) return;
      let entry = segmentEntryByNode.get(segment);
      const isNew = !entry;
      const wasExact = !!(entry && r94SegmentTimeIsExact(entry.source));
      if (!entry) {
        entry = { segment, turn, key, epoch, source, badge: null };
        segmentEntryByNode.set(segment, entry);
      } else {
        entry.turn = turn;
        entry.key = key;
        entry.epoch = epoch;
        entry.source = source;
      }
      const label = r94SegmentTimeLabel(epoch, source);
      const title = r94SegmentTimeTitle(epoch, source);
      if (!entry.badge || !entry.badge.isConnected) {
        entry.badge = r94CreateSegmentBadge(overlayRoot, epoch, source);
      } else {
        if (entry.badge.textContent !== label) entry.badge.textContent = label;
        if (entry.badge.title !== title) entry.badge.title = title;
      }
      visibleSegmentEntries.add(entry);
      diagnostics.lastLiveSegmentSource = source;
      if (r94SegmentTimeIsExact(source) && !wasExact) {
        diagnostics.exactItemBindings = (diagnostics.exactItemBindings || 0) + 1;
      }
      if (isNew || r94SegmentTimeIsExact(source)) {
        r94UpsertTimelineEntry(
          'segment:' + key,
          epoch,
          segment,
          r94TimelineKindForSegment(segment),
          !r94SegmentTimeIsExact(source),
          normalizedText(segment).slice(0,180)
        );
      }
    }

    function r94StampLiveSegments(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (!r94TurnIsLatest(turn)) return;

      const live = r94TurnIsLive(turn);
      const segments = r94TopLevelSegments(turn);
      for (const segment of segments) {
        if (!(segment instanceof Element) || !segment.isConnected || r94SegmentIsNativeFinal(segment, turn)) continue;
        const key = r94SegmentKey(segment, turn);
        if (!key) continue;

        // R94_ITEM_EXACT_TIMESTAMP_RUNTIME
        // Official app-server item lifecycle timestamps outrank local
        // first-observed time whenever the DOM surface exposes the same item id.
        const exactItem = r94ExactItemTimeForSurface(segment, turn, capability);
        if (exactItem && Number.isFinite(exactItem.epoch)) {
          segmentTimeByKey.delete(key);
          segmentTimeByKey.set(key, { epoch: exactItem.epoch, source: exactItem.source });
          r94TrimSegmentCache();
          r94EnsureSegmentEntry(segment, turn, key, exactItem.epoch, exactItem.source);
          continue;
        }

        // DOM wrappers can be reparented while an item streams. A concrete node
        // keeps the first timestamp assigned to that semantic output item.
        const existingEntry = segmentEntryByNode.get(segment);
        if (existingEntry && Number.isFinite(existingEntry.epoch)) {
          r94EnsureSegmentEntry(
            segment,
            turn,
            existingEntry.key || key,
            existingEntry.epoch,
            existingEntry.source || 'host-first-observed-live-node'
          );
          continue;
        }

        const cached = segmentTimeByKey.get(key);
        if (cached && Number.isFinite(cached.epoch)) {
          r94EnsureSegmentEntry(segment, turn, key, cached.epoch, cached.source || 'host-first-observed-live-cache');
          continue;
        }

        // Historical/remounted semantic items must never be assigned "now".
        // Only a genuinely live turn can receive an approximate host timestamp.
        if (!live || baselineSegmentNodes.has(segment) || baselineSegmentKeys.has(key)) continue;

        const epoch = r94HostEpochNow();
        const source = 'host-first-observed-live-output';
        segmentTimeByKey.delete(key);
        segmentTimeByKey.set(key, { epoch, source });
        r94TrimSegmentCache();
        diagnostics.liveSegmentsStamped = (diagnostics.liveSegmentsStamped || 0) + 1;
        r94EnsureSegmentEntry(segment, turn, key, epoch, source);
      }
      r94SyncDiagnostics();
      r94SchedulePosition();
    }

    function r94OrphanSemanticCandidates(root) {
      const element = root instanceof Element ? root : root && root.parentElement;
      if (!(element instanceof Element)) return [];
      const raw = [];
      const add = function(node) {
        if (!(node instanceof Element) || raw.includes(node)) return;
        raw.push(node);
      };

      if (element.matches(R94_SEMANTIC_OUTPUT_SELECTOR) || r94FallbackSemanticSignature(element)) add(element);
      element.querySelectorAll(R94_SEMANTIC_OUTPUT_SELECTOR).forEach(add);
      r94FallbackSemanticOutputSurfaces(element).forEach(add);

      const usable = raw.filter(function(node) {
        return node.isConnected &&
          isVisible(node) &&
          !r94CanonicalTurn(node) &&
          !insideComposer(node) &&
          !insideOwnUi(node) &&
          !r94IsUserSurface(node) &&
          (r94StrongSemanticOutputSurface(node) || !!r94FallbackSemanticSignature(node) || normalizedText(node).length >= 2);
      });

      // Keep the most specific semantic wrapper so one progress card does not
      // receive timestamps on both its outer shell and inner body.
      return usable.filter(function(node) {
        return !usable.some(function(other) {
          if (other === node || !node.contains(other)) return false;
          const nodeKind = r94SemanticKind(node);
          const otherKind = r94SemanticKind(other);
          return nodeKind === otherKind || otherKind !== 'assistant';
        });
      });
    }

    function r94OrphanNearComposer(node) {
      if (!(node instanceof Element)) return false;
      let pane = null;
      let composer = null;
      try {
        pane = typeof paneForNode === 'function' ? paneForNode(node) : null;
        composer = typeof composerForPane === 'function'
          ? composerForPane(pane)
          : (typeof findComposerRoot === 'function' ? findComposerRoot() : null);
      } catch {}
      if (!(composer instanceof Element) || !composer.isConnected) return false;
      let nodeRect = null;
      let composerRect = null;
      try {
        nodeRect = node.getBoundingClientRect();
        composerRect = composer.getBoundingClientRect();
      } catch {}
      if (!nodeRect || !composerRect || nodeRect.height <= 0 || composerRect.height <= 0) return false;
      // Live progress surfaces sit above/around their pane composer. A generous
      // bound keeps current long status groups while rejecting old virtualized
      // history that remounts far up the pane during another active turn.
      return nodeRect.bottom >= composerRect.top - Math.max(1400, innerHeight * 1.25) &&
        nodeRect.top <= composerRect.bottom + 160;
    }

    function r94StampOrphanSemanticRoot(root) {
      // R94_PANE_ORPHAN_SEMANTIC_TIMESTAMP_RUNTIME
      for (const segment of r94OrphanSemanticCandidates(root)) {
        if (orphanSegmentNodes.has(segment) || !r94OrphanNearComposer(segment)) continue;

        const threadId = String(r94ThreadIdForNode(segment) || '').replace(/^local:/i, '').trim().toLowerCase();
        if (!threadId) continue;
        const latest = capability.latestForThread(threadId);
        const turnId = r94NormalizeTurnId(latest && latest.turnId);
        if (!turnId) continue;

        const status = String(latest && latest.status || '').toLowerCase();
        if (/completed|failed|interrupted|cancelled|canceled/.test(status)) continue;
        const live = /inprogress|in_progress|running|started|pending/.test(status) ||
          r94ActiveGenerationUiPresentFor(segment);
        if (!live) continue;

        let epoch = null;
        let source = '';
        const itemId = r94DirectItemIdForSurface(segment) || r94ItemIdForSurface(segment);
        if (itemId && typeof capability.getItemRecord === 'function') {
          const itemRecord = capability.getItemRecord(threadId, turnId, itemId);
          const started = Number(itemRecord && itemRecord.startedAtMs);
          const completed = Number(itemRecord && itemRecord.completedAtMs);
          if (Number.isFinite(started) && started > 0) {
            epoch = started;
            source = 'item/started';
          } else if (Number.isFinite(completed) && completed > 0) {
            epoch = completed;
            source = 'item/completed';
          }
        }
        if (!Number.isFinite(epoch)) {
          epoch = r94HostEpochNow();
          source = 'host-first-observed-live-orphan-output';
        }

        const pane = typeof paneForNode === 'function' ? paneForNode(segment) : null;
        const key = 'orphan:' + r94Hash(
          threadId + '|' + turnId + '|' +
          r94StructuralPath(segment, pane instanceof Element ? pane : document.body) + '|' +
          r94SemanticKind(segment)
        );
        if (!key) continue;

        orphanSegmentNodes.add(segment);
        segmentTimeByKey.delete(key);
        segmentTimeByKey.set(key, { epoch, source });
        r94TrimSegmentCache();
        diagnostics.liveSegmentsStamped = (diagnostics.liveSegmentsStamped || 0) + 1;
        diagnostics.orphanSegmentsStamped = (diagnostics.orphanSegmentsStamped || 0) + 1;
        r94EnsureSegmentEntry(segment, segment, key, epoch, source);
      }
    }

    function r94FlushSegmentTurns() {
      segmentTimerId = 0;
      const turns = Array.from(pendingSegmentTurns);
      pendingSegmentTurns.clear();
      latestObservedTurnByThread.clear();
      for (const turn of turns) {
        if (turn instanceof Element && turn.isConnected) r94StampLiveSegments(turn);
      }
    }

    function r94ScheduleSegmentTurn(turn) {
      // R94_STREAMING_SEGMENT_THROTTLE_RUNTIME
      // One semantic-output scan per ~220ms is plenty for human-visible
      // timestamps and avoids rescanning a long response every animation frame.
      if (disposed || document.visibilityState === 'hidden' || !(turn instanceof Element)) return;
      pendingSegmentTurns.add(turn);
      if (!segmentTimerId) segmentTimerId = window.setTimeout(r94FlushSegmentTurns, 220);
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
        if (!rect || rect.width <= 0 || rect.height <= 0 ||
            rect.right <= 0 || rect.left >= innerWidth ||
            rect.bottom <= 0 || rect.top >= innerHeight) {
          entry.badge.style.display = 'none';
          continue;
        }

        const nativeTimeCover = entry.mode === 'native-time-cover';
        const x = Math.max(12, Math.min(innerWidth - 6, nativeTimeCover ? rect.right : (rect.right - 3)));
        const rawY = nativeTimeCover
          ? rect.top
          : (entry.mode === 'action-row' ? (rect.top - 2) : (rect.bottom - 2));
        // R94_NO_VIEWPORT_EDGE_PINNING_RUNTIME
        // Never clamp an offscreen anchor onto the viewport edge. That behavior
        // caused dozens of unrelated timestamps to pile up at the top/bottom
        // while one very tall turn remained intersecting.
        if (rawY < 8 || rawY > innerHeight - 8) {
          entry.badge.style.display = 'none';
          continue;
        }
        writes.push({ entry, x, y: rawY, nativeTimeCover });
      }

      for (const entry of Array.from(visibleSegmentEntries)) {
        if (!entry.segment || !entry.segment.isConnected || !entry.badge || !entry.badge.isConnected) {
          visibleSegmentEntries.delete(entry);
          continue;
        }
        let rect;
        try { rect = entry.segment.getBoundingClientRect(); } catch { rect = null; }
        if (!rect || rect.width <= 0 || rect.height <= 0 ||
            rect.right <= 0 || rect.left >= innerWidth) {
          entry.badge.style.display = 'none';
          continue;
        }
        const x = Math.max(12, Math.min(innerWidth - 10, rect.right - 3));
        const rawY = rect.bottom + 2;
        // Do not pin semantic-item timestamps to viewport edges. If the actual
        // item boundary is not visible, its timestamp is hidden until that
        // boundary scrolls into view.
        if (rawY < 8 || rawY > innerHeight - 8) {
          entry.badge.style.display = 'none';
          continue;
        }
        writes.push({ entry, x, y: rawY, segment: true });
      }

      for (const item of writes) {
        const badge = item.entry.badge;
        badge.style.display = 'block';
        badge.style.transform = item.segment
          ? ('translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,0)')
          : (item.nativeTimeCover
            ? ('translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,0)')
            : ('translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,-100%)'));
      }
      r94PositionTimelineRail();
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
        r94RemoveUserBadge(turn);
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
      if (!(element instanceof Element) ||
          element.closest('#' + R94_OVERLAY_ID) ||
          element.closest('#' + R94_TIMELINE_RAIL_ID)) return;

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
            (mutationTarget.id === R94_OVERLAY_ID ||
             mutationTarget.id === R94_TIMELINE_RAIL_ID ||
             mutationTarget.closest('#' + R94_OVERLAY_ID) ||
             mutationTarget.closest('#' + R94_TIMELINE_RAIL_ID))) {
          continue;
        }
        if (record.removedNodes && record.removedNodes.length) removed = true;
        for (const added of record.addedNodes || []) {
          const element = added instanceof Element ? added : added && added.parentElement;
          if (!(element instanceof Element) ||
              element.closest('#' + R94_OVERLAY_ID) ||
              element.closest('#' + R94_TIMELINE_RAIL_ID)) continue;

          // Current Codex Desktop can render progress/agent output as pane-level
          // siblings of canonical turn wrappers. Timestamp those newly-added
          // live semantic surfaces before the canonical-turn fast path.
          try { r94StampOrphanSemanticRoot(element); } catch {}

          const owner = r94CanonicalTurn(element);
          if (owner) {
            r94RememberLatestObservedTurn(owner);
            r94ScheduleScan(owner);
            r94ScheduleSegmentTurn(owner);
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
      for (const entry of Array.from(visibleSegmentEntries)) {
        if (entry.badge && entry.badge.isConnected) entry.badge.remove();
        entry.badge = null;
      }
      visibleEntries.clear();
      visibleSegmentEntries.clear();
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
        r94RememberLatestObservedTurn(turn);
        r94RefreshTurn(turn);
        r94ScheduleSegmentTurn(turn);
      }
    }

    function r94HandleVisibility() {
      if (document.visibilityState === 'hidden') {
        overlayRoot.hidden = true;
        if (timelineRail instanceof HTMLElement) timelineRail.hidden = true;
        r94StopMutationObservation();
        if (intersectionObserver) intersectionObserver.disconnect();
        if (resizeObserver) resizeObserver.disconnect();
        if (scanFrameId) cancelAnimationFrame(scanFrameId);
        if (segmentFrameId) cancelAnimationFrame(segmentFrameId);
        if (segmentTimerId) clearTimeout(segmentTimerId);
        scanFrameId = 0;
        segmentFrameId = 0;
        segmentTimerId = 0;
        pendingRoots.clear();
        pendingSegmentTurns.clear();
        r94ClearVisibleBadges();
        return;
      }

      overlayRoot.hidden = false;
      if (timelineRail instanceof HTMLElement) timelineRail.hidden = false;
      r94StartMutationObservation();
      if (intersectionObserver) {
        for (const turn of Array.from(observedTurns)) {
          if (turn.isConnected) intersectionObserver.observe(turn);
        }
      }
      r94ScheduleScan(document.documentElement);
      for (const turn of Array.from(observedTurns)) {
        if (turn.isConnected) r94ScheduleSegmentTurn(turn);
      }
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
      if (segmentFrameId) cancelAnimationFrame(segmentFrameId);
      if (segmentTimerId) clearTimeout(segmentTimerId);
      window.removeEventListener('resize', r94SchedulePosition);
      window.removeEventListener('scroll', r94SchedulePosition, true);
      document.removeEventListener('visibilitychange', r94HandleVisibility);
      window.removeEventListener('cas-r94-turn-capability-update', r94HandleCapabilityUpdate);
      window.removeEventListener('cas-r94-item-capability-update', r94HandleCapabilityUpdate);
      pendingRoots.clear();
      pendingSegmentTurns.clear();
      observedTurns.clear();
      visibleTurns.clear();
      visibleEntries.clear();
      visibleSegmentEntries.clear();
      segmentTimeByKey.clear();
      baselineSegmentKeys.clear();
      timelineEntries.clear();
      timelineMarkers.clear();
      timelineActiveKey = '';
      capability.clear();
      if (overlayRoot.isConnected) overlayRoot.remove();
      if (timelineRail instanceof HTMLElement && timelineRail.isConnected) timelineRail.remove();
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
    window.addEventListener('cas-r94-item-capability-update', r94HandleCapabilityUpdate);

    r94BaselineCurrentSegments();
    r94StartMutationObservation();
    r94ScanRoot(document.documentElement);
    r94SchedulePosition();

    // r74 cleanup already calls state.observer.disconnect(). Expose one composed
    // controller so cleanup tears down Mutation/Intersection/Resize observers,
    // listeners, cache and the Transfer-owned overlay root in one operation.
    state.observer = { disconnect: r94Cleanup };
  }
