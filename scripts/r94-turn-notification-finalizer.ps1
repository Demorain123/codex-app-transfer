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

  // R94_NATIVE_ACTIVE_SINGLE_PANE_FALLBACK_RUNTIME
  // Exact rollout JSONL remains authoritative. When that bridge has not produced
  // an envelope yet, mirror only values that Codex itself is visibly presenting
  // for the one active pane. Never synthesize latest-request in/out from Usage
  // category totals, and never apply this fallback in split/multi-pane mode.
  function r94ActiveDocumentThreadId() {
    try {
      const pathname = String(location && location.pathname || '');
      const match =
        pathname.match(/\/(?:local|thread|conversation)\/([^/?#]+)/) ||
        pathname.match(/\/hotkey-window\/thread\/([^/?#]+)/);
      if (match && match[1]) {
        let value = match[1];
        try { value = decodeURIComponent(value); } catch {}
        value = r94NormalizePaneId(value);
        if (value) return value;
      }
    } catch {}
    try {
      const row = document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active="true"]');
      const value = r94NormalizePaneId(row && row.getAttribute('data-app-action-sidebar-thread-id'));
      if (value) return value;
    } catch {}
    return '';
  }

  function r94NativeSinglePaneUsage(threadId, bar) {
    const paneThread = r94NormalizePaneId(threadId);
    if (!paneThread || !(bar instanceof Element)) return null;

    const bars = Array.from(document.querySelectorAll(
      '[data-cas-pane-statusbar="true"],[data-cas-status-inside-composer="true"]'
    )).filter(function(node) {
      return node instanceof Element && node.isConnected && (!node.getClientRects || node.getClientRects().length > 0);
    });
    if (bars.length !== 1 || bars[0] !== bar) return null;

    const activeThread = r94ActiveDocumentThreadId();
    if (activeThread && activeThread !== paneThread) return null;

    let candidate = null;
    try { candidate = typeof findNativeUsagePanel === 'function' ? findNativeUsagePanel() : null; } catch {}
    if (!candidate || !(candidate.node instanceof Element) || !candidate.node.isConnected) return null;

    const text = String(candidate.text || '').replace(/\s+/g, ' ').trim();
    if (!text) return null;

    const compact = function(raw) {
      try {
        const value = typeof parseCompactNumber === 'function'
          ? parseCompactNumber(String(raw || '').replace(/\s+/g, ''))
          : Number(String(raw || '').replace(/[,\s]/g, ''));
        return Number.isFinite(value) ? value : null;
      } catch {
        return null;
      }
    };

    const ctxMatch = text.match(/([\d.,]+\s*[KMB]?)\s*\/\s*([\d.,]+\s*[KMB]?)\s*[·•]?\s*([\d.]+)%/i);
    const cacheMatch = text.match(/(?:缓存命中|cache\s*hit)\s*([\d.]+)%/i);
    const totalMatch = text.match(/(?:累计|session\s*total|total)\s*([\d.,]+\s*[KMB]?)/i);

    const contextTokens = ctxMatch ? compact(ctxMatch[1]) : null;
    const contextWindow = ctxMatch ? compact(ctxMatch[2]) : null;
    const contextPercent = ctxMatch ? Number(ctxMatch[3]) : null;
    const cacheHitPercent = cacheMatch ? Number(cacheMatch[1]) : null;
    const sessionTotalTokens = totalMatch ? compact(totalMatch[1]) : null;

    if (![contextTokens, contextWindow, contextPercent, cacheHitPercent, sessionTotalTokens].some(Number.isFinite)) {
      return null;
    }

    return {
      threadId: paneThread,
      source: 'native-active-single-pane',
      contextTokens,
      contextWindow,
      contextPercent: Number.isFinite(contextPercent) ? contextPercent : null,
      cacheHitPercent: Number.isFinite(cacheHitPercent) ? cacheHitPercent : null,
      sessionTotalTokens,
    };
  }

  // R94_MULTI_PANE_USAGE_OWNERSHIP_RUNTIME
  function r94ExternalExactMap() {
    let map = state.metrics && state.metrics.r94ExternalExactByThread;
    if (!(map instanceof Map)) {
      map = new Map();
      if (state.metrics) state.metrics.r94ExternalExactByThread = map;
    }
    return map;
  }

  function r94StoreExternalExact(exact) {
    if (!exact || typeof exact !== 'object') return;
    const threadId = r94NormalizePaneId(exact.threadId);
    if (!threadId) return;
    const map = r94ExternalExactMap();
    map.delete(threadId);
    map.set(threadId, exact);
    while (map.size > 64) {
      const oldest = map.keys().next().value;
      if (!oldest) break;
      map.delete(oldest);
    }
    try {
      window.__casR94PaneUsageDiagnostics = {
        exactThreads: map.size,
        threads: Array.from(map.keys()).slice(-8),
        lastThread: threadId,
      };
    } catch {}
  }

  function r94ExternalExactForThread(threadId) {
    const normalized = r94NormalizePaneId(threadId);
    if (!normalized) return null;
    const exact = r94ExternalExactMap().get(normalized);
    return exact && typeof exact === 'object' ? exact : null;
  }

  function r94RecentOutputMap() {
    let map = state.metrics && state.metrics.r94RecentOutputsByThread;
    if (!(map instanceof Map)) {
      map = new Map();
      if (state.metrics) state.metrics.r94RecentOutputsByThread = map;
    }
    return map;
  }

  function r94StoreRecentOutputs(threadId, outputs) {
    // R94_ASSISTANT_OUTPUT_METADATA_INGEST_RUNTIME
    // The main-process collector sends only turn/item identity, phase and
    // timestamps from Codex rollout rows. No assistant text crosses this bridge.
    const normalizedThread = r94NormalizePaneId(threadId);
    if (!normalizedThread || !Array.isArray(outputs)) return;
    const safe = outputs.slice(-96).map(function(output) {
      if (!output || typeof output !== 'object') return null;
      const turnId = String(output.turnId || '').trim().toLowerCase();
      const atMs = Number(output.atMs);
      if (!turnId || !Number.isFinite(atMs) || atMs <= 0) return null;
      return {
        turnId,
        itemId: output.itemId ? String(output.itemId) : '',
        phase: output.phase ? String(output.phase).toLowerCase() : '',
        atMs,
        source: String(output.source || 'rollout'),
      };
    }).filter(Boolean);
    const map = r94RecentOutputMap();
    map.delete(normalizedThread);
    map.set(normalizedThread, safe);
    while (map.size > 64) {
      const oldest = map.keys().next().value;
      if (!oldest) break;
      map.delete(oldest);
    }
    try {
      window.__casR94OutputEventDiagnostics = {
        threads: map.size,
        lastThread: normalizedThread,
        outputs: safe.length,
      };
    } catch {}
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

    // R94_LOCAL_ITEM_LIFECYCLE_BRIDGE_RUNTIME
    // The bounded rollout tail carries only item id/type/timestamps — never
    // prompt/response text — so split-view and sub-agent panes still receive
    // exact item timing even when Desktop does not surface every child event.
    const recentItems = Array.isArray(envelope.recentItems) ? envelope.recentItems : [];
    for (const itemMeta of recentItems.slice(-96)) {
      if (!itemMeta || typeof itemMeta !== 'object') continue;
      const turnId = String(itemMeta.turnId || '').trim();
      const itemId = String(itemMeta.itemId || '').trim();
      if (!turnId || !itemId) continue;
      const item = { id: itemId, type: String(itemMeta.itemType || '') };
      const startedAtMs = Number(itemMeta.startedAtMs);
      const completedAtMs = Number(itemMeta.completedAtMs);
      if (Number.isFinite(startedAtMs) && startedAtMs > 0) {
        r94OfferNotification('item/started', {
          threadId: normalizedThread,
          turnId,
          item,
          startedAtMs,
        });
      }
      if (Number.isFinite(completedAtMs) && completedAtMs > 0) {
        r94OfferNotification('item/completed', {
          threadId: normalizedThread,
          turnId,
          item,
          completedAtMs,
        });
      }
    }

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
    const contextTokens = r94Number(last,'totalTokens','total_tokens');
    const contextWindow = Number(usage.modelContextWindow ?? usage.model_context_window);
    const sessionTotalTokens = r94Number(total,'totalTokens','total_tokens');
    return {
      threadId: r94NormalizePaneId(record.threadId),
      turnId: String(record.turnId || ''),
      usageObservedAtMs: Number(record.usageObservedAtMs) || null,
      inputTokens,
      cachedInputTokens,
      outputTokens,
      reasoningTokens,
      contextTokens,
      contextWindow: Number.isFinite(contextWindow) ? contextWindow : null,
      sessionTotalTokens,
      contextPercent: Number.isFinite(contextTokens) && Number.isFinite(contextWindow) && contextWindow > 0
        ? Math.max(0, Math.min(100, (contextTokens / contextWindow) * 100))
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
    const threadId = r94NormalizePaneId(typeof envelope.threadId === 'string' ? envelope.threadId : '');
    const info = envelope.info && typeof envelope.info === 'object' ? envelope.info : null;

    // Lifecycle identity is useful before the first token_count snapshot exists.
    r94StoreRecentOutputs(threadId, envelope.recentOutputs);
    r94OfferRolloutEnvelope(envelope, threadId, info);
    if (!info) {
      try { refreshUi(); } catch {}
      return true;
    }

    // R94_EXACT_USAGE_DIRECT_DECODE_RUNTIME
    // The rollout token_count fields are authoritative for exact pane usage.
    // Legacy consumeValue feeds older mirrors/charts only; it must never gate
    // the exact per-thread map.
    let legacyHit = false;
    try { legacyHit = !!consumeValue(info, 0); } catch {}

    const last = info.last_token_usage && typeof info.last_token_usage === 'object'
      ? info.last_token_usage
      : (info.lastTokenUsage && typeof info.lastTokenUsage === 'object' ? info.lastTokenUsage : null);
    const total = info.total_token_usage && typeof info.total_token_usage === 'object'
      ? info.total_token_usage
      : (info.totalTokenUsage && typeof info.totalTokenUsage === 'object' ? info.totalTokenUsage : null);
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
      contextTokens: numberAt(last, [['total_tokens'], ['totalTokens']]),
      contextWindow: numberAt(info, [['model_context_window'], ['modelContextWindow']]),
      sessionTotalTokens: total ? numberAt(total, [['total_tokens'], ['totalTokens']]) : null,
      // R94_CODEX_TOKEN_DURATION_INGEST_RUNTIME
      // The main-process rollout tailer computes this from persisted Codex
      // token_count timestamps using turn_context/task_started as the first
      // interval anchor. It is pane/thread scoped and does not borrow native UI speed.
      usageDurationMs: Number.isFinite(Number(envelope.usageDurationMs)) ? Number(envelope.usageDurationMs) : null,
      outputTokenRate: Number.isFinite(Number(envelope.outputTokenRate)) ? Number(envelope.outputTokenRate) : null,
    } : null;

    if (exact) {
      exact.contextPercent = Number.isFinite(exact.contextTokens) && Number.isFinite(exact.contextWindow) && exact.contextWindow > 0
        ? Math.max(0, Math.min(100, (exact.contextTokens / exact.contextWindow) * 100))
        : null;
      exact.cacheHitPercent = Number.isFinite(exact.cachedInputTokens) && Number.isFinite(exact.inputTokens) && exact.inputTokens > 0
        ? Math.max(0, Math.min(100, (exact.cachedInputTokens / exact.inputTokens) * 100))
        : null;
      const fingerprint = [
        exact.threadId, exact.turnId, exact.inputTokens, exact.cachedInputTokens, exact.outputTokens,
        exact.reasoningTokens, exact.contextTokens, exact.contextWindow, exact.sessionTotalTokens,
        exact.usageDurationMs, exact.outputTokenRate,
      ].join('|');
      if (state.metrics.externalExactFingerprint !== fingerprint) {
        state.metrics.externalExactChangedAt = Date.now();
        state.metrics.externalExactFingerprint = fingerprint;
      }
      exact.changedAt = Number(state.metrics.externalExactChangedAt) || Date.now();
      state.metrics.externalExact = exact;
      r94StoreExternalExact(exact);
    }

    state.metrics.externalUsageSource = turnId ? 'local-session-jsonl-turn' : 'local-session-jsonl';
    state.metrics.externalThreadId = threadId || null;
    state.metrics.externalTurnId = turnId || null;
    state.metrics.externalUpdatedAt = updatedAt;

    try { refreshUi(); } catch {}
    return !!exact || legacyHit;
  }
'@
$Patched = Replace-BlockRequired $Patched '  function ingestExternalUsage(envelope) {' '  state.refresh = refreshUi;' $R94ExternalIngest 'r94 turn-aware local JSONL ingestion'

$R94IngestExport = @'
  state.ingestExternalUsage = ingestExternalUsage; // R94_EXACT_USAGE_INGEST_EXPORT_RUNTIME
  state.refresh = refreshUi;
'@
if (-not $Patched.Contains('R94_EXACT_USAGE_INGEST_EXPORT_RUNTIME')) {
    $Patched = Replace-Required $Patched '  state.refresh = refreshUi;' $R94IngestExport 'r94 exact usage ingest runtime export'
}

$R94PaneThreadFallbackOld = @'
      const externalThreadId = normalizePaneId(state.metrics && state.metrics.externalThreadId);
      if (!threadId && index === 0) threadId = externalThreadId;
'@
$R94PaneThreadFallbackNew = @'
      const externalThreadId = normalizePaneId(state.metrics && state.metrics.externalThreadId);
      // R94_MULTI_PANE_THREAD_FALLBACK_FAIL_CLOSED_RUNTIME
      // A process-global/latest externalThreadId is only safe when exactly one
      // visible composer exists. In split view, an unknown pane must stay
      // unowned instead of borrowing whichever thread happened to update last.
      if (!threadId && composers.length === 1 && index === 0) threadId = externalThreadId;
'@
$Patched = Replace-Required $Patched $R94PaneThreadFallbackOld $R94PaneThreadFallbackNew 'r94 multi-pane thread fallback fail-closed'

$R94PaneOwnership = @'
  function paneTelemetryOwnership(threadId) {
    const paneThread = r94NormalizePaneId(threadId);
    const exact = r94ExternalExactForThread(paneThread);
    const sourceThread = r94NormalizePaneId(exact && exact.threadId);
    const owned = !!paneThread && !!sourceThread && paneThread === sourceThread;
    return {
      owned,
      awaiting: !!paneThread && !owned,
      paneThread,
      sourceThread,
      exact: owned ? exact : null,
    };
  }
'@
$Patched = Replace-BlockRequired $Patched '  function paneTelemetryOwnership(threadId) {' '  function paneActivityState(bar) {' $R94PaneOwnership 'r94 multi-pane exact usage ownership'

$R94PaneSpeedHelpers = @'
  // R94_PANE_LOCAL_TPS_RUNTIME
  // Derive pane-local output speed only from consecutive exact usage samples
  // for the same thread+turn. Never borrow the native/global Codex tok/s.
  function r94PaneSpeedMap() {
    let map = state.metrics && state.metrics.r94PaneSpeedByTurn;
    if (!(map instanceof Map)) {
      map = new Map();
      if (state.metrics) state.metrics.r94PaneSpeedByTurn = map;
    }
    return map;
  }

  function r94PaneSpeedPresentation(threadId, turnRecord, turnExact, activity) {
    const paneThread = r94NormalizePaneId(threadId);
    const turnId = String(turnRecord && turnRecord.turnId || (turnExact && turnExact.turnId) || '').trim().toLowerCase();

    // R94_ROLLOUT_DURATION_TPS_RUNTIME
    // Prefer the persisted rollout interval used by tokscale-style collectors:
    // output tokens from one token_count divided by the exact interval ending
    // at that same token_count. This works even when the renderer only sees one
    // refreshed snapshot for a short sub-agent response.
    const rolloutExact = r94ExternalExactForThread(paneThread);
    const rolloutTurnId = String(rolloutExact && rolloutExact.turnId || '').trim().toLowerCase();
    const rolloutRate = Number(rolloutExact && rolloutExact.outputTokenRate);
    const rolloutDurationMs = Number(rolloutExact && rolloutExact.usageDurationMs);
    if (
      paneThread && turnId && rolloutTurnId === turnId &&
      Number.isFinite(rolloutRate) && rolloutRate > 0 && rolloutRate < 10000 &&
      Number.isFinite(rolloutDurationMs) && rolloutDurationMs > 0
    ) {
      return {
        text: rolloutRate.toFixed(rolloutRate >= 100 ? 0 : 1) + ' tok/s',
        source: 'exact-rollout-token-interval',
        confidence: activity === 'live' ? 'live-exact-interval' : 'last-exact-interval',
        title: 'Pane-local Codex output rate from one persisted token_count output count divided by its matched rollout timestamp interval (' + Math.round(rolloutDurationMs) + ' ms).',
      };
    }

    const outputTokens = Number(turnExact && turnExact.outputTokens);
    const observedAt = Number(turnExact && turnExact.usageObservedAtMs);
    if (!paneThread || !turnId || !Number.isFinite(outputTokens) || !Number.isFinite(observedAt) || observedAt <= 0) {
      return {
        text: '-- tok/s',
        source: 'timing-unavailable',
        confidence: 'unavailable',
        title: 'Unavailable until two exact output-token snapshots for this pane and turn provide a matched token/time delta.',
      };
    }

    const key = paneThread + '\u0000' + turnId;
    const map = r94PaneSpeedMap();
    let sample = map.get(key);
    if (!sample) {
      sample = { outputTokens, observedAt, rate: null };
      map.set(key, sample);
    } else if (observedAt > sample.observedAt) {
      const deltaTokens = outputTokens - Number(sample.outputTokens || 0);
      const deltaMs = observedAt - Number(sample.observedAt || 0);
      if (deltaTokens > 0 && deltaMs >= 80) {
        const rawRate = deltaTokens * 1000 / deltaMs;
        if (Number.isFinite(rawRate) && rawRate > 0 && rawRate < 10000) {
          sample.rate = Number.isFinite(sample.rate)
            ? (sample.rate * 0.35 + rawRate * 0.65)
            : rawRate;
        }
      }
      sample.outputTokens = outputTokens;
      sample.observedAt = observedAt;
      map.delete(key);
      map.set(key, sample);
      while (map.size > 96) {
        const oldest = map.keys().next().value;
        if (!oldest) break;
        map.delete(oldest);
      }
    }

    if (Number.isFinite(sample.rate)) {
      const digits = sample.rate >= 100 ? 0 : 1;
      return {
        text: sample.rate.toFixed(digits) + ' tok/s',
        source: 'exact-pane-output-delta',
        confidence: activity === 'live' ? 'live-exact-delta' : 'last-exact-delta',
        title: activity === 'live'
          ? 'Pane-local output speed from consecutive exact output-token snapshots for this thread and turn.'
          : 'Last pane-local output speed measured from consecutive exact output-token snapshots for this completed/idle turn.',
      };
    }

    return {
      text: '-- tok/s',
      source: 'exact-pane-awaiting-second-sample',
      confidence: 'unavailable',
      title: 'Waiting for a second exact output-token snapshot for this thread and turn; no global/native speed is substituted.',
    };
  }
'@

if (-not $Patched.Contains('R94_PANE_LOCAL_TPS_RUNTIME')) {
    $Patched = Replace-Required $Patched '  function paneTelemetryOwnership(threadId) {' ($R94PaneSpeedHelpers + [char]10 + [char]10 + '  function paneTelemetryOwnership(threadId) {') 'r94 pane-local tok/s helper'
}

$R94StatusHtml = @'
  function statusHtmlForPane(sessionId, threadId, agentId, bar) {
    const ownership = paneTelemetryOwnership(threadId);
    const turnRecord = r94LatestTurnCapability(threadId);
    const turnExact = r94TurnUsageSnapshot(turnRecord);
    const hasTurnIdentity = !!(turnRecord && turnRecord.turnId);
    // R94_MULTI_PANE_LAST_THREAD_SNAPSHOT_FALLBACK_RUNTIME
    // A fresh parent/sub-agent turn can be known from lifecycle before Codex
    // emits that turn's first tokenUsage update. Do not blank an otherwise
    // exact pane-owned thread snapshot merely because the newer turn identity
    // exists. The fallback is explicitly labelled as thread-scoped below so it
    // is never mistaken for current-turn in/out.
    const threadExact = !turnExact && ownership.owned ? ownership.exact : null;
    const threadExactBehindTurn = !!(threadExact && hasTurnIdentity);
    const nativeFallback = !turnExact && !threadExact ? r94NativeSinglePaneUsage(threadId, bar) : null;
    const exact = turnExact || threadExact;
    const displayUsage = exact || nativeFallback;
    const hasOwnedUsage = !!(turnExact || threadExact || nativeFallback);
    const rawActivity = hasOwnedUsage
      ? paneActivityState(bar)
      : (ownership.awaiting ? 'waiting' : 'unowned');
    const lifecycleStatus = String(turnRecord && turnRecord.status || '').toLowerCase();
    const lifecycleTerminal = /completed|failed|interrupted|cancelled|canceled/.test(lifecycleStatus);
    // R94_TERMINAL_TURN_IDLE_FALLBACK_RUNTIME
    // Some sub-agent panes do not expose a normal send button after they close,
    // so DOM-only activity detection reports UNKNOWN forever. An exact terminal
    // turn lifecycle is sufficient to say the pane is no longer busy.
    const activity = rawActivity === 'unknown' && lifecycleTerminal ? 'idle' : rawActivity;
    // R94_STATUS_TRUTH_SEMANTICS_RUNTIME
    // "BUSY" means pane-local task activity (stop/busy UI evidence), not proof
    // that the model is decoding tokens at this instant.
    const stateLabel = hasOwnedUsage
      ? (activity === 'live' ? 'BUSY' : activity.toUpperCase())
      : (ownership.awaiting ? 'WAITING' : 'UNOWNED');
    const stateTitle = turnExact
      ? ('Exact turn-scoped capability for turn ' + String(turnRecord.turnId || '') +
         '. Usage is keyed by threadId + turnId; activity still requires pane-local UI evidence.')
      : (threadExact
        ? (activity === 'live'
          ? 'BUSY means the pane has active task UI evidence (stop/busy). It does not claim the model is currently decoding. Counts are the last exact thread snapshot while no exact turn capability is available.'
          : 'Exact thread snapshot fallback; no cross-pane/global Usage borrowing.')
        : (nativeFallback
          ? 'Native active single-pane fallback: ctx/cache/session mirror the currently visible Codex Usage panel. Latest-request in/out and pane tok/s remain unavailable until stronger ownership/timing evidence arrives.'
          : (ownership.awaiting
            ? 'WAITING: current pane thread is known, but exact JSONL usage is not available and no safe single-pane native fallback is eligible.'
            : 'UNOWNED: no exact turn/thread usage can be safely attributed to this pane.')));

    if (bar instanceof Element) {
      if (turnRecord && turnRecord.turnId) bar.setAttribute('data-cas-turn-id', String(turnRecord.turnId));
      else bar.removeAttribute('data-cas-turn-id');
      bar.setAttribute(
        'data-cas-turn-source',
        turnExact ? 'exact-turn-capability'
          : (threadExact ? (threadExactBehindTurn ? 'thread-snapshot-before-turn-usage' : 'thread-snapshot-fallback')
            : (nativeFallback ? 'native-active-single-pane' : 'unavailable'))
      );
    }

    const context = displayUsage && Number.isFinite(displayUsage.contextPercent) ? ('ctx ' + displayUsage.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = exact && Number.isFinite(exact.inputTokens) ? ('in ' + shortNumber(exact.inputTokens)) : 'in --';
    const output = exact && Number.isFinite(exact.outputTokens) ? ('out ' + shortNumber(exact.outputTokens)) : 'out --';
    const cache = displayUsage && Number.isFinite(displayUsage.cacheHitPercent) ? ('cache ' + displayUsage.cacheHitPercent.toFixed(1) + '%') : 'cache --';
    const session = displayUsage && Number.isFinite(displayUsage.sessionTotalTokens) ? ('session ' + shortNumber(displayUsage.sessionTotalTokens)) : 'session --';
    // R94_NO_NATIVE_GLOBAL_SPEED_AS_PANE_SPEED_RUNTIME
    // Codex native tok/s may be global, stale between polls, or cover a
    // different model-response interval. Only exact same-thread+same-turn
    // output-token deltas are eligible for the pane-local speed chip.
    const speed = turnExact
      ? r94PaneSpeedPresentation(threadId, turnRecord, turnExact, activity)
      : {
          text: '-- tok/s',
          source: nativeFallback ? 'native-global-not-reused' : 'timing-unavailable',
          confidence: 'unavailable',
          title: nativeFallback
            ? 'Visible native/global Codex tok/s is intentionally not re-attributed to this pane.'
            : 'Pane-local tok/s requires exact same-turn output-token samples.',
        };
    const exactSource = turnExact
      ? 'exact-turn-capability'
      : (threadExact
        ? (threadExactBehindTurn ? 'exact-thread-snapshot-before-turn-usage' : 'exact-jsonl-fallback')
        : (nativeFallback ? 'native-active-single-pane' : 'unowned'));
    const exactConfidence = exact
      ? (turnExact ? 'exact-turn' : (threadExactBehindTurn ? 'exact-thread-stale-for-active-turn' : 'exact-snapshot'))
      : (nativeFallback ? 'native-visible' : 'unavailable');
    const exactTitle = turnExact
      ? 'Exact Codex-reported snapshot keyed by threadId + turnId: ctx uses last_token_usage.total_tokens / model_context_window; in/out are the latest model request; cache is cached_input/input; session is cumulative total_token_usage.total_tokens.'
      : (threadExact
        ? (threadExactBehindTurn
          ? 'A newer pane turn is active/known but has not emitted token usage yet. Showing the last exact snapshot for this same thread only; in/out therefore describe the latest completed/reported model request, not the new turn.'
          : 'Exact Codex rollout snapshot for this thread. ctx is current last_token_usage.total_tokens; in/out are the latest model request, not whole-turn totals; session is cumulative and can greatly exceed the context window.')
        : (nativeFallback
          ? 'Visible Codex Usage fallback for exactly one active pane. ctx/cache/session mirror native UI snapshots; in/out and pane tok/s intentionally remain unavailable rather than being guessed.'
          : 'Unavailable: no exact pane-owned usage source.'));

    const metrics = [
      metricChip(
        stateLabel,
        turnExact ? 'turn-lifecycle+pane-ui' : (threadExact ? 'pane-ui-evidence' : (nativeFallback ? 'native-active-single-pane' : exactSource)),
        turnExact ? 'turn-scoped' : (threadExact ? 'scoped' : (nativeFallback ? 'native-visible' : 'unavailable')),
        stateTitle,
        'cas-status-state'
      ),
      metricChip(context, exactSource, exactConfidence, exactTitle, ''),
      metricChip(input, exactSource, exactConfidence, exactTitle, ''),
      metricChip(output, exactSource, exactConfidence, exactTitle, ''),
      metricChip(cache, exactSource, exactConfidence, exactTitle, 'cas-status-secondary'),
      metricChip(speed.text, speed.source, speed.confidence, speed.title, ''),
      metricChip(session, exactSource, exactConfidence, exactTitle, 'cas-status-tertiary'),
    ].join('');

    return '<div class="cas-status-metrics-row" data-cas-pane-live-state="' + stateLabel.toLowerCase() + '">' + metrics + '</div>' +
      '<div class="cas-status-identity-row">' +
        (sessionId ? identityChip('sid', sessionId, 'session id') : '') +
        identityChip('tid', threadId, 'thread id') +
        (agentId ? identityChip('agent', agentId, 'agent id') : '') +
      '</div>';
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
    # R94_PANE_STATUS_OWNER_REQUIRED
    # r89/r90 pane status is part of the inherited contract. A base-only shape
    # means an earlier generated-owner transform silently deleted that runtime,
    # which must fail the build instead of shipping another UI regression.
    throw 'r94 pane status owner missing; refusing base-only status downgrade'
} else {
    throw 'r94 could not locate inherited pane statusHtmlForPane(...) runtime owner'
}

$R94ConsumeText = @'
  function consumeText(text) {
    if (!text || typeof text !== 'string') return;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/^data:\s*/, '').trim();
      if (!line || line === '[DONE]') continue;
      const isToken = /token_count|last_token_usage|total_token_usage|model_context_window|thread\/tokenUsage\/updated|thread_token_usage_updated|usage/i.test(line);
      const isLifecycle = /turn\/(?:started|completed)|turn_(?:started|completed)|task_(?:started|complete)/i.test(line);
      const isItemLifecycle = /item\/(?:started|completed)|item_(?:started|completed)/i.test(line);
      if (!isToken && !isLifecycle && !isItemLifecycle) continue;

      let parsed = null;
      try { parsed = JSON.parse(line); } catch { parsed = null; }
      if (!parsed) continue;

      if (isLifecycle || isItemLifecycle || /thread\/tokenUsage\/updated|thread_token_usage_updated/i.test(line)) {
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
    'R94_MULTI_PANE_USAGE_OWNERSHIP_RUNTIME',
    'R94_NATIVE_ACTIVE_SINGLE_PANE_FALLBACK_RUNTIME',
    'R94_EXACT_USAGE_DIRECT_DECODE_RUNTIME',
    'R94_EXACT_USAGE_INGEST_EXPORT_RUNTIME',
    'R94_STATUS_TRUTH_SEMANTICS_RUNTIME',
    'R94_NO_NATIVE_GLOBAL_SPEED_AS_PANE_SPEED_RUNTIME',
    'R94_MULTI_PANE_LAST_THREAD_SNAPSHOT_FALLBACK_RUNTIME',
    'thread-snapshot-before-turn-usage',
    'exact-thread-snapshot-before-turn-usage',
    'state.ingestExternalUsage = ingestExternalUsage',
    'contextTokens',
    "('session ' + shortNumber(displayUsage.sessionTotalTokens))",
    'native-active-single-pane',
    'r94ExternalExactByThread',
    'r94StoreExternalExact(exact);',
    'r94OfferRolloutEnvelope(envelope, threadId, info);',
    'R94_LOCAL_ITEM_LIFECYCLE_BRIDGE_RUNTIME',
    'recentItems.slice(-96)',
    'window.__casR94TurnCapability',
    "typeof capability.ingestNotification !== 'function'",
    'thread\/tokenUsage\/updated',
    'turn\/(?:started|completed)',
    'item\/(?:started|completed)',
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
} else {
    throw 'r94 pane turn-status owner was not resolved'
}

foreach ($Forbidden in @(
    'nativeFallback.nativeSpeed',
    'exact.contextPercent = Number.isFinite(exact.inputTokens)',
    'contextPercent: Number.isFinite(inputTokens)',
    "('total ' + shortNumber(displayUsage.sessionTotalTokens))"
)) {
    if ($Patched.Contains($Forbidden)) {
        throw "r94 telemetry truth regression survived final materialization: $Forbidden"
    }
}
Write-Host 'R94_TELEMETRY_TRUTH_SEMANTICS_PASS' -ForegroundColor Green

Write-Host 'R94_LOCAL_ITEM_LIFECYCLE_BRIDGE_PASS' -ForegroundColor Green
Write-Host 'R94_MULTI_PANE_USAGE_OWNERSHIP_PASS' -ForegroundColor Green
Write-Host 'R94_PASSIVE_ITEM_LIFECYCLE_INGEST_PASS' -ForegroundColor Green
Write-Host 'R94_PASSIVE_TURN_NOTIFICATION_INGEST_PASS' -ForegroundColor Green
Write-Host 'R94_LOCAL_ROLLOUT_TURN_BRIDGE_PASS' -ForegroundColor Green
Write-Host 'R94_TURN_SCOPED_STATUS_PASS' -ForegroundColor Green
