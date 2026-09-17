  function composerRectForNode(node) {
    const pane = paneForNode(node);
    const composer = composerForPane(pane) || findComposerRoot();
    if (!(composer instanceof Element)) return null;
    try { return composer.getBoundingClientRect(); } catch { return null; }
  }

  function isNearComposerLiveTail(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return false;
    let er;
    try { er = element.getBoundingClientRect(); } catch { er = null; }
    const cr = composerRectForNode(element);
    if (!er || !cr) return false;
    if (er.width <= 0 || er.height <= 0) return false;
    const tailDepth = Math.max(520, Math.min(980, innerHeight * 0.72));
    return er.bottom <= cr.top + 90 && er.bottom >= cr.top - tailDepth;
  }

  function visibleBusyHint(scope) {
    if (!(scope instanceof Element)) return false;
    const direct = scope.querySelectorAll('[aria-busy="true"],[data-loading="true"],[data-state="loading"],[data-state="pending"],[data-state="running"],[class*="animate-spin"],[class*="spinner"]');
    for (const node of direct) {
      if (node instanceof Element && isVisible(node) && !insideOwnUi(node)) return true;
    }
    return false;
  }

  function liveTailTextFor(node) {
    const pane = paneForNode(node);
    const scope = pane instanceof Element ? pane : document;
    const nodes = Array.from(scope.querySelectorAll('[role="status"],[data-testid],p,span,div'))
      .filter(function(candidate) {
        if (!(candidate instanceof Element) || !isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate)) return false;
        return isNearComposerLiveTail(candidate);
      })
      .sort(function(a, b) {
        try { return a.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom; }
        catch { return 0; }
      })
      .slice(-24);
    return nodes.map(function(candidate) { return normalizedText(candidate); }).join(' ').slice(-2200).toLowerCase();
  }

  function turnLooksUserAuthored(turn) {
    if (!(turn instanceof Element)) return false;
    if (turn.matches('[data-message-author-role="user"],[data-message-author="user"]')) return true;
    const user = turn.querySelector('[data-message-author-role="user"],[data-message-author="user"]');
    const assistant = turn.querySelector('[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[data-assistant-message-sent-time]');
    return !!user && !assistant;
  }

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
      if (/(^|[\s:_-])(stop|cancel|interrupt|abort|pause)([\s:_-]|$)|停止|取消|中止|终止|暂停/i.test(hint)) return true;
    }
    if (visibleBusyHint(scope)) return true;

    const latest = latestConversationTurnFor(node);
    const tailText = liveTailTextFor(node) || (latest instanceof Element ? normalizedText(latest).slice(-1600).toLowerCase() : '');
    if (/(^|\b)(thinking|working|generating|running|pausing|waiting|step\s*\d+\s*\/\s*\d+)(\b|$)|思考|处理中|正在生成|正在运行|等待中|暂停片刻/i.test(tailText)) {
      return true;
    }
    return false;
  }

  function latestConversationTurnFor(node) {
    const pane = paneForNode(node);
    const scope = pane instanceof Element ? pane : document;
    const preferred = Array.from(scope.querySelectorAll('[data-chatgpt-conversation-turn="true"]'))
      .filter(function(candidate) { return candidate instanceof Element && !insideComposer(candidate) && !insideOwnUi(candidate) && !turnLooksUserAuthored(candidate) && isVisible(candidate); });
    if (preferred.length) return preferred[preferred.length - 1];

    const keyed = Array.from(scope.querySelectorAll('[data-turn-key]'))
      .filter(function(candidate) { return candidate instanceof Element && !insideComposer(candidate) && !insideOwnUi(candidate) && !turnLooksUserAuthored(candidate) && isVisible(candidate); });
    if (keyed.length) return keyed[keyed.length - 1];

    const composer = composerForPane(pane) || findComposerRoot();
    let cr = null;
    try { cr = composer instanceof Element ? composer.getBoundingClientRect() : null; } catch { cr = null; }
    if (!cr) return null;
    const candidates = Array.from(scope.querySelectorAll('[data-message-author-role="assistant"],[role="status"],[data-testid],p,pre'))
      .filter(function(candidate) {
        if (!(candidate instanceof Element) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate) || !isVisible(candidate)) return false;
        let rect;
        try { rect = candidate.getBoundingClientRect(); } catch { return false; }
        return rect.bottom <= cr.top + 90 && rect.bottom >= cr.top - Math.max(520, Math.min(980, innerHeight * 0.72));
      });
    if (!candidates.length) return null;
    candidates.sort(function(a, b) {
      try { return a.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom; }
      catch { return 0; }
    });
    return candidates[candidates.length - 1];
  }

  function isLatestTurnSurface(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return false;
    const latest = latestConversationTurnFor(element);
    if (latest instanceof Element && (element === latest || latest.contains(element) || element.contains(latest))) return true;
    if (isNearComposerLiveTail(element) && activeGenerationUiPresentFor(element)) return true;
    return false;
  }

  function hasRecentLiveUsageFor(node) {
    if (activeGenerationUiPresentFor(node)) return true;
    const pane = paneForNode(node);
    const composer = composerForPane(pane);
    const paneId = paneThreadId(pane, composer);
    const externalId = normalizePaneThreadId(state.metrics && state.metrics.externalThreadId);
    if (paneId && externalId && paneId !== externalId) return false;
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
  }

  function hasRecentLiveUsage() {
    for (const composer of findComposerRoots()) {
      if (activeGenerationUiPresentFor(composer)) return true;
    }
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
  }

  function liveTailRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    if (!hasRecentLiveUsageFor(element)) return null;
    if (!isLatestTurnSurface(element)) return null;

    const semantic = element.closest('[data-chatgpt-conversation-turn="true"],[data-turn-key],[data-message-author-role="assistant"],[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
    if (semantic instanceof Element && !isUserAuthoredSurface(semantic)) return semantic;

    const latest = latestConversationTurnFor(element);
    if (latest instanceof Element && (element === latest || latest.contains(element) || element.contains(latest))) return latest;

    let current = element;
    const pane = paneForNode(element);
    for (let depth = 0; depth < 6 && current.parentElement; depth += 1) {
      const parent = current.parentElement;
      if (pane instanceof Element && parent === pane) break;
      if (insideComposer(parent) || insideOwnUi(parent) || isUserAuthoredSurface(parent)) break;
      current = parent;
    }
    return current;
  }

  function strictAssistantRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    const direct = element.closest('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    if (direct) return direct;
    const broad = assistantRootFor(element);
    if (broad instanceof Element) {
      const nested = broad.querySelector('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
      return nested || broad;
    }
    return liveTailRootFor(element);
  }

  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    const add = function(root) {
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root) || isUserAuthoredSurface(root) || !isVisible(root)) return;
      seen.add(root);
      roots.push(root);
    };
    const primary = '[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]';
    document.querySelectorAll(primary).forEach(add);
    document.querySelectorAll('[data-chatgpt-conversation-turn="true"]').forEach(function(turn) {
      if (!(turn instanceof Element) || insideComposer(turn) || insideOwnUi(turn)) return;
      const nested = turn.querySelector(primary);
      const root = nested || (turn.querySelector('[data-assistant-message-sent-time]') ? turn : null);
      add(root);
    });
    for (const composer of findComposerRoots()) {
      if (!activeGenerationUiPresentFor(composer)) continue;
      add(latestConversationTurnFor(composer));
    }
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

  function stampLiveRoot(root) {
    if (!(root instanceof Element) || !hasRecentLiveUsageFor(root)) return;
    topLevelSegments(root).forEach(function(segment) {
      if (!(segment instanceof Element) || isUserAuthoredSurface(segment) || !isVisible(segment)) return;
      if (segment.querySelector(':scope > [' + BADGE_ATTR + ']')) return;
      const key = segmentKey(segment, root);
      if (!key) return;
      const native = nativeTimeForSegment(segment, root);
      if (native) {
        stampSegment(segment, root, native.epoch, native.source);
        return;
      }
      if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
      if (!isLatestTurnSurface(segment)) return;
      stampSegment(segment, root, Date.now(), 'first observed live output segment locally');
    });
  }

  function sweepLiveTailSegments() {
    for (const composer of findComposerRoots()) {
      if (!activeGenerationUiPresentFor(composer)) continue;
      const pane = paneForComposer(composer);
      const scope = pane instanceof Element ? pane : document;
      const candidates = Array.from(scope.querySelectorAll('[data-message-author-role="assistant"],[role="status"],[data-testid],p,pre'))
        .filter(function(candidate) {
          return candidate instanceof Element && isVisible(candidate) && !insideComposer(candidate) && !insideOwnUi(candidate) && !isUserAuthoredSurface(candidate) && isNearComposerLiveTail(candidate);
        })
        .sort(function(a, b) {
          try { return a.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom; }
          catch { return 0; }
        })
        .slice(-12);
      for (const candidate of candidates) {
        const root = liveTailRootFor(candidate);
        if (root instanceof Element) stampLiveRoot(root);
      }
    }
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
      try { sweepLiveTailSegments(); } catch {}
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
            const probes = added.querySelectorAll('p,li,pre,[role="status"],[data-testid],[data-local-conversation-final-assistant],[data-message-author-role="assistant"],[data-turn-key]');
            let count = 0;
            for (const probe of probes) {
              if (count++ >= 96) break;
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
