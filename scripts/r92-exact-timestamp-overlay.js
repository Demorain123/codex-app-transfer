// R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME
// Exact-only, one-timestamp-per-turn renderer.
// Native Codex conversation DOM is treated as read-only: this module never
// inserts children into a turn/action row and never writes timestamp attrs.

  const R92_OVERLAY_ID = 'cas-r92-timestamp-overlay';
  const R92_BADGE_CLASS = 'cas-r92-turn-time';
  const R92_TURN_SELECTOR = '[data-turn-key],[data-content-search-turn-key]';
  const R92_FINAL_SELECTOR = '[data-local-conversation-final-assistant],[data-content-search-assistant-turn-key],[data-message-author-role="assistant"]';
  const R92_NATIVE_TIME_SELECTOR = '[data-assistant-message-sent-time],time[datetime]';
  const R92_HISTORY_TURN_PREFIX = 'history-content:turn:';
  const R92_LOCAL_THREAD_PREFIX = 'local:';
  const R92_CACHE_LIMIT = 512;
  const R92_MAX_PENDING_SCAN_ROOTS = 64;

  function r92Decode(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    try { return decodeURIComponent(text); } catch { return text; }
  }

  function r92CurrentThreadId() {
    const pathname = String(location && location.pathname || '');
    const patterns = [
      /\/local\/([^/?#]+)/,
      /\/hotkey-window\/thread\/([^/?#]+)/,
      /\/thread\/([^/?#]+)/,
      /\/conversation\/([^/?#]+)/,
    ];
    for (const pattern of patterns) {
      const match = pattern.exec(pathname);
      if (match && match[1]) return r92Decode(match[1]);
    }
    const active = document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active="true"]');
    const raw = String(active && active.getAttribute('data-app-action-sidebar-thread-id') || '');
    if (raw.startsWith(R92_LOCAL_THREAD_PREFIX)) return r92Decode(raw.slice(R92_LOCAL_THREAD_PREFIX.length));
    return '';
  }

  function r92NormalizeTurnId(value) {
    let raw = r92Decode(value);
    if (!raw) return '';
    if (raw.startsWith(R92_HISTORY_TURN_PREFIX)) raw = raw.slice(R92_HISTORY_TURN_PREFIX.length);
    const uuid = raw.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    if (uuid) return uuid[0];
    if (/^(turn-index-|expanded-review-composer-preview|:)/i.test(raw)) return '';
    return raw;
  }

  function r92CanonicalTurn(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return null;
    const keyed = element.closest('[data-turn-key]');
    if (keyed instanceof Element) return keyed;
    const searched = element.closest('[data-content-search-turn-key]');
    return searched instanceof Element ? searched : null;
  }

  function r92IdsForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const rawTurn =
      turn.getAttribute('data-turn-key') ||
      turn.getAttribute('data-content-search-turn-key') ||
      '';
    const turnId = r92NormalizeTurnId(rawTurn);
    if (!turnId) return null;
    const threadId = r92CurrentThreadId();
    return {
      threadId: threadId || null,
      turnId,
      key: (threadId || '__unknown_thread__') + '\u0000' + turnId,
    };
  }

  function r92CleanTimeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function r92TimeRecordFromElement(node) {
    if (!(node instanceof Element)) return null;
    if (node.closest('[data-message-author-role="user"],[data-message-author="user"]')) return null;

    const candidates = [
      node.getAttribute('datetime'),
      node.getAttribute('data-timestamp'),
      node.getAttribute('title'),
      node.getAttribute('aria-label'),
      node.textContent,
    ].map(r92CleanTimeText).filter(Boolean);

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
        const label = r92CleanTimeText(timeMatch[1]).replace(/\s+(am|pm)$/i, ' $1').toUpperCase();
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

  function r92NativeExactForTurn(turn) {
    if (!(turn instanceof Element)) return null;
    const nodes = Array.from(turn.querySelectorAll(R92_NATIVE_TIME_SELECTOR))
      .filter(function(node) {
        return node instanceof Element &&
          !node.closest('[data-message-author-role="user"],[data-message-author="user"]');
      });
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const record = r92TimeRecordFromElement(nodes[index]);
      if (record) return { record, sourceElement: nodes[index] };
    }
    return null;
  }

  function r92TrimCache(cache) {
    while (cache.size > R92_CACHE_LIMIT) {
      const oldest = cache.keys().next().value;
      if (oldest == null) break;
      cache.delete(oldest);
    }
  }

  function r92CreateCapability() {
    const exactByKey = new Map();

    function remember(ids, record) {
      if (!ids || !ids.key || !record || !record.label) return record || null;
      exactByKey.delete(ids.key);
      exactByKey.set(ids.key, {
        epoch: Number.isFinite(record.epoch) ? record.epoch : null,
        label: String(record.label),
        title: String(record.title || record.label),
        source: String(record.source || 'exact'),
      });
      r92TrimCache(exactByKey);
      return exactByKey.get(ids.key);
    }

    function getForTurn(turn, ids) {
      const native = r92NativeExactForTurn(turn);
      if (native && native.record) {
        return {
          record: remember(ids, native.record),
          sourceElement: native.sourceElement,
        };
      }
      const cached = ids && exactByKey.get(ids.key);
      return cached ? { record: cached, sourceElement: null } : null;
    }

    function clear() {
      exactByKey.clear();
    }

    return Object.freeze({
      getForTurn,
      remember,
      clear,
      size: function() { return exactByKey.size; },
    });
  }

  function r92EnsureOverlayRoot() {
    let root = document.getElementById(R92_OVERLAY_ID);
    if (root instanceof HTMLElement) return root;
    root = document.createElement('div');
    root.id = R92_OVERLAY_ID;
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

  function r92CreateBadge(root, record) {
    const badge = document.createElement('div');
    badge.className = R92_BADGE_CLASS;
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

  function r92AnchorForTurn(turn, sourceElement) {
    if (!(turn instanceof Element)) return null;
    if (sourceElement instanceof Element && sourceElement.isConnected) {
      const row = sourceElement.parentElement;
      if (row instanceof Element) return { node: row, mode: 'action-row' };
      return { node: sourceElement, mode: 'action-row' };
    }
    const final = turn.querySelector(R92_FINAL_SELECTOR);
    if (final instanceof Element) return { node: final, mode: 'final' };
    return { node: turn, mode: 'final' };
  }

  function installOutputObserver() {
    if (!document.body) {
      setTimeout(installOutputObserver, 120);
      return;
    }

    const overlayRoot = r92EnsureOverlayRoot();
    const capability = r92CreateCapability();
    state.r92TimestampCapability = capability;

    const diagnostics = {
      exactOnly: true,
      observedTurns: 0,
      visibleTurns: 0,
      badges: 0,
      cacheSize: 0,
      lastSource: '',
    };
    window.__casR92TimestampDiagnostics = diagnostics;

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
      ? new ResizeObserver(function() { r92SchedulePosition(); })
      : null;

    const intersectionObserver = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver(function(entries) {
          for (const entry of entries) {
            const turn = entry.target;
            if (!(turn instanceof Element)) continue;
            if (entry.isIntersecting) {
              visibleTurns.add(turn);
              if (resizeObserver) resizeObserver.observe(turn);
              r92RefreshTurn(turn);
            } else {
              visibleTurns.delete(turn);
              if (resizeObserver) resizeObserver.unobserve(turn);
              r92RemoveTurnBadge(turn);
            }
          }
          r92SyncDiagnostics();
          r92SchedulePosition();
        }, { root: null, rootMargin: '120px 0px 120px 0px', threshold: 0 })
      : null;

    function r92SyncDiagnostics() {
      diagnostics.observedTurns = observedTurns.size;
      diagnostics.visibleTurns = visibleTurns.size;
      diagnostics.badges = visibleEntries.size;
      diagnostics.cacheSize = capability.size();
    }

    function r92RemoveTurnBadge(turn) {
      const entry = entryByTurn.get(turn);
      if (!entry) return;
      visibleEntries.delete(entry);
      if (entry.badge && entry.badge.isConnected) entry.badge.remove();
      entry.badge = null;
    }

    function r92EnsureTurnBadge(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      const ids = r92IdsForTurn(turn);
      if (!ids) return;
      const exact = capability.getForTurn(turn, ids);
      if (!exact || !exact.record || !exact.record.label) {
        r92RemoveTurnBadge(turn);
        return;
      }

      let entry = entryByTurn.get(turn);
      const anchor = r92AnchorForTurn(turn, exact.sourceElement);
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
        entry.badge = r92CreateBadge(overlayRoot, exact.record);
      } else if (entry.badge.textContent !== exact.record.label) {
        entry.badge.textContent = exact.record.label;
        entry.badge.title = exact.record.title || exact.record.label;
      }

      visibleEntries.add(entry);
      diagnostics.lastSource = exact.record.source || '';
      r92SyncDiagnostics();
    }

    function r92RefreshTurn(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (intersectionObserver && !visibleTurns.has(turn)) return;
      r92EnsureTurnBadge(turn);
      r92SchedulePosition();
    }

    function r92PositionVisible() {
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
      r92SyncDiagnostics();
    }

    function r92SchedulePosition() {
      if (disposed || frameId || document.visibilityState === 'hidden') return;
      frameId = requestAnimationFrame(r92PositionVisible);
    }

    function r92ObserveTurn(turn) {
      if (!(turn instanceof Element) || !turn.isConnected) return;
      if (turn.closest('#' + R92_OVERLAY_ID)) return;
      if (insideComposer(turn) || insideOwnUi(turn)) return;
      const ids = r92IdsForTurn(turn);
      if (!ids) return;

      if (!observedTurns.has(turn)) {
        observedTurns.add(turn);
        if (intersectionObserver) {
          intersectionObserver.observe(turn);
        } else {
          visibleTurns.add(turn);
          r92RefreshTurn(turn);
        }
      } else if (!intersectionObserver || visibleTurns.has(turn)) {
        r92RefreshTurn(turn);
      }
    }

    function r92ScanRoot(root) {
      if (disposed || !root || document.visibilityState === 'hidden') return;
      const element = root instanceof Element ? root : root.parentElement;
      if (!(element instanceof Element)) return;

      const seen = new Set();
      const add = function(candidate) {
        const turn = r92CanonicalTurn(candidate);
        if (!(turn instanceof Element) || seen.has(turn)) return;
        seen.add(turn);
        r92ObserveTurn(turn);
      };

      if (element.matches(R92_TURN_SELECTOR)) add(element);
      const closest = r92CanonicalTurn(element);
      if (closest) add(closest);
      element.querySelectorAll(R92_TURN_SELECTOR).forEach(add);
    }

    function r92PruneDisconnected() {
      for (const turn of Array.from(observedTurns)) {
        if (turn.isConnected) continue;
        observedTurns.delete(turn);
        visibleTurns.delete(turn);
        if (intersectionObserver) intersectionObserver.unobserve(turn);
        if (resizeObserver) resizeObserver.unobserve(turn);
        r92RemoveTurnBadge(turn);
      }
      r92SyncDiagnostics();
    }

    function r92FlushScans() {
      scanFrameId = 0;
      r92PruneDisconnected();
      const roots = Array.from(pendingRoots);
      pendingRoots.clear();
      for (const root of roots) {
        if (root && root.isConnected) r92ScanRoot(root);
      }
    }

    function r92ScheduleScan(root) {
      if (disposed || !root || document.visibilityState === 'hidden') return;
      const element = root instanceof Element ? root : root.parentElement;
      if (!(element instanceof Element) || element.closest('#' + R92_OVERLAY_ID)) return;

      for (const existing of Array.from(pendingRoots)) {
        if (existing === element || existing.contains(element)) return;
        if (element.contains(existing)) pendingRoots.delete(existing);
      }
      pendingRoots.add(element);
      if (pendingRoots.size > R92_MAX_PENDING_SCAN_ROOTS) {
        pendingRoots.clear();
        pendingRoots.add(document.documentElement);
      }
      if (!scanFrameId) scanFrameId = requestAnimationFrame(r92FlushScans);
    }

    function r92HandleMutations(records) {
      if (disposed || document.visibilityState === 'hidden') return;
      let removed = false;
      for (const record of records) {
        if (record.type !== 'childList') continue;
        if (record.removedNodes && record.removedNodes.length) removed = true;
        for (const added of record.addedNodes || []) {
          const element = added instanceof Element ? added : added && added.parentElement;
          if (!(element instanceof Element) || element.closest('#' + R92_OVERLAY_ID)) continue;
          const owner = r92CanonicalTurn(element);
          if (owner) {
            r92ScheduleScan(owner);
            if (!intersectionObserver || visibleTurns.has(owner)) r92RefreshTurn(owner);
            continue;
          }
          if (element.matches(R92_TURN_SELECTOR) || element.querySelector(R92_TURN_SELECTOR)) {
            r92ScheduleScan(element);
          }
        }
      }
      if (removed) r92ScheduleScan(document.documentElement);
    }

    function r92StartMutationObservation() {
      if (mutationObserver || disposed || document.visibilityState === 'hidden') return;
      mutationObserver = new MutationObserver(r92HandleMutations);
      mutationObserver.observe(document.documentElement, { childList: true, subtree: true });
    }

    function r92StopMutationObservation() {
      if (!mutationObserver) return;
      mutationObserver.disconnect();
      mutationObserver = null;
    }

    function r92ClearVisibleBadges() {
      for (const entry of Array.from(visibleEntries)) {
        if (entry.badge && entry.badge.isConnected) entry.badge.remove();
        entry.badge = null;
      }
      visibleEntries.clear();
      visibleTurns.clear();
      r92SyncDiagnostics();
    }

    function r92HandleVisibility() {
      if (document.visibilityState === 'hidden') {
        overlayRoot.hidden = true;
        r92StopMutationObservation();
        if (intersectionObserver) intersectionObserver.disconnect();
        if (resizeObserver) resizeObserver.disconnect();
        if (scanFrameId) cancelAnimationFrame(scanFrameId);
        scanFrameId = 0;
        pendingRoots.clear();
        r92ClearVisibleBadges();
        return;
      }

      overlayRoot.hidden = false;
      r92StartMutationObservation();
      if (intersectionObserver) {
        for (const turn of Array.from(observedTurns)) {
          if (turn.isConnected) intersectionObserver.observe(turn);
        }
      }
      r92ScheduleScan(document.documentElement);
      r92SchedulePosition();
    }

    function r92Cleanup() {
      if (disposed) return;
      disposed = true;
      r92StopMutationObservation();
      if (intersectionObserver) intersectionObserver.disconnect();
      if (resizeObserver) resizeObserver.disconnect();
      if (frameId) cancelAnimationFrame(frameId);
      if (scanFrameId) cancelAnimationFrame(scanFrameId);
      window.removeEventListener('resize', r92SchedulePosition);
      window.removeEventListener('scroll', r92SchedulePosition, true);
      document.removeEventListener('visibilitychange', r92HandleVisibility);
      pendingRoots.clear();
      observedTurns.clear();
      visibleTurns.clear();
      visibleEntries.clear();
      capability.clear();
      if (overlayRoot.isConnected) overlayRoot.remove();
      if (window.__casR92TimestampDiagnostics === diagnostics) delete window.__casR92TimestampDiagnostics;
    }

    // Compatibility no-op: r75's old poll hook is removed by the r92 owner-layer
    // patch. Keeping this symbol prevents legacy generated checks from inventing
    // a fallback sweep; it intentionally does no timestamp work.
    function sweepOutputSegments() {}

    window.addEventListener('resize', r92SchedulePosition, { passive: true });
    window.addEventListener('scroll', r92SchedulePosition, { passive: true, capture: true });
    document.addEventListener('visibilitychange', r92HandleVisibility);

    r92StartMutationObservation();
    r92ScanRoot(document.documentElement);
    r92SchedulePosition();

    // r74 cleanup already calls state.observer.disconnect(). Expose one composed
    // controller so cleanup tears down Mutation/Intersection/Resize observers,
    // listeners, cache and the Transfer-owned overlay root in one operation.
    state.observer = { disconnect: r92Cleanup };
  }
