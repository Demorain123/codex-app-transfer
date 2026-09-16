  function ingestExternalUsage(envelope) {
    if (!envelope || typeof envelope !== 'object') return false;
    const info = envelope.info && typeof envelope.info === 'object' ? envelope.info : null;
    if (!info) return false;

    const threadId = String(envelope.threadId || '').replace(/^local:/i, '').trim().toLowerCase();
    if (!threadId) return false;
    if (!(state.externalUsageByThread instanceof Map)) state.externalUsageByThread = new Map();

    const updatedAt = Number(envelope.updatedAt) || Date.now();
    const last = info.last_token_usage || info.lastTokenUsage || info.usage || null;
    const output = last && typeof last === 'object'
      ? numberAt(last, [['output_tokens'], ['outputTokens'], ['completion_tokens'], ['completionTokens']])
      : null;
    const previous = state.externalUsageByThread.get(threadId) || null;
    let outputSpeed = previous && Number.isFinite(previous.outputSpeed) ? previous.outputSpeed : null;
    if (previous && Number.isFinite(output) && Number.isFinite(previous.outputTokens)) {
      const deltaTokens = output - previous.outputTokens;
      const deltaSeconds = (updatedAt - Number(previous.updatedAt || 0)) / 1000;
      if (deltaTokens > 0 && deltaSeconds > 0.05) outputSpeed = deltaTokens / deltaSeconds;
      else if (deltaTokens < 0) outputSpeed = null;
    }

    const entry = {
      threadId,
      sessionId: typeof envelope.sessionId === 'string' ? envelope.sessionId.trim().toLowerCase() : null,
      parentThreadId: typeof envelope.parentThreadId === 'string' ? envelope.parentThreadId.trim().toLowerCase() : null,
      model: typeof envelope.model === 'string' ? envelope.model : null,
      updatedAt,
      info,
      outputTokens: Number.isFinite(output) ? output : null,
      outputSpeed,
    };
    state.externalUsageByThread.set(threadId, entry);

    let primaryThreadId = '';
    try {
      const roots = typeof findComposerRoots === 'function' ? findComposerRoots() : [];
      if (roots.length && typeof threadIdForComposer === 'function') primaryThreadId = threadIdForComposer(roots[0]);
    } catch {}

    if (!primaryThreadId || primaryThreadId === threadId) {
      const hit = consumeValue(info, 0);
      if (hit) {
        state.metrics.externalUsageSource = 'local-session-jsonl';
        state.metrics.externalThreadId = threadId;
        state.metrics.externalSessionId = entry.sessionId;
        state.metrics.externalParentThreadId = entry.parentThreadId;
        state.metrics.externalUpdatedAt = updatedAt;
      }
    }
    try { refreshUi(); } catch {}
    return true;
  }

