  function timestampComposerRoots() {
    try {
      if (typeof findComposerRoots === 'function') {
        const roots = findComposerRoots();
        if (Array.isArray(roots)) return roots.filter(function(root) { return root instanceof Element && isVisible(root); });
      }
    } catch {}
    try {
      const one = findComposerRoot();
      return one instanceof Element && isVisible(one) ? [one] : [];
    } catch { return []; }
  }

  function timestampPaneScopeFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return null;
    const composers = timestampComposerRoots();
    if (!composers.length) return null;
    let current = element;
    for (let depth = 0; current instanceof Element && current !== document.body && depth < 12; depth += 1) {
      const contained = composers.filter(function(composer) { return current === composer || current.contains(composer); });
      if (contained.length === 1) return current;
      if (contained.length > 1) break;
      current = current.parentElement;
    }
    return null;
  }

  function activeGenerationUiPresent() {
    const composers = timestampComposerRoots();
    for (const composer of composers) {
      const scope = composer.parentElement instanceof Element ? composer.parentElement : composer;
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
    }
    return false;
  }

  function latestConversationTurn() {
    const preferred = Array.from(document.querySelectorAll('[data-chatgpt-conversation-turn="true"]'))
      .filter(function(node) { return node instanceof Element && !insideComposer(node) && !insideOwnUi(node); });
    if (preferred.length) return preferred[preferred.length - 1];
    const keyed = Array.from(document.querySelectorAll('[data-turn-key]'))
      .filter(function(node) { return node instanceof Element && !insideComposer(node) && !insideOwnUi(node); });
    return keyed.length ? keyed[keyed.length - 1] : null;
  }

  function latestConversationTurnFor(node) {
    const scope = timestampPaneScopeFor(node);
    if (!(scope instanceof Element)) return latestConversationTurn();
    const preferred = Array.from(scope.querySelectorAll('[data-chatgpt-conversation-turn="true"]'))
      .filter(function(turn) { return turn instanceof Element && !insideComposer(turn) && !insideOwnUi(turn); });
    if (preferred.length) return preferred[preferred.length - 1];
    const keyed = Array.from(scope.querySelectorAll('[data-turn-key]'))
      .filter(function(turn) { return turn instanceof Element && !insideComposer(turn) && !insideOwnUi(turn); });
    return keyed.length ? keyed[keyed.length - 1] : null;
  }

  function isLatestTurnSurface(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return false;
    const latest = latestConversationTurnFor(element);
    if (!(latest instanceof Element)) return true;
    return element === latest || latest.contains(element) || element.contains(latest);
  }

  function liveSemanticRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    if (!hasRecentLiveUsage()) return null;

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

  function hasRecentLiveUsage() {
    // Exact token_count telemetry can legitimately arrive only after a long
    // model/tool turn completes. While Codex exposes a visible stop/cancel
    // control in any visible pane, the current UI itself is stronger evidence
    // that at least one turn is live.
    if (activeGenerationUiPresent()) return true;
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
    // Estimated timestamps are restricted to the newest turn in the segment's
    // own visible pane, not the newest turn elsewhere in a split view.
    if (!isLatestTurnSurface(segment)) return;
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
        if (!isLatestTurnSurface(segment)) return;
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
