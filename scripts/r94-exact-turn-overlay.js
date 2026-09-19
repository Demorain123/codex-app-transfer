// R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME
// R94_EXACT_TURN_CAPABILITY_RUNTIME
// Exact-only, one-timestamp-per-turn renderer.
// Native Codex conversation DOM is treated as read-only: this module never
// inserts children into a turn/action row and never writes timestamp attrs.

  const R94_OVERLAY_ID = 'cas-r94-timestamp-overlay';
  const R94_BADGE_CLASS = 'cas-r94-turn-time';
  const R94_TURN_SELECTOR = '[data-turn-key],[data-content-search-turn-key],[data-content-search-assistant-turn-key],[data-chatgpt-conversation-turn="true"]';
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
    const latestKeyByThread = new Map();
    let capabilitySequence = 0;

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
      current.capabilitySequence = ++capabilitySequence;
      if (ids.threadId) latestKeyByThread.set(ids.threadId, ids.key);
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
      latestKeyByThread.clear();
      capabilitySequence = 0;
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

  function r94NativeTimestampVisible(node) {
    if (!r94AnchorUsable(node)) return false;
    try {
      const style = getComputedStyle(node);
      if (!style || style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
      const opacity = Number(style.opacity);
      if (Number.isFinite(opacity) && opacity <= 0.05) return false;
      return !!r94CleanTimeText(node.textContent || node.getAttribute('aria-label') || node.getAttribute('title'));
    } catch {
      return true;
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
    try {
      const origin = Number(performance && performance.timeOrigin);
      const offset = Number(performance && typeof performance.now === 'function' ? performance.now() : NaN);
      if (Number.isFinite(origin) && Number.isFinite(offset) && origin > 0) return origin + offset;
    } catch {}
    return new Date().getTime();
  }

  function r94IsUserSurface(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return false;
    return !!element.closest('[data-message-author-role="user"],[data-message-author="user"]');
  }

  function r94StrongSemanticOutputSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-local-conversation-final-assistant]')) return true;
    return node.matches('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
  }

  function r94DirectVisualChildren(parent) {
    if (!(parent instanceof Element)) return [];
    return Array.from(parent.children || []).filter(function(child) {
      if (!(child instanceof Element) || !isVisible(child)) return false;
      if (child.closest('#' + R94_OVERLAY_ID)) return false;
      if (insideComposer(child) || insideOwnUi(child) || r94IsUserSurface(child)) return false;
      return normalizedText(child).length >= 2 || r94StrongSemanticOutputSurface(child);
    });
  }

  function r94AtomicTextSurface(node) {
    if (!(node instanceof Element)) return false;
    if (r94StrongSemanticOutputSurface(node)) return true;
    const tag = String(node.tagName || '').toLowerCase();
    return ['p','li','pre','blockquote','table','tr','details','summary'].includes(tag);
  }

  function r94VerticalRowCount(children) {
    const rects = [];
    for (const child of children) {
      if (!(child instanceof Element) || !isVisible(child)) continue;
      try {
        const rect = child.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        rects.push({ top: rect.top, bottom: rect.bottom });
      } catch {}
    }
    rects.sort(function(a,b) { return a.top - b.top; });
    if (!rects.length) return 0;
    let rows = 1;
    let bottom = rects[0].bottom;
    for (let i = 1; i < rects.length; i += 1) {
      const rect = rects[i];
      if (rect.top > bottom + 2) rows += 1;
      bottom = Math.max(bottom, rect.bottom);
    }
    return rows;
  }

  function r94CollectVisualSegments(node, root, depth) {
    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node) || r94IsUserSurface(node)) return [];
    if (normalizedText(node).length < 2 && !r94StrongSemanticOutputSurface(node)) return [];
    if (node.matches('[data-local-conversation-final-assistant]')) return [node];
    if (r94AtomicTextSurface(node)) return [node];
    if (depth >= 12) return [node];

    const semantic = node.closest('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
    if (semantic instanceof Element && semantic !== root && root instanceof Element && root.contains(semantic)) {
      let owner = semantic;
      let parent = semantic.parentElement;
      while (parent instanceof Element && parent !== root) {
        if (r94StrongSemanticOutputSurface(parent)) owner = parent;
        parent = parent.parentElement;
      }
      if (owner === node || node.contains(owner)) return [owner];
    }

    const children = r94DirectVisualChildren(node);
    if (!children.length) return [node];
    if (children.length === 1) return r94CollectVisualSegments(children[0], root, depth + 1);
    if (r94VerticalRowCount(children) < 2) return [node];

    const out = [];
    for (const child of children) {
      const nested = r94CollectVisualSegments(child, root, depth + 1);
      for (const item of nested) out.push(item);
    }
    return out.length ? out : [node];
  }

  function r94TopLevelSegments(turn) {
    if (!(turn instanceof Element)) return [];
    let candidates = [];
    const direct = r94DirectVisualChildren(turn);
    if (!direct.length) candidates = r94CollectVisualSegments(turn, turn, 0);
    else {
      for (const child of direct) {
        const nested = r94CollectVisualSegments(child, turn, 0);
        for (const item of nested) candidates.push(item);
      }
    }

    const unique = [];
    const seen = new Set();
    for (const candidate of candidates) {
      if (!(candidate instanceof Element) || seen.has(candidate)) continue;
      if (!turn.contains(candidate) && candidate !== turn) continue;
      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate) || r94IsUserSurface(candidate)) continue;
      if (normalizedText(candidate).length < 2 && !r94StrongSemanticOutputSurface(candidate)) continue;
      seen.add(candidate);
      unique.push(candidate);
    }
    return unique;
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
      segment.getAttribute('data-message-id') ||
      segment.getAttribute('data-testid') ||
      segment.getAttribute('role') || '';
    const tag = String(segment.tagName || '').toLowerCase();
    // Do not hash mutable text. Streaming text changes must keep one stable
    // first-observed timestamp for the same visual block.
    return r94Hash(rootId + '|' + r94StructuralPath(segment, turn) + '|' + semanticId + '|' + tag);
  }

  function r94CreateSegmentBadge(root, epoch) {
    const badge = document.createElement('div');
    badge.className = R94_SEGMENT_BADGE_CLASS;
    badge.setAttribute('aria-hidden','true');
    badge.textContent = '≈' + clock(epoch);
    badge.title = fullTime(epoch) + ' · approximate: first observed locally while this output block was live';
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
    const capability = r94CreateCapability();
    state.r94TimestampCapability = capability;
    window.__casR94TurnCapability = capability;

    const diagnostics = {
      exactOnly: false,
      hybridSegmentMode: true,
      observedTurns: 0,
      visibleTurns: 0,
      badges: 0,
      cacheSize: 0,
      liveSegmentsStamped: 0,
      liveSegmentBadges: 0,
      liveSegmentCache: 0,
      lastSource: '',
      lastLiveSegmentSource: '',
      nativeTimestampSuppressed: 0,
    };
    window.__casR94TimestampDiagnostics = diagnostics;

    const observedTurns = new Set();
    const visibleTurns = new Set();
    const pendingRoots = new Set();
    const entryByTurn = new WeakMap();
    const visibleEntries = new Set();

    // Live per-output timestamp state. Existing DOM is baselined at install so
    // only blocks first appearing during an actually-live turn receive ≈ time.
    const baselineSegmentNodes = new WeakSet();
    const baselineSegmentKeys = new Set();
    const segmentTimeByKey = new Map();
    const segmentEntryByNode = new WeakMap();
    const visibleSegmentEntries = new Set();
    const pendingSegmentTurns = new Set();

    let disposed = false;
    let mutationObserver = null;
    let frameId = 0;
    let scanFrameId = 0;
    let segmentFrameId = 0;

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
      diagnostics.liveSegmentBadges = visibleSegmentEntries.size;
      diagnostics.liveSegmentCache = segmentTimeByKey.size;
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

      if (exact.sourceElement instanceof Element && exact.sourceElement.isConnected) {
        // Codex owns final/user sent-time UI even when it is hover-revealed.
        // Never duplicate that native timestamp with a Transfer turn badge.
        r94RemoveTurnBadge(turn);
        r94SuppressNativeFinalSegmentBadge(turn);
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

    function r94TurnIsLatest(turn) {
      const ids = r94IdsForTurn(turn);
      if (!ids) return false;
      const latest = ids.threadId ? capability.latestForThread(ids.threadId) : null;
      if (latest && latest.turnId) {
        const latestId = r94NormalizeTurnId(latest.turnId);
        if (latestId === ids.turnId) return true;
        const latestStatus = String(latest.status || '').toLowerCase();
        // While capability says another turn is actively running, do not stamp
        // this turn. If the capability is merely a completed old turn, allow
        // DOM live-tail evidence to bridge the brief turn/started race.
        if (/inprogress|in_progress|running|started|pending/.test(latestStatus)) return false;
      }
      const domLatest = r94LatestVisibleAssistantTurnFor(turn);
      return !!(domLatest && (domLatest === turn || domLatest.contains(turn) || turn.contains(domLatest)));
    }

    function r94TurnIsLive(turn) {
      const ids = r94IdsForTurn(turn);
      if (!ids) return false;
      const record = capability.getRecord(ids.threadId, ids.turnId);
      const status = String(record && record.status || '').toLowerCase();
      if (/inprogress|in_progress|running|started|pending/.test(status)) return true;
      if (/completed|failed|interrupted|cancelled|canceled/.test(status)) return false;
      if (r94ActiveGenerationUiPresentFor(turn)) return true;

      const externalThread = String(state.metrics && state.metrics.externalThreadId || '').replace(/^local:/i, '').trim().toLowerCase();
      const idsThread = String(ids.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
      if (externalThread && idsThread && externalThread !== idsThread) return false;
      const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
      if (!Number.isFinite(updated) || updated <= 0) return false;
      const age = r94HostEpochNow() - updated;
      return age >= -5000 && age <= 90000;
    }

    function r94EnsureSegmentEntry(segment, turn, key, epoch, source) {
      if (!(segment instanceof Element) || !segment.isConnected || !key || !Number.isFinite(epoch)) return;
      let entry = segmentEntryByNode.get(segment);
      if (!entry) {
        entry = { segment, turn, key, epoch, source, badge: null };
        segmentEntryByNode.set(segment, entry);
      } else {
        entry.turn = turn;
        entry.key = key;
        entry.epoch = epoch;
        entry.source = source;
      }
      if (!entry.badge || !entry.badge.isConnected) {
        entry.badge = r94CreateSegmentBadge(overlayRoot, epoch);
      }
      visibleSegmentEntries.add(entry);
      diagnostics.lastLiveSegmentSource = source;
    }

    function r94StampLiveSegments(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (!r94TurnIsLatest(turn) || !r94TurnIsLive(turn)) return;

      const segments = r94TopLevelSegments(turn);
      for (const segment of segments) {
        if (!(segment instanceof Element) || !segment.isConnected || r94SegmentIsNativeFinal(segment, turn)) continue;
        const key = r94SegmentKey(segment, turn);
        if (!key) continue;

        const cached = segmentTimeByKey.get(key);
        if (cached && Number.isFinite(cached.epoch)) {
          r94EnsureSegmentEntry(segment, turn, key, cached.epoch, cached.source || 'host-first-observed-live-cache');
          continue;
        }

        if (baselineSegmentNodes.has(segment) || baselineSegmentKeys.has(key)) continue;

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

    function r94FlushSegmentTurns() {
      segmentFrameId = 0;
      const turns = Array.from(pendingSegmentTurns);
      pendingSegmentTurns.clear();
      for (const turn of turns) {
        if (turn instanceof Element && turn.isConnected) r94StampLiveSegments(turn);
      }
    }

    function r94ScheduleSegmentTurn(turn) {
      if (disposed || document.visibilityState === 'hidden' || !(turn instanceof Element)) return;
      pendingSegmentTurns.add(turn);
      if (!segmentFrameId) segmentFrameId = requestAnimationFrame(r94FlushSegmentTurns);
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

      for (const entry of Array.from(visibleSegmentEntries)) {
        if (!entry.segment || !entry.segment.isConnected || !entry.badge || !entry.badge.isConnected) {
          visibleSegmentEntries.delete(entry);
          continue;
        }
        let rect;
        try { rect = entry.segment.getBoundingClientRect(); } catch { rect = null; }
        if (!rect || rect.width <= 0 || rect.height <= 0 || rect.bottom < -120 || rect.top > innerHeight + 120) {
          entry.badge.style.display = 'none';
          continue;
        }
        const x = Math.max(12, Math.min(innerWidth - 10, rect.right - 3));
        const y = Math.max(12, Math.min(innerHeight - 12, rect.bottom + 2));
        writes.push({ entry, x, y, segment: true });
      }

      for (const item of writes) {
        const badge = item.entry.badge;
        badge.style.display = 'block';
        badge.style.transform = item.segment
          ? ('translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,0)')
          : ('translate3d(' + item.x + 'px,' + item.y + 'px,0) translate(-100%,-100%)');
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
        r94RefreshTurn(turn);
        r94ScheduleSegmentTurn(turn);
      }
    }

    function r94HandleVisibility() {
      if (document.visibilityState === 'hidden') {
        overlayRoot.hidden = true;
        r94StopMutationObservation();
        if (intersectionObserver) intersectionObserver.disconnect();
        if (resizeObserver) resizeObserver.disconnect();
        if (scanFrameId) cancelAnimationFrame(scanFrameId);
        if (segmentFrameId) cancelAnimationFrame(segmentFrameId);
        scanFrameId = 0;
        segmentFrameId = 0;
        pendingRoots.clear();
        pendingSegmentTurns.clear();
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
      window.removeEventListener('resize', r94SchedulePosition);
      window.removeEventListener('scroll', r94SchedulePosition, true);
      document.removeEventListener('visibilitychange', r94HandleVisibility);
      window.removeEventListener('cas-r94-turn-capability-update', r94HandleCapabilityUpdate);
      pendingRoots.clear();
      pendingSegmentTurns.clear();
      observedTurns.clear();
      visibleTurns.clear();
      visibleEntries.clear();
      visibleSegmentEntries.clear();
      segmentTimeByKey.clear();
      baselineSegmentKeys.clear();
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

    r94BaselineCurrentSegments();
    r94StartMutationObservation();
    r94ScanRoot(document.documentElement);
    r94SchedulePosition();

    // r74 cleanup already calls state.observer.disconnect(). Expose one composed
    // controller so cleanup tears down Mutation/Intersection/Resize observers,
    // listeners, cache and the Transfer-owned overlay root in one operation.
    state.observer = { disconnect: r94Cleanup };
  }
