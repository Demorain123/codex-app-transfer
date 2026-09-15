/*
 * CAS r73 Codex output telemetry runtime.
 *
 * Goals:
 * - Add a stable, visible local timestamp badge to EVERY assistant/model output
 *   segment rendered by Codex Desktop, including streamed/progress assistant turns.
 * - Never rewrite message text, never touch composer/user turns, and stay idempotent
 *   across React remounts / virtualized lists.
 * - Best-effort, non-blocking token telemetry: context fill + output tok/s are shown
 *   only when a token_count payload is observable in renderer fetch traffic.
 *
 * Selector/observer ideas were informed by the MIT-licensed Codex-Monitor
 * (KevinKE93) and codex-context-used-meter (Minghou-Lei). Stream token-rate ideas
 * were informed by the MIT-licensed codex-speed-monitor (petergpt). This file is
 * an independent implementation tailored to Codex App Transfer's No-Lagging path.
 */
(() => {
  'use strict';

  const RUNTIME_VERSION = 'r73.1';
  const STYLE_ID = 'cas-output-telemetry-style';
  const BADGE_ATTR = 'data-cas-output-timestamp';
  const STAMP_ATTR = 'data-cas-output-stamped';
  const OBSERVED_ATTR = 'data-cas-output-observed-at';
  const HUD_ID = 'cas-output-telemetry-hud';
  const APPLY_FLAG = '__casOutputTelemetryApplying';
  const ROOT_MARKER = '__casOutputTelemetryRuntime';

  const previous = window[ROOT_MARKER];
  if (previous?.version === RUNTIME_VERSION) {
    previous.rescan?.();
    return { ok: true, version: RUNTIME_VERSION, reused: true };
  }
  try { previous?.observer?.disconnect?.(); } catch {}
  try { previous?.cleanup?.(); } catch {}

  const state = {
    version: RUNTIME_VERSION,
    observer: null,
    scanTimer: null,
    metrics: {
      seen: false,
      contextPercent: null,
      contextTokens: null,
      contextWindow: null,
      outputTokens: null,
      reasoningTokens: null,
      cachedInputTokens: null,
      inputTokens: null,
      turnStartedAt: null,
      updatedAt: null,
      done: false,
    },
    fetchInstalled: false,
  };

  function nowEpoch() { return Date.now(); }
  function pad2(value) { return String(value).padStart(2, '0'); }
  function formatClock(epoch) {
    const d = new Date(epoch);
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  }
  function formatFull(epoch) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
      }).format(new Date(epoch));
    } catch {
      return new Date(epoch).toLocaleString();
    }
  }
  function compactNumber(value) {
    if (!Number.isFinite(value)) return '--';
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
    return String(Math.round(value));
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      [${STAMP_ATTR}="true"] { position: relative !important; }
      [${BADGE_ATTR}] {
        position: absolute;
        top: 2px;
        right: 4px;
        z-index: 20;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 1px 5px;
        border: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
        border-radius: 999px;
        background: color-mix(in srgb, Canvas 88%, transparent);
        color: color-mix(in srgb, CanvasText 56%, transparent);
        box-shadow: 0 1px 4px color-mix(in srgb, CanvasText 8%, transparent);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        font: 9px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        letter-spacing: 0.01em;
        white-space: nowrap;
        pointer-events: auto;
        cursor: default;
        user-select: text;
        opacity: .78;
      }
      [${BADGE_ATTR}]:hover { opacity: 1; }
      #${HUD_ID} {
        position: fixed;
        right: 10px;
        bottom: 10px;
        z-index: 2147483646;
        display: none;
        align-items: center;
        gap: 7px;
        padding: 3px 7px;
        border: 1px solid color-mix(in srgb, CanvasText 14%, transparent);
        border-radius: 999px;
        background: color-mix(in srgb, Canvas 88%, transparent);
        color: color-mix(in srgb, CanvasText 64%, transparent);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        box-shadow: 0 2px 8px color-mix(in srgb, CanvasText 10%, transparent);
        font: 10px/1.3 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        pointer-events: none;
      }
      #${HUD_ID}[data-visible="true"] { display: inline-flex; }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function assistantNodes() {
    // Stable semantic attributes observed in current Codex Desktop builds.
    // Keep the selector set intentionally narrow: false positives on user turns are
    // worse than temporarily missing a badge after an upstream UI rename.
    const selectors = [
      '[data-content-search-assistant-turn-key]',
      '[data-local-conversation-final-assistant]',
      '[data-chatgpt-conversation-turn="true"] [data-content-search-assistant-turn-key]',
    ];
    const seen = new Set();
    const nodes = [];
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach(raw => {
        const node = raw.closest('[data-content-search-assistant-turn-key]') ||
          raw.closest('[data-local-conversation-final-assistant]') || raw;
        if (seen.has(node) || node.closest(`#${HUD_ID}`)) return;
        seen.add(node);
        nodes.push(node);
      });
    }

    // Fallback for ChatGPT-style assistant wrappers when the search-key marker is
    // absent. Require an assistant-specific descendant to avoid stamping user turns.
    document.querySelectorAll('[data-chatgpt-conversation-turn="true"]').forEach(turn => {
      if (seen.has(turn)) return;
      if (!turn.querySelector('[data-assistant-message-sent-time], [data-message-author-role="assistant"], [data-local-conversation-final-assistant]')) return;
      seen.add(turn);
      nodes.push(turn);
    });
    return nodes;
  }

  function parseNativeTimestamp(node) {
    const sent = node.querySelector('[data-assistant-message-sent-time]') ||
      node.querySelector('time[datetime]');
    if (!sent) return null;
    const candidates = [
      sent.getAttribute('datetime'),
      sent.getAttribute('data-timestamp'),
      sent.getAttribute('title'),
      sent.getAttribute('aria-label'),
      sent.textContent,
    ].filter(Boolean).map(v => String(v).trim()).filter(Boolean);

    for (const value of candidates) {
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 1_000_000_000) {
        const epoch = numeric > 10_000_000_000 ? numeric : numeric * 1000;
        return { epoch, label: formatClock(epoch), source: 'native' };
      }
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return { epoch: parsed, label: formatClock(parsed), source: 'native' };
      const clock = value.match(/\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s?(AM|PM)?\b/i);
      if (clock) {
        return { epoch: null, label: clock[0], source: 'native-text' };
      }
    }
    return null;
  }

  function metricTitle() {
    const m = state.metrics;
    if (!m.seen) return '';
    const lines = [];
    if (Number.isFinite(m.contextPercent)) {
      lines.push(`Context: ${m.contextPercent.toFixed(1)}% (${compactNumber(m.contextTokens)}/${compactNumber(m.contextWindow)})`);
    }
    if (Number.isFinite(m.outputTokens)) lines.push(`Output: ${compactNumber(m.outputTokens)} tokens`);
    if (Number.isFinite(m.inputTokens)) lines.push(`Input: ${compactNumber(m.inputTokens)} tokens`);
    if (Number.isFinite(m.cachedInputTokens)) lines.push(`Cached input: ${compactNumber(m.cachedInputTokens)} tokens`);
    if (Number.isFinite(m.reasoningTokens)) lines.push(`Reasoning: ${compactNumber(m.reasoningTokens)} tokens`);
    const speed = outputSpeed();
    if (Number.isFinite(speed)) lines.push(`Speed: ${speed.toFixed(1)} tok/s`);
    return lines.join('\n');
  }

  function stamp(node) {
    if (!(node instanceof Element)) return;
    ensureStyle();
    let badge = Array.from(node.children || []).find(child => child.hasAttribute?.(BADGE_ATTR));
    let observedEpoch = Number(node.getAttribute(OBSERVED_ATTR));
    if (!Number.isFinite(observedEpoch) || observedEpoch <= 0) {
      observedEpoch = nowEpoch();
      node.setAttribute(OBSERVED_ATTR, String(observedEpoch));
    }
    const native = parseNativeTimestamp(node);
    const label = native?.label || formatClock(observedEpoch);
    if (!badge) {
      badge = document.createElement('span');
      badge.setAttribute(BADGE_ATTR, 'true');
      badge.setAttribute('aria-label', 'Assistant output timestamp');
      node.appendChild(badge);
    }
    if (badge.textContent !== label) badge.textContent = label;
    const sourceEpoch = native?.epoch || observedEpoch;
    const sourceLabel = native ? 'Codex message time' : 'first observed locally';
    const metrics = metricTitle();
    const title = `${formatFull(sourceEpoch)} · ${sourceLabel}${metrics ? `\n${metrics}` : ''}`;
    if (badge.getAttribute('title') !== title) badge.setAttribute('title', title);
    node.setAttribute(STAMP_ATTR, 'true');
  }

  function scan() {
    if (!document.body || window[APPLY_FLAG]) return;
    window[APPLY_FLAG] = true;
    try {
      assistantNodes().forEach(stamp);
      refreshBadgeMetricTitles();
      updateHud();
    } finally {
      queueMicrotask(() => { window[APPLY_FLAG] = false; });
    }
  }

  function refreshBadgeMetricTitles() {
    document.querySelectorAll(`[${BADGE_ATTR}]`).forEach(badge => {
      const host = badge.parentElement;
      if (host) stamp(host);
    });
  }

  function scheduleScan(delay = 80) {
    if (state.scanTimer) clearTimeout(state.scanTimer);
    state.scanTimer = setTimeout(() => {
      state.scanTimer = null;
      scan();
    }, delay);
  }

  function installObserver() {
    if (!document.body) {
      setTimeout(installObserver, 50);
      return;
    }
    state.observer?.disconnect?.();
    const observer = new MutationObserver(records => {
      if (window[APPLY_FLAG]) return;
      // Streamed text can produce very high mutation rates. Batch aggressively;
      // a timestamp is attached within ~80 ms of the first segment render.
      const meaningful = records.some(record => record.addedNodes?.length || record.type === 'attributes');
      if (meaningful) scheduleScan(80);
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        'data-content-search-assistant-turn-key',
        'data-local-conversation-final-assistant',
        'data-assistant-message-sent-time',
      ],
    });
    state.observer = observer;
    scan();
  }

  function numberAt(obj, ...paths) {
    for (const path of paths) {
      let value = obj;
      for (const key of path) value = value?.[key];
      if (Number.isFinite(Number(value))) return Number(value);
    }
    return null;
  }

  function consumeTokenObject(obj) {
    if (!obj || typeof obj !== 'object') return false;
    const type = String(obj.type || obj.event?.type || obj.payload?.type || '');
    let usage = obj.last_token_usage || obj.lastTokenUsage || obj.usage || obj.payload?.last_token_usage || obj.payload?.usage;
    const root = obj.payload && typeof obj.payload === 'object' ? obj.payload : obj;
    if ((!usage || typeof usage !== 'object') && type !== 'token_count') return false;
    usage = usage && typeof usage === 'object' ? usage : root;

    const output = numberAt(usage, ['output_tokens'], ['outputTokens']);
    const total = numberAt(usage, ['total_tokens'], ['totalTokens']);
    const input = numberAt(usage, ['input_tokens'], ['inputTokens']);
    const cached = numberAt(usage, ['cached_input_tokens'], ['cachedInputTokens']);
    const reasoning = numberAt(usage, ['reasoning_output_tokens'], ['reasoningTokens']);
    const contextWindow = numberAt(obj, ['model_context_window'], ['modelContextWindow'], ['payload', 'model_context_window']) ??
      numberAt(root, ['model_context_window'], ['modelContextWindow']);

    if (![output, total, input, cached, reasoning, contextWindow].some(Number.isFinite)) return false;
    const m = state.metrics;
    m.seen = true;
    if (Number.isFinite(output)) {
      if ((!Number.isFinite(m.outputTokens) || output < m.outputTokens) && output > 0) m.turnStartedAt = performance.now();
      if (!m.turnStartedAt && output > 0) m.turnStartedAt = performance.now();
      m.outputTokens = output;
    }
    if (Number.isFinite(total)) m.contextTokens = total;
    if (Number.isFinite(input)) m.inputTokens = input;
    if (Number.isFinite(cached)) m.cachedInputTokens = cached;
    if (Number.isFinite(reasoning)) m.reasoningTokens = reasoning;
    if (Number.isFinite(contextWindow) && contextWindow > 0) m.contextWindow = contextWindow;
    if (Number.isFinite(m.contextTokens) && Number.isFinite(m.contextWindow) && m.contextWindow > 0) {
      m.contextPercent = Math.max(0, Math.min(100, (m.contextTokens / m.contextWindow) * 100));
    }
    m.updatedAt = nowEpoch();
    m.done = false;
    scheduleScan(0);
    return true;
  }

  function consumePayload(value, depth = 0) {
    if (depth > 5 || value == null) return false;
    let hit = false;
    if (Array.isArray(value)) {
      for (const item of value) hit = consumePayload(item, depth + 1) || hit;
      return hit;
    }
    if (typeof value !== 'object') return false;
    hit = consumeTokenObject(value) || hit;
    for (const [key, child] of Object.entries(value)) {
      if (key === 'last_token_usage' || key === 'usage') continue;
      if (child && typeof child === 'object') hit = consumePayload(child, depth + 1) || hit;
    }
    return hit;
  }

  function consumeText(text) {
    if (!text || typeof text !== 'string') return;
    const trimmed = text.trim();
    if (!trimmed) return;
    // SSE/NDJSON: parse line-wise first. Ignore parse errors; this observer must
    // never affect the app's own network path.
    for (const rawLine of trimmed.split(/\r?\n/)) {
      const line = rawLine.replace(/^data:\s*/, '').trim();
      if (!line || line === '[DONE]') continue;
      if (line.includes('task_complete')) state.metrics.done = true;
      if (!line.includes('token_count') && !line.includes('last_token_usage') && !line.includes('model_context_window')) continue;
      try { consumePayload(JSON.parse(line)); } catch {}
    }
  }

  function outputSpeed() {
    const m = state.metrics;
    if (!Number.isFinite(m.outputTokens) || !m.turnStartedAt || m.outputTokens <= 0) return null;
    const seconds = Math.max((performance.now() - m.turnStartedAt) / 1000, 0.25);
    return m.outputTokens / seconds;
  }

  function ensureHud() {
    let hud = document.getElementById(HUD_ID);
    if (!hud && document.body) {
      hud = document.createElement('div');
      hud.id = HUD_ID;
      hud.setAttribute('aria-label', 'Codex output telemetry');
      document.body.appendChild(hud);
    }
    return hud;
  }

  function updateHud() {
    const hud = ensureHud();
    if (!hud) return;
    const m = state.metrics;
    if (!m.seen) {
      hud.removeAttribute('data-visible');
      return;
    }
    const parts = [];
    if (Number.isFinite(m.contextPercent)) parts.push(`ctx ${m.contextPercent.toFixed(1)}%`);
    const speed = outputSpeed();
    if (Number.isFinite(speed) && !m.done) parts.push(`${speed.toFixed(1)} tok/s`);
    if (Number.isFinite(m.outputTokens)) parts.push(`out ${compactNumber(m.outputTokens)}`);
    if (!parts.length) {
      hud.removeAttribute('data-visible');
      return;
    }
    const text = parts.join(' · ');
    if (hud.textContent !== text) hud.textContent = text;
    hud.setAttribute('data-visible', 'true');
  }

  function installFetchObserver() {
    if (state.fetchInstalled || typeof window.fetch !== 'function') return;
    state.fetchInstalled = true;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function casTelemetryFetch(input, init) {
      const response = await nativeFetch(input, init);
      try {
        const url = String(typeof input === 'string' ? input : input?.url || response.url || '');
        const contentType = String(response.headers?.get?.('content-type') || '');
        const likelyTelemetry = /responses|conversation|codex|backend-api|event-stream/i.test(url + ' ' + contentType);
        if (likelyTelemetry && response.body && typeof response.clone === 'function') {
          const clone = response.clone();
          void (async () => {
            try {
              const reader = clone.body?.getReader?.();
              if (!reader) return;
              const decoder = new TextDecoder();
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                consumeText(decoder.decode(value, { stream: true }));
              }
              consumeText(decoder.decode());
            } catch {}
          })();
        }
      } catch {}
      return response;
    };
  }

  function cleanup() {
    try { state.observer?.disconnect?.(); } catch {}
    if (state.scanTimer) clearTimeout(state.scanTimer);
    document.getElementById(HUD_ID)?.remove();
    document.getElementById(STYLE_ID)?.remove();
    document.querySelectorAll(`[${BADGE_ATTR}]`).forEach(node => node.remove());
    document.querySelectorAll(`[${STAMP_ATTR}]`).forEach(node => {
      node.removeAttribute(STAMP_ATTR);
      node.removeAttribute(OBSERVED_ATTR);
    });
  }

  state.rescan = scan;
  state.cleanup = cleanup;
  window[ROOT_MARKER] = state;

  ensureStyle();
  installFetchObserver();
  installObserver();
  return { ok: true, version: RUNTIME_VERSION, reused: false };
})();
