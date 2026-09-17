  function nativeSentTimeForSegment(segment) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return null;
    const candidates = [];
    if (segment.matches('[data-assistant-message-sent-time],time[datetime]')) candidates.push(segment);
    segment.querySelectorAll('[data-assistant-message-sent-time],time[datetime]').forEach(function(node) { candidates.push(node); });
    for (const candidate of candidates) {
      if (!(candidate instanceof Element)) continue;
      if (candidate.closest('[data-message-author-role="user"],[data-message-author="user"]')) continue;
      const parsed = nativeTime(candidate);
      if (parsed) return parsed;
    }
    return null;
  }

  function isFinalAssistantSurface(segment) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return false;
    if (segment.matches('[data-local-conversation-final-assistant]')) return true;
    if (segment.querySelector('[data-local-conversation-final-assistant]')) return true;
    // A generic data-message-author-role="assistant" wrapper may contain an
    // entire multi-step turn, so it is identity/root only, never final by itself.
    return !!segment.querySelector('[data-assistant-message-sent-time]');
  }

  function nativeTimeForSegment(segment, root) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return null;
    const own = nativeSentTimeForSegment(segment);
    if (own) return own;
    if (!isFinalAssistantSurface(segment)) return null;
    const actionRow = actionRowForSegment(segment, root);
    if (!actionRow) return null;
    return nativeSentTimeForSegment(actionRow);
  }

  function actionRowForSegment(segment, root) {
    if (!(segment instanceof Element) || !isFinalAssistantSurface(segment)) return null;
    const turn = segment.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') ||
      (root instanceof Element ? root.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') : null) ||
      segment;
    const sentTimes = Array.from(turn.querySelectorAll('[data-assistant-message-sent-time]'))
      .filter(function(node) { return !node.closest('[data-message-author-role="user"],[data-message-author="user"]'); });
    const sentTime = sentTimes.length ? sentTimes[sentTimes.length - 1] : null;
    return sentTime && sentTime.parentElement ? sentTime.parentElement : null;
  }

  function timestampBadgeForKey(key) {
    if (!key) return null;
    const badges = document.querySelectorAll('[' + BADGE_ATTR + ']');
    for (const badge of badges) {
      if (badge.getAttribute('data-cas-output-key') === key) return badge;
    }
    return null;
  }

  function timestampIsEstimated(source) {
    const value = String(source || '').toLowerCase();
    return !(value.includes('native') || value.includes('sent time') || value.includes('jsonl'));
  }

  function timestampWouldTouchNativeControl(segment) {
    if (!(segment instanceof Element)) return false;
    const interactive = 'button,[role="button"],a[href],summary,details,[aria-expanded],[aria-controls]';
    if (segment.matches(interactive)) return true;
    if (segment.closest(interactive)) return true;
    // Do not treat an arbitrary deep descendant action/copy button as ownership
    // of the whole output segment. That made r91 suppress nearly every timestamp
    // in real Codex turns. Only a direct native-control child makes fallback
    // append structurally unsafe.
    try {
      if (segment.querySelector(':scope > button,:scope > [role="button"],:scope > a[href],:scope > summary,:scope > details,:scope > [aria-expanded],:scope > [aria-controls]')) return true;
    } catch {}
    return false;
  }

  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment) || isUserAuthoredSurface(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    if (!state.timestampTimes) state.timestampTimes = new Map();

    const actionRow = actionRowForSegment(segment, root);
    const host = actionRow && actionRow.parentElement;
    if (!(actionRow && host) && timestampWouldTouchNativeControl(segment)) return;
    let existing = timestampBadgeForKey(key);
    if (!existing) existing = segment.querySelector(':scope > [' + BADGE_ATTR + ']');
    if (existing) return;

    const remembered = Number(state.timestampTimes.get(key));
    const attrTime = Number(segment.getAttribute(FIRST_SEEN_ATTR));
    const when = Number.isFinite(attrTime) && attrTime > 0
      ? attrTime
      : (Number.isFinite(remembered) && remembered > 0 ? remembered : epoch);
    if (!Number.isFinite(when) || when <= 0) return;

    const estimated = timestampIsEstimated(source);
    const badge = document.createElement('div');
    badge.setAttribute(BADGE_ATTR, 'true');
    badge.setAttribute('data-cas-output-key', key);
    badge.setAttribute('data-cas-timestamp-confidence', estimated ? 'estimated' : 'exact');
    badge.setAttribute('aria-label', estimated ? 'Assistant output timestamp, estimated locally' : 'Assistant output timestamp');
    badge.textContent = (estimated ? '≈ ' : '') + clock(when);
    badge.title = fullTime(when) + ' · ' + (estimated ? 'estimated: ' : 'exact: ') + String(source || 'unknown source');
    badge.style.cssText = 'position:relative;z-index:2;display:flex;width:100%;box-sizing:border-box;align-items:center;justify-content:flex-end;min-height:10px;margin:2px 0 0 0;padding:0 3px;border:0;background:transparent;box-shadow:none;color:color-mix(in srgb,CanvasText 56%,transparent);font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:none;user-select:none;opacity:.78;';

    if (actionRow && host) actionRow.insertAdjacentElement('afterend', badge);
    else segment.appendChild(badge);

    segment.setAttribute(HOST_ATTR, 'true');
    segment.setAttribute(FIRST_SEEN_ATTR, String(when));
    state.timestampTimes.set(key, when);
  }
