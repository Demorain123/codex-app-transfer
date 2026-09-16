  function activeGenerationUiPresentFor(node) {
    const pane = paneForNode(node);
    const fallbackComposer = findComposerRoot();
    const scope = pane instanceof Element
      ? pane
      : (fallbackComposer instanceof Element ? (fallbackComposer.parentElement || fallbackComposer) : null);
    if (!(scope instanceof Element)) return false;
    const controls = scope.querySelectorAll('button,[role="button"]');
    for (const control of controls) {
      if (!(control instanceof Element) || !isVisible(control) || insideOwnUi(control)) continue;
      const hint = [
        control.getAttribute('aria-label'),
        control.getAttribute('title'),
        control.getAttribute('data-testid'),
        control.getAttribute('data-state'),
        control.textContent,
      ].filter(Boolean).join(' ').toLowerCase();
      if (/(^|[\s:_-])(stop|cancel|interrupt|abort)([\s:_-]|$)|停止|取消|中止|终止/i.test(hint)) return true;
    }
    return false;
  }

  function latestConversationTurnFor(node) {
    const pane = paneForNode(node);
    const scope = pane instanceof Element ? pane : document;
    const preferred = Array.from(scope.querySelectorAll('[data-chatgpt-conversation-turn="true"]'))
      .filter(function(candidate) { return candidate instanceof Element && !insideComposer(candidate) && !insideOwnUi(candidate); });
    if (preferred.length) return preferred[preferred.length - 1];
    const keyed = Array.from(scope.querySelectorAll('[data-turn-key]'))
      .filter(function(candidate) { return candidate instanceof Element && !insideComposer(candidate) && !insideOwnUi(candidate); });
    return keyed.length ? keyed[keyed.length - 1] : null;
  }

  function isLatestTurnSurface(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return false;
    const latest = latestConversationTurnFor(element);
    if (!(latest instanceof Element)) return true;
    return element === latest || latest.contains(element) || element.contains(latest);
  }

  function hasRecentLiveUsageFor(node) {
    if (activeGenerationUiPresentFor(node)) return true;
    const pane = paneForNode(node);
    const paneId = paneThreadId(pane, pane && pane.querySelector ? pane.querySelector('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"],.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea') : null);
    const externalId = normalizePaneThreadId(state.metrics && state.metrics.externalThreadId);
    if (paneId && externalId && paneId !== externalId) return false;
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
  }

  function hasRecentLiveUsage() {
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
  }

  function liveSemanticRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    if (!hasRecentLiveUsageFor(element)) return null;

    const latest = latestConversationTurnFor(element);
    const semantic = element.closest('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
    if (semantic instanceof Element && !isUserAuthoredSurface(semantic)) {
      if (!(latest instanceof Element) || semantic === latest || latest.contains(semantic) || semantic.contains(latest)) return semantic;
    }

    if (latest instanceof Element && (element === latest || latest.contains(element))) return latest;
    return null;
  }

  function strictAssistantRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    const direct = element.closest('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    if (direct) return direct;
    const broad = assistantRootFor(element);
    if (broad instanceof Element) {
      const nested = broad.querySelector('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
      return nested || broad;
    }
    return liveSemanticRootFor(element);
  }

  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    const primary = '[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]';
    document.querySelectorAll(primary).forEach(function(node) {
      const root = node instanceof Element ? node : null;
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root) || isUserAuthoredSurface(root)) return;
      seen.add(root);
      roots.push(root);
    });
    document.querySelectorAll('[data-chatgpt-conversation-turn="true"]').forEach(function(turn) {
      if (!(turn instanceof Element) || insideComposer(turn) || insideOwnUi(turn)) return;
      const nested = turn.querySelector(primary);
      const root = nested || (turn.querySelector('[data-assistant-message-sent-time]') ? turn : null);
      if (!(root instanceof Element) || seen.has(root) || isUserAuthoredSurface(root)) return;
      seen.add(root);
      roots.push(root);
    });
    return roots;
  }

  function resetTimestampArtifacts() {
    document.querySelectorAll('[' + BADGE_ATTR + ']').forEach(function(node) { node.remove(); });
    document.querySelectorAll('[' + HOST_ATTR + ']').forEach(function(node) {
      node.removeAttribute(HOST_ATTR);
      node.removeAttribute(FIRST_SEEN_ATTR);
    });
    try {
      for (let index = localStorage.length - 1; index >= 0; index -= 1) {
        const key = String(localStorage.key(index) || '');
        if (/^cas-r\d+-segment-times(?:-|$)/i.test(key) || key === 'cas-r74-segment-times') localStorage.removeItem(key);
      }
    } catch {}
    state.timestampTimes = new Map();
    state.timestampBaselineElements = new WeakSet();
    state.timestampBaselineKeys = new Set();
    state.timestampRuntimeStartedAt = Date.now();
  }

  function baselineExistingDom() {
    resetTimestampArtifacts();
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return;
        const key = segmentKey(segment, root);
        if (!key) return;
        state.timestampBaselineElements.add(segment);
        state.timestampBaselineKeys.add(key);
        const native = nativeTimeForSegment(segment, root);
        if (native) stampSegment(segment, root, native.epoch, native.source);
      });
    });
  }

  function stampMutationNode(node) {
    const root = strictAssistantRootFor(node);
    if (!root) return;
    const segment = segmentForMutation(node, root);
    if (!(segment instanceof Element) || !isVisible(segment) || isUserAuthoredSurface(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;

    const native = nativeTimeForSegment(segment, root);
    if (native) {
      stampSegment(segment, root, native.epoch, native.source);
      return;
    }

    if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
    if (!isLatestTurnSurface(segment)) return;
    if (!hasRecentLiveUsageFor(segment)) return;
    stampSegment(segment, root, Date.now(), 'first observed live output mutation locally');
  }

  function sweepOutputSegments(allowFresh) {
    if (allowFresh) {
      if (!hasRecentLiveUsage()) return;
    }
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return;
        if (segment.querySelector(':scope > [' + BADGE_ATTR + ']')) return;
        const key = segmentKey(segment, root);
        if (!key) return;
        const native = nativeTimeForSegment(segment, root);
        if (native) {
          stampSegment(segment, root, native.epoch, native.source);
          return;
        }
        if (!allowFresh) return;
        if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
        if (!isLatestTurnSurface(segment)) return;
        if (!hasRecentLiveUsageFor(segment)) return;
        stampSegment(segment, root, Date.now(), 'first observed live output segment locally');
      });
    });
  }

  function scheduleOutputSweep() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(function() {
      state.timer = null;
      try { sweepOutputSegments(false); } catch {}
    }, 90);
  }

  function installOutputObserver() {
    if (!document.body) { setTimeout(installOutputObserver, 80); return; }
    baselineExistingDom();
    const observer = new MutationObserver(function(records) {
      for (const record of records) {
        if (record.type === 'characterData') {
          stampMutationNode(record.target);
          continue;
        }
        for (const added of record.addedNodes || []) {
          stampMutationNode(added);
          if (added instanceof Element) {
            const probes = added.querySelectorAll('p,li,pre,[role="status"],[data-testid],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
            let count = 0;
            for (const probe of probes) {
              if (count++ >= 64) break;
              stampMutationNode(probe);
            }
          }
        }
      }
      scheduleOutputSweep();
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    state.observer = observer;
    setTimeout(function() { try { sweepOutputSegments(false); } catch {} }, 120);
  }
