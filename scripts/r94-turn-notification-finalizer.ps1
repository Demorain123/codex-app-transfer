# R94_TURN_NOTIFICATION_FINALIZER
# Passively connects both native app-server-shaped notifications (when they
# already cross the renderer stream) and r76's read-only local rollout bridge
# to the bounded r94 TurnCapability. No provider/app-server request is created.

if (-not (Get-Variable -Name Patched -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r94 notification finalizer requires $Patched'
}

$R94TurnHelpers = @'
  // R94_TURN_NOTIFICATION_BRIDGE_RUNTIME
  function r94NormalizePaneId(value) {
    return String(value || '').replace(/^local:/i, '').trim().toLowerCase();
  }

  function r94Number(object, camel, snake) {
    const value = Number(object && (object[camel] ?? object[snake]));
    return Number.isFinite(value) ? value : null;
  }

  function r94OfficialUsageFromInfo(info) {
    if (!info || typeof info !== 'object') return null;
    const last = info.last_token_usage && typeof info.last_token_usage === 'object'
      ? info.last_token_usage
      : (info.lastTokenUsage && typeof info.lastTokenUsage === 'object' ? info.lastTokenUsage : null);
    const total = info.total_token_usage && typeof info.total_token_usage === 'object'
      ? info.total_token_usage
      : (info.totalTokenUsage && typeof info.totalTokenUsage === 'object' ? info.totalTokenUsage : null);
    if (!last || !total) return null;
    const breakdown = function(raw) {
      const inputTokens = r94Number(raw,'inputTokens','input_tokens') ?? 0;
      const cachedInputTokens = r94Number(raw,'cachedInputTokens','cached_input_tokens') ?? 0;
      const outputTokens = r94Number(raw,'outputTokens','output_tokens') ?? 0;
      const reasoningOutputTokens = r94Number(raw,'reasoningOutputTokens','reasoning_output_tokens') ?? 0;
      const explicitTotal = r94Number(raw,'totalTokens','total_tokens');
      return {
        inputTokens,
        cachedInputTokens,
        outputTokens,
        reasoningOutputTokens,
        cacheWriteInputTokens: r94Number(raw,'cacheWriteInputTokens','cache_write_input_tokens') ?? 0,
        totalTokens: explicitTotal ?? (inputTokens + outputTokens),
      };
    };
    const modelContextWindow = Number(info.model_context_window ?? info.modelContextWindow);
    return {
      last: breakdown(last),
      total: breakdown(total),
      modelContextWindow: Number.isFinite(modelContextWindow) ? modelContextWindow : null,
    };
  }

  function r94OfferNotification(method, params) {
    try {
      const capability = window.__casR94TurnCapability;
      if (!capability || typeof capability.ingestNotification !== 'function') return false;
      return !!capability.ingestNotification({ method, params });
    } catch {
      return false;
    }
  }

  function r94OfferRolloutEnvelope(envelope, threadId, info) {
    const normalizedThread = r94NormalizePaneId(threadId);
    if (!normalizedThread || !envelope || typeof envelope !== 'object') return;

    const active = envelope.activeTurn && typeof envelope.activeTurn === 'object' ? envelope.activeTurn : null;
    if (active && active.turnId) {
      r94OfferNotification('turn/started', {
        threadId: normalizedThread,
        turn: {
          id: active.turnId,
          status: active.status || 'inProgress',
          startedAt: active.startedAt ?? null,
        },
      });
    }

    const usage = r94OfficialUsageFromInfo(info);
    const usageTurnId = String(envelope.turnId || '').trim();
    if (usage && usageTurnId) {
      r94OfferNotification('thread/tokenUsage/updated', {
        threadId: normalizedThread,
        turnId: usageTurnId,
        tokenUsage: usage,
      });
    }

    const terminal = envelope.terminalTurn && typeof envelope.terminalTurn === 'object'
      ? envelope.terminalTurn
      : null;
    if (terminal && terminal.turnId) {
      r94OfferNotification('turn/completed', {
        threadId: normalizedThread,
        turn: {
          id: terminal.turnId,
          status: terminal.status || 'completed',
          startedAt: terminal.startedAt ?? null,
          completedAt: terminal.completedAt ?? null,
          durationMs: terminal.durationMs ?? null,
        },
      });
    } else if (usageTurnId && Number.isFinite(Number(envelope.turnCompletedAt))) {
      r94OfferNotification('turn/completed', {
        threadId: normalizedThread,
        turn: {
          id: usageTurnId,
          status: envelope.turnStatus || 'completed',
          startedAt: envelope.turnStartedAt ?? null,
          completedAt: envelope.turnCompletedAt,
          durationMs: envelope.turnDurationMs ?? null,
        },
      });
    }
  }

  function r94LatestTurnCapability(threadId) {
    try {
      const capability = window.__casR94TurnCapability;
      if (!capability || typeof capability.latestForThread !== 'function') return null;
      return capability.latestForThread(r94NormalizePaneId(threadId));
    } catch {
      return null;
    }
  }

  function r94TurnUsageSnapshot(record) {
    const usage = record && record.usage && typeof record.usage === 'object' ? record.usage : null;
    const last = usage && usage.last && typeof usage.last === 'object' ? usage.last : null;
    const total = usage && usage.total && typeof usage.total === 'object' ? usage.total : null;
    if (!last || !total) return null;
    const inputTokens = r94Number(last,'inputTokens','input_tokens');
    const cachedInputTokens = r94Number(last,'cachedInputTokens','cached_input_tokens');
    const outputTokens = r94Number(last,'outputTokens','output_tokens');
    const reasoningTokens = r94Number(last,'reasoningOutputTokens','reasoning_output_tokens');
    const contextWindow = Number(usage.modelContextWindow ?? usage.model_context_window);
    const sessionTotalTokens = r94Number(total,'totalTokens','total_tokens');
    return {
      threadId: r94NormalizePaneId(record.threadId),
      turnId: String(record.turnId || ''),
      inputTokens,
      cachedInputTokens,
      outputTokens,
      reasoningTokens,
      contextWindow: Number.isFinite(contextWindow) ? contextWindow : null,
      sessionTotalTokens,
      contextPercent: Number.isFinite(inputTokens) && Number.isFinite(contextWindow) && contextWindow > 0
        ? Math.max(0, Math.min(100, (inputTokens / contextWindow) * 100))
        : null,
      cacheHitPercent: Number.isFinite(cachedInputTokens) && Number.isFinite(inputTokens) && inputTokens > 0
        ? Math.max(0, Math.min(100, (cachedInputTokens / inputTokens) * 100))
        : null,
    };
  }
'@

if (-not $Patched.Contains('R94_TURN_NOTIFICATION_BRIDGE_RUNTIME')) {
    $Patched = Replace-Required $Patched '  function ingestExternalUsage(envelope) {' ($R94TurnHelpers + [char]10 + [char]10 + '  function ingestExternalUsage(envelope) {') 'r94 turn notification helpers'
}

$R94ExternalIngest = @'
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
    const threadId = r94NormalizePaneId(typeof envelope.threadId === 'string' ? envelope.threadId : '');
    const turnId = String(envelope.turnId || '').trim().toLowerCase();
    const updatedAt = Number(envelope.updatedAt) || Date.now();

    const exact = last ? {
      threadId,
      turnId: turnId || null,
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
        exact.threadId, exact.turnId, exact.inputTokens, exact.cachedInputTokens, exact.outputTokens,
        exact.reasoningTokens, exact.contextWindow, exact.sessionTotalTokens,
      ].join('|');
      if (state.metrics.externalExactFingerprint !== fingerprint) {
        state.metrics.externalExactChangedAt = Date.now();
        state.metrics.externalExactFingerprint = fingerprint;
      }
      exact.changedAt = Number(state.metrics.externalExactChangedAt) || Date.now();
      state.metrics.externalExact = exact;
    }

    state.metrics.externalUsageSource = turnId ? 'local-session-jsonl-turn' : 'local-session-jsonl';
    state.metrics.externalThreadId = threadId || null;
    state.metrics.externalTurnId = turnId || null;
    state.metrics.externalUpdatedAt = updatedAt;

    r94OfferRolloutEnvelope(envelope, threadId, info);
    try { refreshUi(); } catch {}
    return true;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function ingestExternalUsage(envelope) {' '  state.refresh = refreshUi;' $R94ExternalIngest 'r94 turn-aware local JSONL ingestion'

$R94StatusHtml = @'
  function statusHtmlForPane(sessionId, threadId, agentId, bar) {
    const ownership = paneTelemetryOwnership(threadId);
    const turnRecord = r94LatestTurnCapability(threadId);
    const turnExact = r94TurnUsageSnapshot(turnRecord);
    const hasTurnIdentity = !!(turnRecord && turnRecord.turnId);
    const exact = turnExact || (!hasTurnIdentity && ownership.owned ? ownership.exact : null);
    const activity = (turnExact || ownership.owned)
      ? paneActivityState(bar)
      : (ownership.awaiting ? 'waiting' : 'unowned');
    const stateLabel = (turnExact || ownership.owned)
      ? activity.toUpperCase()
      : (ownership.awaiting ? 'WAITING' : 'UNOWNED');
    const stateTitle = turnExact
      ? ('Exact turn-scoped capability for turn ' + String(turnRecord.turnId || '') +
         '. Usage is keyed by threadId + turnId; activity still requires pane-local UI evidence.')
      : (ownership.owned
        ? (activity === 'live'
          ? 'LIVE is backed by pane-scoped stop/busy UI evidence. Counts are the last exact thread snapshot while no exact turn capability is available.'
          : 'Exact thread snapshot fallback; no cross-pane/global Usage borrowing.')
        : (ownership.awaiting
          ? 'WAITING: current pane thread is known, but a same-turn exact usage capability is not available yet.'
          : 'UNOWNED: no exact turn/thread usage can be safely attributed to this pane.'));

    if (bar instanceof Element) {
      if (turnRecord && turnRecord.turnId) bar.setAttribute('data-cas-turn-id', String(turnRecord.turnId));
      else bar.removeAttribute('data-cas-turn-id');
      bar.setAttribute('data-cas-turn-source', turnExact ? 'exact-turn-capability' : (ownership.owned ? 'thread-snapshot-fallback' : 'unavailable'));
    }

    const context = exact && Number.isFinite(exact.contextPercent) ? ('ctx ' + exact.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = exact && Number.isFinite(exact.inputTokens) ? ('in ' + shortNumber(exact.inputTokens)) : 'in --';
    const output = exact && Number.isFinite(exact.outputTokens) ? ('out ' + shortNumber(exact.outputTokens)) : 'out --';
    const cache = exact && Number.isFinite(exact.cacheHitPercent) ? ('cache ' + exact.cacheHitPercent.toFixed(1) + '%') : 'cache --';
    const total = exact && Number.isFinite(exact.sessionTotalTokens) ? ('total ' + shortNumber(exact.sessionTotalTokens)) : 'total --';
    const speedOwnership = turnExact
      ? Object.assign({}, ownership, { owned: true, awaiting: false, exact: turnExact })
      : ownership;
    const speed = paneSpeedPresentation(speedOwnership, activity);
    const exactSource = turnExact ? 'exact-turn-capability' : (ownership.owned ? 'exact-jsonl-fallback' : 'unowned');
    const exactConfidence = exact ? (turnExact ? 'exact-turn' : 'exact-snapshot') : 'unavailable';
    const exactTitle = turnExact
      ? 'Exact recent-turn usage keyed by threadId + turnId. total is cumulative session usage; ctx/in/out/cache are from this turn usage payload.'
      : (ownership.owned
        ? 'Exact thread snapshot fallback from local Codex session JSONL. It is used only when no newer turn identity is present.'
        : 'Unavailable: no exact pane-owned usage source.');

    const metrics = [
      metricChip(stateLabel, turnExact ? 'turn-lifecycle+pane-ui' : (ownership.owned ? 'pane-ui-evidence' : exactSource), turnExact ? 'turn-scoped' : (ownership.owned ? 'scoped' : 'unavailable'), stateTitle, 'cas-status-state'),
      metricChip(context, exactSource, exactConfidence, exactTitle, ''),
      metricChip(input, exactSource, exactConfidence, exactTitle, ''),
      metricChip(output, exactSource, exactConfidence, exactTitle, ''),
      metricChip(cache, exactSource, exactConfidence, exactTitle, 'cas-status-secondary'),
      metricChip(speed.text, speed.source, speed.confidence, speed.title, ''),
      metricChip(total, exactSource, exactConfidence, exactTitle, 'cas-status-tertiary'),
    ].join('');

    return '<div class="cas-status-metrics-row" data-cas-pane-live-state="' + stateLabel.toLowerCase() + '">' + metrics + '</div>' +
      '<div class="cas-status-identity-row">' +
        identityChip('sid', sessionId, 'session id') +
        identityChip('tid', threadId, 'thread id') +
        (agentId ? identityChip('agent', agentId, 'agent id') : '') +
      '</div>';
  }
'@
$R94BaseStatusHtml = @'
  // R94_TURN_STATUS_BASE_OWNER_RUNTIME
  // Fallback for the single-status runtime shape. It still prefers the exact
  // recent-turn capability and never borrows native/global Usage metrics.
  function statusHtml() {
    const m = state.metrics || {};
    const threadId = r94NormalizePaneId(m.externalThreadId || '');
    const turnRecord = r94LatestTurnCapability(threadId);
    const turnExact = r94TurnUsageSnapshot(turnRecord);
    const fallbackExact = m.externalExact && typeof m.externalExact === 'object' ? m.externalExact : null;
    const exact = turnExact || fallbackExact;
    const context = exact && Number.isFinite(exact.contextPercent) ? ('ctx ' + exact.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = exact && Number.isFinite(exact.inputTokens) ? ('in ' + shortNumber(exact.inputTokens)) : 'in --';
    const output = exact && Number.isFinite(exact.outputTokens) ? ('out ' + shortNumber(exact.outputTokens)) : 'out --';
    const cache = exact && Number.isFinite(exact.cacheHitPercent) ? ('cache ' + exact.cacheHitPercent.toFixed(1) + '%') : 'cache --';
    const total = exact && Number.isFinite(exact.sessionTotalTokens) ? ('total ' + shortNumber(exact.sessionTotalTokens)) : 'total --';
    const model = String(m.model || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return [
      '<span class="cas-status-item" data-cas-metric-source="' + (turnExact ? 'exact-turn-capability' : 'exact-jsonl-fallback') + '">' + context + '</span>',
      '<span class="cas-status-item">' + input + '</span>',
      '<span class="cas-status-item">' + output + '</span>',
      '<span class="cas-status-item cas-status-secondary">' + cache + '</span>',
      '<span class="cas-status-item">-- tok/s</span>',
      '<span class="cas-status-item cas-status-tertiary">' + total + '</span>',
      '<span class="cas-status-spacer"></span>',
      '<span class="cas-status-item cas-status-muted cas-status-secondary">' + model + '</span>',
    ].join('');
  }
'@

$R94TurnStatusOwner = $null
$R94PaneStatusStart = [regex]::Match(
    $Patched,
    '(?m)^[ \t]*function statusHtmlForPane\s*\([^)]*\)\s*\{'
)
if ($R94PaneStatusStart.Success) {
    $R94PaneTail = $Patched.Substring($R94PaneStatusStart.Index + $R94PaneStatusStart.Length)
    $R94PaneStatusEnd = [regex]::Match(
        $R94PaneTail,
        '(?m)^[ \t]*function bindIdentityCopy\s*\(bar\)\s*\{'
    )
    if (-not $R94PaneStatusEnd.Success) {
        throw 'r94 pane status owner found but bindIdentityCopy boundary is missing'
    }
    $R94PaneEndMarker = $R94PaneStatusEnd.Value
    $Patched = Replace-BlockRequired $Patched $R94PaneStatusStart.Value $R94PaneEndMarker $R94StatusHtml 'r94 turn-scoped pane status presentation'
    $R94TurnStatusOwner = 'pane'
    Write-Host 'R94_TURN_STATUS_PANE_OWNER_PASS' -ForegroundColor Green
} elseif ($Patched.Contains('  function statusHtml() {')) {
    $Patched = Replace-BlockRequired $Patched '  function statusHtml() {' '  function ensureMirror() {' $R94BaseStatusHtml 'r94 turn-scoped base status presentation'
    $R94TurnStatusOwner = 'base'
    Write-Host 'R94_TURN_STATUS_BASE_OWNER_PASS' -ForegroundColor Yellow
} else {
    throw 'r94 could not locate either pane statusHtmlForPane(...) or base statusHtml() runtime owner'
}

$R94ConsumeText = @'
  function consumeText(text) {
    if (!text || typeof text !== 'string') return;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/^data:\s*/, '').trim();
      if (!line || line === '[DONE]') continue;
      const isToken = /token_count|last_token_usage|total_token_usage|model_context_window|thread\/tokenUsage\/updated|thread_token_usage_updated|usage/i.test(line);
      const isLifecycle = /turn\/(?:started|completed)|turn_(?:started|completed)|task_(?:started|complete)/i.test(line);
      if (!isToken && !isLifecycle) continue;

      let parsed = null;
      try { parsed = JSON.parse(line); } catch { parsed = null; }
      if (!parsed) continue;

      if (isLifecycle || /thread\/tokenUsage\/updated|thread_token_usage_updated/i.test(line)) {
        try {
          const capability = window.__casR94TurnCapability;
          if (capability && typeof capability.ingestNotification === 'function') {
            capability.ingestNotification(parsed);
          }
        } catch {}
      }

      if (isLifecycle && /turn\/completed|turn_completed|task_complete/i.test(line)) {
        state.metrics.done = true;
      }
      if (isToken) {
        try { consumeValue(parsed, 0); } catch {}
      }
    }
  }
'@
$Patched = Replace-BlockRequired $Patched '  function consumeText(text) {' '  function installFetchObserver() {' $R94ConsumeText 'r94 passive exact turn notification ingestion'

foreach ($Marker in @(
    'R94_TURN_NOTIFICATION_BRIDGE_RUNTIME',
    'r94OfferRolloutEnvelope(envelope, threadId, info);',
    'window.__casR94TurnCapability',
    "typeof capability.ingestNotification !== 'function'",
    'thread\/tokenUsage\/updated',
    'turn\/(?:started|completed)',
    'task_(?:started|complete)'
)) {
    if (-not $Patched.Contains($Marker)) {
        throw "r94 notification finalizer marker missing: $Marker"
    }
}

if ($R94TurnStatusOwner -eq 'pane') {
    foreach ($Marker in @(
        "bar.setAttribute('data-cas-turn-id'",
        'exact-turn-capability'
    )) {
        if (-not $Patched.Contains($Marker)) {
            throw "r94 pane turn-status marker missing: $Marker"
        }
    }
} elseif ($R94TurnStatusOwner -eq 'base') {
    foreach ($Marker in @(
        'R94_TURN_STATUS_BASE_OWNER_RUNTIME',
        "data-cas-metric-source=\"' + (turnExact ? 'exact-turn-capability' : 'exact-jsonl-fallback')"
    )) {
        if (-not $Patched.Contains($Marker)) {
            throw "r94 base turn-status marker missing: $Marker"
        }
    }
} else {
    throw 'r94 turn-status owner was not resolved'
}

Write-Host 'R94_PASSIVE_TURN_NOTIFICATION_INGEST_PASS' -ForegroundColor Green
Write-Host 'R94_LOCAL_ROLLOUT_TURN_BRIDGE_PASS' -ForegroundColor Green
Write-Host 'R94_TURN_SCOPED_STATUS_PASS' -ForegroundColor Green
