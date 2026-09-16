  function strictAssistantRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    const direct = element.closest('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    if (direct) return direct;
    const broad = assistantRootFor(element);
    if (!(broad instanceof Element)) return null;
    const nested = broad.querySelector('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    return nested || broad;
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

  function hasRecentLiveUsage() {
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
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

    // Historical DOM that was present at runtime install never receives "now".
    // React remounts/text churn are not trustworthy generation-time evidence.
    if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
    if (!hasRecentLiveUsage()) return;
    stampSegment(segment, root, Date.now(), 'first observed live output mutation locally');
  }

  function sweepOutputSegments(allowFresh) {
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
        if (!hasRecentLiveUsage()) return;
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
