// R89_TELEMETRY_TRUTH_JS
// Truth-first telemetry overlay. A value can be numerically real yet still be
// wrong for a pane when its source is global/native. Pane status therefore uses
// only the exact local-session JSONL snapshot owned by that pane's thread.
// Model tok/s is deliberately unavailable until numerator and denominator can
// be proven to describe the same model-response interval.

// R89_EXTERNAL_INGEST_BLOCK_START
  function ingestExternalUsage(envelope) {
    if (!envelope || typeof envelope !== 'object') return false;
    const info = envelope.info && typeof envelope.info === 'object' ? envelope.info : null;
    if (!info) return false;

    const hit = consumeValue(info, 0);
    if (!hit) return false;

    const last = info.last_token_usage && typeof info.last_token_usage === 'object'
      ? info.last_token_usage
      : (info.lastTokenUsage && typeof info.lastTokenUsage === 'object' ? info.lastTokenUsage : null);
    const total = info.total_token_usage && typeof info.total_token_usage === 'object'
      ? info.total_token_usage
      : (info.totalTokenUsage && typeof info.totalTokenUsage === 'object' ? info.totalTokenUsage : null);
    const threadId = normalizePaneId(typeof envelope.threadId === 'string' ? envelope.threadId : '');
    const updatedAt = Number(envelope.updatedAt) || Date.now();

    const exact = last ? {
      threadId,
      updatedAt,
      inputTokens: numberAt(last, [['input_tokens'], ['inputTokens'], ['prompt_tokens'], ['promptTokens']]),
      cachedInputTokens: numberAt(last, [['cached_input_tokens'], ['cachedInputTokens'], ['cached_tokens'], ['cachedTokens']]),
      outputTokens: numberAt(last, [['output_tokens'], ['outputTokens'], ['completion_tokens'], ['completionTokens']]),
      reasoningTokens: numberAt(last, [['reasoning_output_tokens'], ['reasoningTokens']]),
      contextWindow: numberAt(info, [['model_context_window'], ['modelContextWindow']]),
      sessionTotalTokens: total ? numberAt(total, [['total_tokens'], ['totalTokens']]) : null,
    } : null;

    if (exact) {
      exact.contextPercent = Number.isFinite(exact.inputTokens) && Number.isFinite(exact.contextWindow) && exact.contextWindow > 0
        ? Math.max(0, Math.min(100, (exact.inputTokens / exact.contextWindow) * 100))
        : null;
      exact.cacheHitPercent = Number.isFinite(exact.cachedInputTokens) && Number.isFinite(exact.inputTokens) && exact.inputTokens > 0
        ? Math.max(0, Math.min(100, (exact.cachedInputTokens / exact.inputTokens) * 100))
        : null;
      const fingerprint = [
        exact.threadId, exact.inputTokens, exact.cachedInputTokens, exact.outputTokens,
        exact.reasoningTokens, exact.contextWindow, exact.sessionTotalTokens,
      ].join('|');
      if (state.metrics.externalExactFingerprint !== fingerprint) {
        state.metrics.externalExactChangedAt = Date.now();
        state.metrics.externalExactFingerprint = fingerprint;
      }
      exact.changedAt = Number(state.metrics.externalExactChangedAt) || Date.now();
      state.metrics.externalExact = exact;
    }

    state.metrics.externalUsageSource = 'local-session-jsonl';
    state.metrics.externalThreadId = threadId || null;
    state.metrics.externalUpdatedAt = updatedAt;
    try { refreshUi(); } catch {}
    return true;
  }
// R89_EXTERNAL_INGEST_BLOCK_END

// R89_GLOBAL_SPEED_BLOCK_START
  function effectiveSpeed() {
    // CAS-R89-NO-GLOBAL-SPEED-AS-PANE-TPS
    // The native Usage panel may continue moving because background processes
    // or subagents are active. It is a global/native value and is not safe to
    // attribute to a specific pane. Keep our custom mirror/history blank rather
    // than silently relabeling global throughput as pane model speed.
    return null;
  }
// R89_GLOBAL_SPEED_BLOCK_END

// R89_PANE_TRUTH_BLOCK_START
  function paneTelemetryOwnership(threadId) {
    const paneThread = normalizePaneId(threadId);
    const exact = state.metrics && state.metrics.externalExact;
    const sourceThread = normalizePaneId(exact && exact.threadId);
    return {
      owned: !!paneThread && !!sourceThread && paneThread === sourceThread,
      paneThread,
      sourceThread,
      exact: exact && typeof exact === 'object' ? exact : null,
    };
  }

  function paneActivityState(bar) {
    if (!(bar instanceof Element)) return 'unknown';
    const composer = bar.nextElementSibling;
    if (!(composer instanceof Element)) return 'unknown';
    const pane = paneForNode(composer);
    const scope = pane instanceof Element ? pane : (composer.parentElement || composer);
    if (!(scope instanceof Element)) return 'unknown';

    const controls = scope.querySelectorAll('button,[role="button"]');
    let sendVisible = false;
    for (const control of controls) {
      if (!(control instanceof Element) || !isVisible(control) || insideOwnUi(control)) continue;
      const hint = [
        control.getAttribute('aria-label'), control.getAttribute('title'),
        control.getAttribute('data-testid'), control.getAttribute('data-state'),
        control.textContent,
      ].filter(Boolean).join(' ').toLowerCase();
      if (/(^|[\s:_-])(stop|cancel|interrupt|abort|pause)([\s:_-]|$)|停止|取消|中止|终止|暂停/i.test(hint)) return 'live';
      if (/(^|[\s:_-])(send|submit)([\s:_-]|$)|发送|提交/i.test(hint)) sendVisible = true;
    }

    const busy = scope.querySelectorAll('[aria-busy="true"],[data-loading="true"],[data-state="loading"],[data-state="pending"],[data-state="running"]');
    for (const node of busy) {
      if (node instanceof Element && isVisible(node) && !insideOwnUi(node)) return 'live';
    }
    return sendVisible ? 'idle' : 'unknown';
  }

  function paneIsLiveForStatus(bar) {
    return paneActivityState(bar) === 'live';
  }

  function metricChip(text, source, confidence, title, extraClass) {
    const safeText = escapeStatusText(text);
    const safeSource = escapeStatusText(source || 'unavailable');
    const safeConfidence = escapeStatusText(confidence || 'unavailable');
    const safeTitle = escapeStatusText(title || '');
    return '<span class="cas-status-item ' + (extraClass || '') + '" data-cas-metric-source="' + safeSource + '" data-cas-confidence="' + safeConfidence + '" title="' + safeTitle + '">' + safeText + '</span>';
  }

  function paneSpeedPresentation(ownership, activity) {
    if (!ownership.owned) {
      return { text: '-- tok/s', source: 'unowned', confidence: 'unavailable', title: 'Unavailable: exact telemetry belongs to another thread.' };
    }
    if (activity !== 'live') {
      return { text: '-- tok/s', source: activity, confidence: 'unavailable', title: activity === 'idle' ? 'Idle: no pane-local generation is active.' : 'Unavailable: pane activity state is not proven live.' };
    }
    return {
      text: '-- tok/s',
      source: 'timing-unavailable',
      confidence: 'unavailable',
      title: 'Live pane, but exact pane-local model tok/s is unavailable: native/global tok/s is intentionally not attributed to this pane, and JSONL snapshots do not provide a matched model-response timing interval.',
    };
  }

  function statusHtmlForPane(sessionId, threadId, agentId, bar) {
    const ownership = paneTelemetryOwnership(threadId);
    const activity = ownership.owned ? paneActivityState(bar) : 'unowned';
    const exact = ownership.owned ? ownership.exact : null;
    const stateLabel = !ownership.owned ? 'UNOWNED' : activity.toUpperCase();
    const stateTitle = !ownership.owned
      ? 'No pane-owned exact JSONL snapshot is available.'
      : (activity === 'live'
        ? 'LIVE is backed by pane-scoped stop/busy UI evidence. Counts are exact JSONL snapshots and may update only at token_count boundaries.'
        : (activity === 'idle'
          ? 'IDLE is backed by a visible pane send/submit control. Counts are the last exact JSONL snapshot, not live activity.'
          : 'UNKNOWN: there is not enough pane-local UI evidence to claim LIVE or IDLE.'));

    const context = exact && Number.isFinite(exact.contextPercent) ? ('ctx ' + exact.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = exact && Number.isFinite(exact.inputTokens) ? ('in ' + shortNumber(exact.inputTokens)) : 'in --';
    const output = exact && Number.isFinite(exact.outputTokens) ? ('out ' + shortNumber(exact.outputTokens)) : 'out --';
    const cache = exact && Number.isFinite(exact.cacheHitPercent) ? ('cache ' + exact.cacheHitPercent.toFixed(1) + '%') : 'cache --';
    const total = exact && Number.isFinite(exact.sessionTotalTokens) ? ('total ' + shortNumber(exact.sessionTotalTokens)) : 'total --';
    const speed = paneSpeedPresentation(ownership, activity);
    const exactTitle = ownership.owned
      ? 'Exact snapshot from local Codex session JSONL last_token_usage / total_token_usage. Snapshot exactness does not imply the pane is currently live.'
      : 'Unavailable: this pane does not own the current exact JSONL snapshot.';

    const metrics = [
      metricChip(stateLabel, ownership.owned ? 'pane-ui-evidence' : 'unowned', ownership.owned ? 'scoped' : 'unavailable', stateTitle, 'cas-status-state'),
      metricChip(context, ownership.owned ? 'exact-jsonl' : 'unowned', ownership.owned ? 'exact-snapshot' : 'unavailable', exactTitle, ''),
      metricChip(input, ownership.owned ? 'exact-jsonl' : 'unowned', ownership.owned ? 'exact-snapshot' : 'unavailable', exactTitle, ''),
      metricChip(output, ownership.owned ? 'exact-jsonl' : 'unowned', ownership.owned ? 'exact-snapshot' : 'unavailable', exactTitle, ''),
      metricChip(cache, ownership.owned ? 'exact-jsonl' : 'unowned', ownership.owned ? 'exact-snapshot' : 'unavailable', exactTitle, 'cas-status-secondary'),
      metricChip(speed.text, speed.source, speed.confidence, speed.title, ''),
      metricChip(total, ownership.owned ? 'exact-jsonl' : 'unowned', ownership.owned ? 'exact-snapshot' : 'unavailable', exactTitle, 'cas-status-tertiary'),
    ].join('');

    return '<div class="cas-status-metrics-row" data-cas-pane-live-state="' + stateLabel.toLowerCase() + '">' + metrics + '</div>' +
      '<div class="cas-status-identity-row">' +
        identityChip('sid', sessionId, 'session id') +
        identityChip('tid', threadId, 'thread id') +
        (agentId ? identityChip('agent', agentId, 'agent id') : '') +
      '</div>';
  }
// R89_PANE_TRUTH_BLOCK_END
