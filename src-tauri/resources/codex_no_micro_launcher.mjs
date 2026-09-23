import { spawn, spawnSync } from "node:child_process";
import { rename, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MODE = "micro-disabled-worker-safe"; // CAS-NO-LAGGING-R32-MICRO-ACCESSORY-GUARD
const EXPECTED_MARKER = "codex-micro-disabled-worker-safe";
const OUTPUT_TELEMETRY_RUNTIME = "r73.1";
const fixDirectory = path.dirname(fileURLToPath(import.meta.url));
const statusPath = process.env.CAS_NO_MICRO_STATUS_PATH || path.join(fixDirectory, "last-launch.json");
const packageVersion = process.env.CAS_NO_MICRO_PACKAGE_VERSION || "unknown";
const transferProxyPort = Number.parseInt(process.env.CAS_TRANSFER_PROXY_PORT || "0", 10) || 0;
const executable = process.argv[2];
const extraArguments = process.argv.slice(3);

if (!executable) {
  throw new Error("Usage: node codex_no_micro_launcher.mjs <Codex executable> [extra arguments]");
}

const startedAt = new Date().toISOString();
let phase = "preflight";
let child = null;
let inspectorPort = null;

try {
  inspectorPort = await reservePort();
  phase = "spawn-child-with-inspector";
  child = await spawnCodex(executable, inspectorPort, extraArguments);

  phase = "inspector-connected";
  const inspectorUrl = await waitForInspector(inspectorPort, child, 15_000);

  phase = "stub-evaluated";
  const evaluation = await installStub(inspectorUrl, child.pid, executable);
  if (evaluation !== EXPECTED_MARKER) {
    throw new Error(`stub marker mismatch: ${String(evaluation)}`);
  }

  phase = "stub-marker-verified";
  await delay(700);
  if (!isPidAlive(child.pid)) {
    throw new Error(`Codex exited after resume (exit ${child.exitCode})`);
  }

  phase = "child-alive-verified";
  child.unref();
  const status = {
    schemaVersion: 2,
    mode: MODE,
    packageName: "OpenAI.Codex",
    packageVersion,
    startedAt,
    injectedAt: new Date().toISOString(),
    verifiedAliveAt: new Date().toISOString(),
    processId: child.pid,
    inspectorPort,
    executablePath: executable,
    nodeVersion: process.version,
    workerPolicy: "empty-execArgv-when-unspecified",
    injection: {
      status: "success",
      phase,
      evaluation,
      globalMarker: true,
    },
    outputTelemetry: {
      status: "armed",
      runtime: OUTPUT_TELEMETRY_RUNTIME,
      timestampMode: "per-assistant-output",
      metricMode: "best-effort-live-stream",
    },
    transferRetryOverlay: {
      status: transferProxyPort > 0 ? "armed" : "disabled",
      proxyPort: transferProxyPort || null,
      mode: "transfer-only-connect-retry",
    },
    cleanup: "not-needed",
    statusFile: { status: "success" },
  };
  const writeResult = await writeStatusBestEffort(status);
  if (!writeResult.ok) {
    status.statusFile = { status: "write-failed", error: writeResult.error };
  }
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exitCode = 0;
} catch (error) {
  const cleanup = await cleanupOwnChild(child, executable);
  const status = {
    schemaVersion: 2,
    mode: MODE,
    packageName: "OpenAI.Codex",
    packageVersion,
    startedAt,
    failedAt: new Date().toISOString(),
    processId: child?.pid ?? null,
    inspectorPort,
    executablePath: executable,
    nodeVersion: process.version,
    workerPolicy: "empty-execArgv-when-unspecified",
    injection: {
      status: "failed",
      phase,
      error: safeError(error),
    },
    outputTelemetry: {
      status: "not-armed",
      runtime: OUTPUT_TELEMETRY_RUNTIME,
    },
    transferRetryOverlay: {
      status: "not-armed",
      proxyPort: transferProxyPort || null,
    },
    cleanup,
    statusFile: { status: "success" },
  };
  const writeResult = await writeStatusBestEffort(status);
  if (!writeResult.ok) {
    status.statusFile = { status: "write-failed", error: writeResult.error };
  }
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exitCode = 1;
}

function normalizedExecutable(value) {
  return path.resolve(value).replaceAll("\\", "/").toLowerCase();
}

function safeError(error) {
  const text = error instanceof Error ? error.message : String(error);
  return text.replace(/(Bearer\s+)[A-Za-z0-9._~+\/-]{16,}={0,2}/gi, "$1***").slice(0, 1500);
}

// CAS-R73-PER-OUTPUT-TIMESTAMP
// This renderer runtime is intentionally local/read-only: it adds presentation-only DOM nodes
// and observes cloned response streams. It never edits Codex session JSONL, app.asar, prompts,
// auth, or model responses. Stable assistant selectors / MutationObserver ideas were informed by
// MIT-licensed KevinKE93/Codex-Monitor and Minghou-Lei/codex-context-used-meter; the optional
// output-rate concept was informed by MIT-licensed petergpt/codex-speed-monitor.
function outputTelemetryRuntimeSource(proxyPort) {
  const retryStatusUrl =
    Number.isInteger(proxyPort) && proxyPort > 0 && proxyPort <= 65535
      ? JSON.stringify(`http://127.0.0.1:${proxyPort}/_cas/transfer-retry-status`)
      : "null";
  return String.raw`
(() => {
  'use strict';

  const VERSION = 'r73.1';
  const ROOT_KEY = '__casOutputTelemetryRuntime';
  const STYLE_ID = 'cas-output-telemetry-style';
  const BADGE_ATTR = 'data-cas-output-timestamp';
  const HOST_ATTR = 'data-cas-output-stamped';
  const FIRST_SEEN_ATTR = 'data-cas-output-first-seen';
  const HUD_ID = 'cas-output-telemetry-hud';
  const APPLY_KEY = '__casOutputTelemetryApplying';
  const RETRY_STATUS_URL = ${retryStatusUrl};
  const RETRY_MARKER = 'CAS-R94-1-TRANSFER-RETRY-CODEX-OVERLAY';
  const RETRY_CHIP_ATTR = 'data-cas-transfer-retry-chip';

  const old = window[ROOT_KEY];
  if (old && old.version === VERSION && old.retryFeature === RETRY_MARKER) {
    try { old.rescan(); } catch {}
    return { ok: true, version: VERSION, reused: true };
  }
  try { old && old.observer && old.observer.disconnect(); } catch {}
  try { old && old.cleanup && old.cleanup(); } catch {}

  const state = {
    version: VERSION,
    retryFeature: RETRY_MARKER,
    observer: null,
    timer: null,
    fetchInstalled: false,
    retryTimer: null,
    retry: {
      active: false,
      activeCount: 0,
      attempt: 0,
      maxRetries: 0,
      infinite: false,
      elapsedMs: 0,
      maxDurationMs: 0,
      delayMs: 0,
      provider: '',
      reason: '',
    },
    metrics: {
      seen: false,
      contextTokens: null,
      contextWindow: null,
      contextPercent: null,
      inputTokens: null,
      cachedInputTokens: null,
      outputTokens: null,
      reasoningTokens: null,
      outputBase: 0,
      startedAt: null,
      done: false,
    },
  };

  function pad2(v) { return String(v).padStart(2, '0'); }
  function clock(epoch) {
    const d = new Date(epoch);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  function fullTime(epoch) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }).format(new Date(epoch));
    } catch {
      return new Date(epoch).toLocaleString();
    }
  }
  function shortNumber(value) {
    if (!Number.isFinite(value)) return '--';
    if (Math.abs(value) >= 1000000) return (value / 1000000).toFixed(1) + 'M';
    if (Math.abs(value) >= 1000) return (value / 1000).toFixed(1) + 'K';
    return String(Math.round(value));
  }

  function retryHours(ms) {
    return (Math.max(0, Number(ms) || 0) / 3600000).toFixed(2);
  }

  function transferRetryLabel(retry) {
    const denominator = retry && retry.infinite ? '∞' : String(Number(retry && retry.maxRetries) || 0);
    let label = 'TRANSFER RETRY ' + (Number(retry && retry.attempt) || 0) + '/' + denominator;
    if (retry && retry.infinite && Number(retry.maxDurationMs) > 0) {
      label += ' · ' + retryHours(retry.elapsedMs) + 'h/' + retryHours(retry.maxDurationMs) + 'h';
    }
    return label;
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '[' + HOST_ATTR + '=\"true\"]{position:relative!important;}',
      '[' + BADGE_ATTR + ']{position:absolute;top:2px;right:4px;z-index:20;display:inline-flex;align-items:center;padding:1px 5px;border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:999px;background:color-mix(in srgb,Canvas 88%,transparent);color:color-mix(in srgb,CanvasText 58%,transparent);box-shadow:0 1px 4px color-mix(in srgb,CanvasText 8%,transparent);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);font:9px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.01em;white-space:nowrap;pointer-events:auto;cursor:default;user-select:text;opacity:.80;}',
      '[' + BADGE_ATTR + ']:hover{opacity:1;}',
      '#' + HUD_ID + '{position:fixed;right:10px;bottom:10px;z-index:2147483646;display:none;align-items:center;gap:7px;padding:3px 7px;border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:999px;background:color-mix(in srgb,Canvas 88%,transparent);color:color-mix(in srgb,CanvasText 64%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 2px 8px color-mix(in srgb,CanvasText 10%,transparent);font:10px/1.3 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;pointer-events:none;}',
      '#' + HUD_ID + '[data-visible=\"true\"]{display:inline-flex;}',
      '#' + HUD_ID + '[data-transfer-retrying=\"true\"]{border-color:color-mix(in srgb,#e6a700 58%,transparent);background:color-mix(in srgb,#5a4300 82%,Canvas);color:#ffe08a;font-weight:700;}',
      '[' + RETRY_CHIP_ATTR + ']{display:inline-flex;align-items:center;margin-left:8px;padding:1px 6px;border:1px solid color-mix(in srgb,#e6a700 55%,transparent);border-radius:999px;background:color-mix(in srgb,#5a4300 78%,Canvas);color:#ffe08a;font:700 9px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:none;}',
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  function assistantNodes() {
    const selectors = [
      '[data-content-search-assistant-turn-key]',
      '[data-local-conversation-final-assistant]',
    ];
    const seen = new Set();
    const nodes = [];
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach(function(raw) {
        const node = raw.closest('[data-content-search-assistant-turn-key]') ||
          raw.closest('[data-local-conversation-final-assistant]') || raw;
        if (seen.has(node) || node.closest('#' + HUD_ID)) return;
        seen.add(node);
        nodes.push(node);
      });
    }
    document.querySelectorAll('[data-chatgpt-conversation-turn=\"true\"]').forEach(function(turn) {
      if (seen.has(turn)) return;
      const assistantMarker = turn.querySelector('[data-assistant-message-sent-time],[data-message-author-role=\"assistant\"],[data-local-conversation-final-assistant]');
      if (!assistantMarker) return;
      seen.add(turn);
      nodes.push(turn);
    });
    return nodes;
  }

  function nativeTime(node) {
    const sent = node.querySelector('[data-assistant-message-sent-time]') || node.querySelector('time[datetime]');
    if (!sent) return null;
    const values = [
      sent.getAttribute('datetime'),
      sent.getAttribute('data-timestamp'),
      sent.getAttribute('title'),
      sent.getAttribute('aria-label'),
      sent.textContent,
    ].filter(Boolean).map(function(v) { return String(v).trim(); }).filter(Boolean);
    for (const value of values) {
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 1000000000) {
        const epoch = numeric > 10000000000 ? numeric : numeric * 1000;
        return { epoch: epoch, label: clock(epoch), source: 'Codex message time' };
      }
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return { epoch: parsed, label: clock(parsed), source: 'Codex message time' };
      const match = value.match(/\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s?(AM|PM)?\b/i);
      if (match) return { epoch: null, label: match[0], source: 'Codex message time' };
    }
    return null;
  }

  function outputSpeed() {
    const m = state.metrics;
    if (!Number.isFinite(m.outputTokens) || !Number.isFinite(m.outputBase) || !m.startedAt) return null;
    const delta = Math.max(0, m.outputTokens - m.outputBase);
    if (delta <= 0) return null;
    const seconds = Math.max((performance.now() - m.startedAt) / 1000, 0.25);
    return delta / seconds;
  }

  function metricTitle() {
    const m = state.metrics;
    if (!m.seen) return '';
    const lines = [];
    if (Number.isFinite(m.contextPercent)) lines.push('Context: ' + m.contextPercent.toFixed(1) + '% (' + shortNumber(m.contextTokens) + '/' + shortNumber(m.contextWindow) + ')');
    if (Number.isFinite(m.inputTokens)) lines.push('Input: ' + shortNumber(m.inputTokens));
    if (Number.isFinite(m.cachedInputTokens)) lines.push('Cached input: ' + shortNumber(m.cachedInputTokens));
    if (Number.isFinite(m.outputTokens)) lines.push('Output: ' + shortNumber(m.outputTokens));
    if (Number.isFinite(m.reasoningTokens)) lines.push('Reasoning: ' + shortNumber(m.reasoningTokens));
    const speed = outputSpeed();
    if (Number.isFinite(speed)) lines.push('Speed: ' + speed.toFixed(1) + ' tok/s');
    return lines.join('\n');
  }

  function stamp(node) {
    if (!(node instanceof Element)) return;
    ensureStyle();
    let firstSeen = Number(node.getAttribute(FIRST_SEEN_ATTR));
    if (!Number.isFinite(firstSeen) || firstSeen <= 0) {
      firstSeen = Date.now();
      node.setAttribute(FIRST_SEEN_ATTR, String(firstSeen));
    }
    const native = nativeTime(node);
    const epoch = native && native.epoch ? native.epoch : firstSeen;
    const label = native && native.label ? native.label : clock(firstSeen);
    const source = native && native.source ? native.source : 'first observed locally';
    let badge = Array.from(node.children || []).find(function(child) { return child.hasAttribute && child.hasAttribute(BADGE_ATTR); });
    if (!badge) {
      badge = document.createElement('span');
      badge.setAttribute(BADGE_ATTR, 'true');
      badge.setAttribute('aria-label', 'Assistant output timestamp');
      node.appendChild(badge);
    }
    if (badge.textContent !== label) badge.textContent = label;
    const metrics = metricTitle();
    const title = fullTime(epoch) + ' · ' + source + (metrics ? '\n' + metrics : '');
    if (badge.getAttribute('title') !== title) badge.setAttribute('title', title);
    node.setAttribute(HOST_ATTR, 'true');
  }

  function ensureHud() {
    let hud = document.getElementById(HUD_ID);
    if (!hud && document.body) {
      hud = document.createElement('div');
      hud.id = HUD_ID;
      hud.setAttribute('aria-label', 'Codex live token telemetry');
      document.body.appendChild(hud);
    }
    return hud;
  }

  function updateRetryChips() {
    const retry = state.retry;
    const existing = Array.from(document.querySelectorAll('[' + RETRY_CHIP_ATTR + ']'));
    if (!retry || !retry.active) {
      existing.forEach(function(node) { node.remove(); });
      return 0;
    }
    const label = transferRetryLabel(retry);
    const bars = Array.from(document.querySelectorAll(
      '[data-cas-status-inside-composer="true"][data-cas-status-owner="r94-inline-safe"]'
    ));
    // Never pretend a global proxy retry belongs to a specific pane when split
    // panes/subagents are visible. With exactly one safe composer bar, render
    // there; otherwise use the global Transfer HUD fallback.
    if (bars.length !== 1 || !(bars[0] instanceof Element)) {
      existing.forEach(function(node) { node.remove(); });
      return 0;
    }
    const bar = bars[0];
    let chip = Array.from(bar.children || []).find(function(child) {
      return child instanceof Element && child.hasAttribute(RETRY_CHIP_ATTR);
    });
    if (!chip) {
      chip = document.createElement('span');
      chip.setAttribute(RETRY_CHIP_ATTR, 'true');
      chip.setAttribute('aria-label', 'Transfer upstream retry');
      bar.appendChild(chip);
    }
    if (chip.textContent !== label) chip.textContent = label;
    chip.setAttribute(
      'title',
      'Transfer is retrying a connect-stage upstream failure. Codex native retry budget remains unchanged.'
    );
    existing.forEach(function(node) {
      if (node !== chip) node.remove();
    });
    return 1;
  }

  function updateHud() {    const hud = ensureHud();
    if (!hud) return;
    const r = state.retry;
    const retryChips = updateRetryChips();
    if (r && r.active) {
      if (retryChips > 0) {
        hud.removeAttribute('data-visible');
        hud.removeAttribute('data-transfer-retrying');
        hud.removeAttribute('title');
        return;
      }
      const retryText = transferRetryLabel(r) +
        (r.activeCount > 1 ? ' · active ' + r.activeCount : '') +
        (r.delayMs ? ' · wait ' + r.delayMs + 'ms' : '');
      if (hud.textContent !== retryText) hud.textContent = retryText;
      hud.setAttribute('data-visible', 'true');
      hud.setAttribute('data-transfer-retrying', 'true');
      hud.setAttribute('title', 'Transfer is retrying an upstream connect-stage failure. Codex native retry budget is unchanged.');
      return;
    }
    hud.removeAttribute('data-transfer-retrying');
    hud.removeAttribute('title');
    const m = state.metrics;
    if (!m.seen) {
      hud.removeAttribute('data-visible');
      return;
    }
    const parts = [];
    if (Number.isFinite(m.contextPercent)) parts.push('ctx ' + m.contextPercent.toFixed(1) + '%');
    const speed = outputSpeed();
    if (Number.isFinite(speed) && !m.done) parts.push(speed.toFixed(1) + ' tok/s');
    if (Number.isFinite(m.outputTokens)) parts.push('out ' + shortNumber(m.outputTokens));
    if (!parts.length) {
      hud.removeAttribute('data-visible');
      return;
    }
    const text = parts.join(' · ');
    if (hud.textContent !== text) hud.textContent = text;
    hud.setAttribute('data-visible', 'true');
  }

  function scan() {
    if (!document.body || window[APPLY_KEY]) return;
    window[APPLY_KEY] = true;
    try {
      assistantNodes().forEach(stamp);
      updateHud();
    } finally {
      queueMicrotask(function() { window[APPLY_KEY] = false; });
    }
  }

  function schedule(delay) {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(function() {
      state.timer = null;
      scan();
    }, typeof delay === 'number' ? delay : 80);
  }

  async function pollTransferRetryStatus() {
    if (!RETRY_STATUS_URL) return;
    let nextDelay = 1500;
    try {
      const response = await window.fetch(RETRY_STATUS_URL, { cache: 'no-store' });
      if (!response.ok) throw new Error('retry status http ' + response.status);
      const value = await response.json();
      const retry = state.retry;
      retry.active = value && value.active === true;
      retry.activeCount = Number(value && value.activeCount) || 0;
      retry.attempt = Number(value && value.attempt) || 0;
      retry.maxRetries = Number(value && value.maxRetries) || 0;
      retry.infinite = value && value.infinite === true;
      retry.elapsedMs = Number(value && value.elapsedMs) || 0;
      retry.maxDurationMs = Number(value && value.maxDurationMs) || 0;
      retry.delayMs = Number(value && value.delayMs) || 0;
      retry.provider = String((value && value.provider) || '');
      retry.reason = String((value && value.reason) || '');
      nextDelay = retry.active ? 200 : ((retry.maxRetries > 0 || retry.infinite) ? 700 : 2000);
      schedule(0);
    } catch {
      state.retry.active = false;
      schedule(0);
      nextDelay = 2000;
    } finally {
      state.retryTimer = setTimeout(pollTransferRetryStatus, nextDelay);
    }
  }

  function installTransferRetryPoll() {
    if (!RETRY_STATUS_URL || state.retryTimer) return;
    state.retryTimer = setTimeout(pollTransferRetryStatus, 50);
  }

  function installObserver() {
    if (!document.body) {
      setTimeout(installObserver, 50);
      return;
    }
    const observer = new MutationObserver(function(records) {
      if (window[APPLY_KEY]) return;
      const meaningful = records.some(function(record) { return record.addedNodes && record.addedNodes.length; });
      if (meaningful) schedule(80);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    state.observer = observer;
    scan();
  }

  function numberAt(obj, paths) {
    for (const path of paths) {
      let value = obj;
      for (const key of path) value = value && value[key];
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
    return null;
  }

  function consumeTokenObject(obj) {
    if (!obj || typeof obj !== 'object') return false;
    const payload = obj.payload && typeof obj.payload === 'object' ? obj.payload : obj;
    const type = String(obj.type || payload.type || '');
    let usage = obj.last_token_usage || obj.lastTokenUsage || obj.usage || payload.last_token_usage || payload.lastTokenUsage || payload.usage;
    if ((!usage || typeof usage !== 'object') && type !== 'token_count') return false;
    usage = usage && typeof usage === 'object' ? usage : payload;

    const input = numberAt(usage, [['input_tokens'], ['inputTokens']]);
    const cached = numberAt(usage, [['cached_input_tokens'], ['cachedInputTokens']]);
    const output = numberAt(usage, [['output_tokens'], ['outputTokens']]);
    const reasoning = numberAt(usage, [['reasoning_output_tokens'], ['reasoningTokens']]);
    const contextWindow = numberAt(obj, [['model_context_window'], ['modelContextWindow'], ['payload', 'model_context_window'], ['payload', 'modelContextWindow']]) ||
      numberAt(payload, [['model_context_window'], ['modelContextWindow']]);
    if (![input, cached, output, reasoning, contextWindow].some(Number.isFinite)) return false;

    const m = state.metrics;
    m.seen = true;
    if (Number.isFinite(output)) {
      if (!Number.isFinite(m.outputTokens) || output < m.outputTokens || m.done) {
        m.outputBase = Math.max(0, output - 1);
        m.startedAt = performance.now();
        m.done = false;
      } else if (!m.startedAt && output > 0) {
        m.outputBase = 0;
        m.startedAt = performance.now();
      }
      m.outputTokens = output;
    }
    if (Number.isFinite(input)) m.inputTokens = input;
    if (Number.isFinite(cached)) m.cachedInputTokens = cached;
    if (Number.isFinite(reasoning)) m.reasoningTokens = reasoning;
    if (Number.isFinite(contextWindow) && contextWindow > 0) m.contextWindow = contextWindow;
    // Codex-Monitor and rollout JSONL both treat current context pressure as
    // last_token_usage.input_tokens / model_context_window, not cumulative session total.
    if (Number.isFinite(m.inputTokens)) m.contextTokens = m.inputTokens;
    if (Number.isFinite(m.contextTokens) && Number.isFinite(m.contextWindow) && m.contextWindow > 0) {
      m.contextPercent = Math.max(0, Math.min(100, (m.contextTokens / m.contextWindow) * 100));
    }
    schedule(0);
    return true;
  }

  function consumeValue(value, depth) {
    depth = depth || 0;
    if (depth > 5 || value == null) return false;
    if (Array.isArray(value)) return value.some(function(item) { return consumeValue(item, depth + 1); });
    if (typeof value !== 'object') return false;
    let hit = consumeTokenObject(value);
    for (const key of Object.keys(value)) {
      if (key === 'last_token_usage' || key === 'lastTokenUsage' || key === 'usage') continue;
      if (value[key] && typeof value[key] === 'object') hit = consumeValue(value[key], depth + 1) || hit;
    }
    return hit;
  }

  function consumeText(text) {
    if (!text || typeof text !== 'string') return;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/^data:\s*/, '').trim();
      if (!line || line === '[DONE]') continue;
      if (line.includes('task_complete')) state.metrics.done = true;
      if (!line.includes('token_count') && !line.includes('last_token_usage') && !line.includes('model_context_window')) continue;
      try { consumeValue(JSON.parse(line), 0); } catch {}
    }
  }

  function installFetchObserver() {
    if (state.fetchInstalled || typeof window.fetch !== 'function') return;
    state.fetchInstalled = true;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function(input, init) {
      const response = await nativeFetch(input, init);
      try {
        const url = String(typeof input === 'string' ? input : (input && input.url) || response.url || '');
        const type = String(response.headers && response.headers.get ? response.headers.get('content-type') || '' : '');
        if (/responses|conversation|codex|backend-api|event-stream/i.test(url + ' ' + type) && response.body && response.clone) {
          const clone = response.clone();
          void (async function() {
            try {
              const reader = clone.body && clone.body.getReader ? clone.body.getReader() : null;
              if (!reader) return;
              const decoder = new TextDecoder();
              while (true) {
                const result = await reader.read();
                if (result.done) break;
                consumeText(decoder.decode(result.value, { stream: true }));
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
    try { state.observer && state.observer.disconnect(); } catch {}
    if (state.timer) clearTimeout(state.timer);
    if (state.retryTimer) clearTimeout(state.retryTimer);
    const hud = document.getElementById(HUD_ID);
    if (hud) hud.remove();
    document.querySelectorAll('[' + RETRY_CHIP_ATTR + ']').forEach(function(node) { node.remove(); });
    const style = document.getElementById(STYLE_ID);
    if (style) style.remove();
    document.querySelectorAll('[' + BADGE_ATTR + ']').forEach(function(node) { node.remove(); });
    document.querySelectorAll('[' + HOST_ATTR + ']').forEach(function(node) {
      node.removeAttribute(HOST_ATTR);
      node.removeAttribute(FIRST_SEEN_ATTR);
    });
  }

  state.rescan = scan;
  state.cleanup = cleanup;
  window[ROOT_KEY] = state;
  ensureStyle();
  installFetchObserver();
  installTransferRetryPoll();
  installObserver();
  return { ok: true, version: VERSION, reused: false };
})()
`;
}

function stubExpression(expectedPid, expectedExecutable) {
  const expectedPath = JSON.stringify(normalizedExecutable(expectedExecutable));
  const telemetrySource = JSON.stringify(outputTelemetryRuntimeSource(transferProxyPort));
  return String.raw`
(() => {
  const actualPath = String(process.execPath || "").replaceAll("\\", "/").toLowerCase();
  if (process.pid !== ${expectedPid}) {
    throw new Error("No Micro inspector target PID mismatch");
  }
  if (actualPath !== ${expectedPath}) {
    throw new Error("No Micro inspector target executable mismatch");
  }

  const Module = process.getBuiltinModule("module");
  const originalLoad = Module._load;
  const telemetrySource = ${telemetrySource};
  const isInspectorArgument = (argument) =>
    typeof argument === "string" && /^--inspect(?:-brk)?(?:=|$)/.test(argument);

  process.execArgv.splice(
    0,
    process.execArgv.length,
    ...process.execArgv.filter((argument) => !isInspectorArgument(argument)),
  );
  process.argv.splice(
    0,
    process.argv.length,
    ...process.argv.filter((argument) => !isInspectorArgument(argument)),
  );

  const workerThreads = process.getBuiltinModule("worker_threads");
  const NativeWorker = workerThreads.Worker;
  if (!NativeWorker.__codexNoInspectWrapper) {
    class CodexNoInspectWorker extends NativeWorker {
      constructor(filename, options = {}) {
        const safeOptions = options ?? {};
        super(filename, {
          ...safeOptions,
          execArgv: safeOptions.execArgv ?? [],
        });
      }
    }
    Object.defineProperty(CodexNoInspectWorker, "__codexNoInspectWrapper", {
      value: true,
    });
    workerThreads.Worker = CodexNoInspectWorker;
  }

  const stub = {
    __codexMicroDisabledLocal: true,
    ConnectionEventType: {
      CONNECTED: "CONNECTED",
      DISCONNECTED: "DISCONNECTED",
      ERROR: "ERROR",
    },
    DeviceType: { Project2077: "Project2077" },
    OAILightingEffect: { off: 0, breath: 1, solid: 2, snake: 3 },
    WLDeviceDiscovery: class NoCodexMicroDeviceDiscovery {
      findWLDevices() { return []; }
    },
    WLDeviceCommImpl: class NoCodexMicroDeviceComm {
      onConnectionEvent() { return () => {}; }
      async connect() {}
      async disconnect() {}
    },
    RPCApiOAI: class NoCodexMicroApi {
      onHidReceived() { return () => {}; }
      onJoystickMove() { return () => {}; }
      async sendLightingConfig() { return true; }
      async sendThreadsLighting() { return true; }
      async getDeviceStatus() { return {}; }
    },
  };

  let outputTelemetryArmed = false;
  const telemetryBoundContents = new WeakSet();
  const attachOutputTelemetry = (contents) => {
    if (!contents || telemetryBoundContents.has(contents)) return;
    try {
      const type = contents.getType?.();
      if (type && type !== "window" && type !== "webview") return;
    } catch {}
    telemetryBoundContents.add(contents);
    const inject = () => {
      try {
        if (contents.isDestroyed?.()) return;
        const promise = contents.executeJavaScript?.(telemetrySource, true);
        promise?.catch?.(() => {});
      } catch {}
    };
    try { contents.on?.("dom-ready", inject); } catch {}
    try { inject(); } catch {}
  };
  const armOutputTelemetry = (electron) => {
    if (outputTelemetryArmed || !electron?.app || !electron?.webContents) return;
    outputTelemetryArmed = true;
    globalThis.__CODEX_OUTPUT_TELEMETRY_R73__ = true;
    try {
      electron.app.on("web-contents-created", (_event, contents) => attachOutputTelemetry(contents));
    } catch {}
    const attachExisting = () => {
      try { electron.webContents.getAllWebContents().forEach(attachOutputTelemetry); } catch {}
    };
    try {
      if (electron.app.isReady?.()) attachExisting();
      else electron.app.whenReady?.().then(attachExisting).catch(() => {});
    } catch {}
  };

  Module._load = function codexMicroDisabledLoader(request, parent, isMain) {
    if (request === "@worklouder/device-kit-oai") return stub;
    const loaded = Reflect.apply(originalLoad, this, arguments);
    if (request === "electron" || loaded?.app?.on && loaded?.webContents) {
      try { armOutputTelemetry(loaded); } catch {}
    }
    return loaded;
  };

  globalThis.__CODEX_MICRO_DISABLED_LOCAL__ = true;
  globalThis.__CODEX_NO_LAGGING_MICRO_ACCESSORY_GUARD__ = true;
  setTimeout(() => {
    try { process.getBuiltinModule("inspector").close(); } catch {}
  }, 500);
  return "${EXPECTED_MARKER}";
})()
`;
}

async function reservePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Could not reserve a loopback inspector port");
  }
  const selectedPort = address.port;
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
  return selectedPort;
}

async function spawnCodex(executablePath, port, args) {
  const spawned = spawn(
    executablePath,
    [`--inspect-brk=127.0.0.1:${port}`, ...args],
    {
      detached: true,
      env: process.env,
      stdio: "ignore",
      windowsHide: false,
    },
  );
  await new Promise((resolve, reject) => {
    const onError = (error) => {
      spawned.off("spawn", onSpawn);
      reject(new Error(`Codex spawn failed: ${safeError(error)}`));
    };
    const onSpawn = () => {
      spawned.off("error", onError);
      resolve();
    };
    spawned.once("error", onError);
    spawned.once("spawn", onSpawn);
  });
  if (!spawned.pid) throw new Error("Codex spawn succeeded without a PID");
  return spawned;
}

async function waitForInspector(portNumber, childProcess, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "inspector did not respond";

  while (Date.now() < deadline) {
    if (!isPidAlive(childProcess.pid)) {
      throw new Error(`Codex exited before the startup hook (exit ${childProcess.exitCode})`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${portNumber}/json/list`, {
        signal: AbortSignal.timeout(750),
      });
      if (response.ok) {
        const targets = await response.json();
        const candidates = Array.isArray(targets)
          ? targets.filter((entry) => typeof entry?.webSocketDebuggerUrl === "string")
          : [];
        if (candidates.length === 1) return candidates[0].webSocketDebuggerUrl;
        if (candidates.length > 1) lastError = `inspector returned ${candidates.length} targets`;
      } else {
        lastError = `inspector returned HTTP ${response.status}`;
      }
    } catch (error) {
      lastError = safeError(error);
    }
    await delay(100);
  }

  throw new Error(`Startup hook timed out: ${lastError}`);
}

async function installStub(webSocketUrl, expectedPid, expectedExecutable) {
  return await new Promise((resolve, reject) => {
    const socket = new WebSocket(webSocketUrl);
    let runtimeEnabled = false;
    let debuggerEnabled = false;
    let continuedToFirstLine = false;
    let callFrameId = null;
    let evaluationValue = null;
    let settled = false;

    const finishError = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try { socket.close(); } catch {}
      reject(error instanceof Error ? error : new Error(String(error)));
    };
    const finishSuccess = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(evaluationValue);
      setTimeout(() => {
        try { socket.close(); } catch {}
      }, 150);
    };
    const timeout = setTimeout(() => {
      finishError(new Error("Startup hook WebSocket timed out"));
    }, 10_000);

    socket.addEventListener("error", () => {
      finishError(new Error("Startup hook WebSocket failed"));
    }, { once: true });
    socket.addEventListener("close", () => {
      if (!settled) finishError(new Error("Startup hook WebSocket closed before resume completed"));
    });

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ id: 1, method: "Runtime.enable" }));
      socket.send(JSON.stringify({ id: 2, method: "Debugger.enable" }));
    }, { once: true });

    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch (error) {
        finishError(new Error(`Invalid inspector JSON: ${safeError(error)}`));
        return;
      }
      if (message.error && message.id) {
        finishError(new Error(`Inspector command ${message.id} failed: ${safeError(message.error.message || message.error)}`));
        return;
      }
      if (message.id === 1) runtimeEnabled = true;
      if (message.id === 2) debuggerEnabled = true;

      if (runtimeEnabled && debuggerEnabled && !continuedToFirstLine) {
        continuedToFirstLine = true;
        socket.send(JSON.stringify({ id: 3, method: "Runtime.runIfWaitingForDebugger" }));
      }

      if (message.method === "Debugger.paused" && !callFrameId) {
        callFrameId = message.params?.callFrames?.[0]?.callFrameId ?? null;
        if (!callFrameId) {
          finishError(new Error("Startup hook did not receive a usable call frame"));
          return;
        }
        socket.send(JSON.stringify({
          id: 4,
          method: "Debugger.evaluateOnCallFrame",
          params: {
            callFrameId,
            expression: stubExpression(expectedPid, expectedExecutable),
            returnByValue: true,
            silent: false,
          },
        }));
        return;
      }

      if (message.id === 4) {
        const exception = message.result?.exceptionDetails;
        if (exception) {
          finishError(new Error(
            exception.exception?.description ?? exception.text ?? JSON.stringify(exception),
          ));
          return;
        }
        evaluationValue = message.result?.result?.value ?? null;
        if (evaluationValue !== EXPECTED_MARKER) {
          finishError(new Error(`stub evaluation returned unexpected marker: ${String(evaluationValue)}`));
          return;
        }
        socket.send(JSON.stringify({
          id: 5,
          method: "Debugger.evaluateOnCallFrame",
          params: {
            callFrameId,
            expression: "globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true && globalThis.__CODEX_OUTPUT_TELEMETRY_R73__ === true",
            returnByValue: true,
            silent: true,
          },
        }));
        return;
      }

      if (message.id === 5) {
        if (message.result?.result?.value !== true) {
          finishError(new Error("global No Lagging / output telemetry marker was not set"));
          return;
        }
        socket.send(JSON.stringify({ id: 6, method: "Debugger.resume" }));
        return;
      }

      if (message.id === 6) finishSuccess();
    });
  });
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function cleanupOwnChild(childProcess, expectedExecutable) {
  if (!childProcess?.pid) return "not-started";
  if (!isPidAlive(childProcess.pid)) return "already-exited";

  try {
    childProcess.kill("SIGKILL");
  } catch {}
  if (await waitForPidExit(childProcess.pid, 1200)) return "terminated-own-child";

  if (process.platform === "win32") {
    const ps = spawnSync(
      "powershell.exe",
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        [
          "$ErrorActionPreference = 'Stop'",
          "$pidToStop = [int]$env:CAS_NO_MICRO_CHILD_PID",
          "$expected = $env:CAS_NO_MICRO_EXPECTED_EXE",
          "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$pidToStop\"",
          "if ($null -eq $p) { exit 0 }",
          "if (-not $p.ExecutablePath) { exit 3 }",
          "if (-not [string]::Equals($p.ExecutablePath, $expected, [System.StringComparison]::OrdinalIgnoreCase)) { exit 4 }",
          "Stop-Process -Id $pidToStop -Force -ErrorAction Stop",
        ].join("; "),
      ],
      {
        stdio: "ignore",
        windowsHide: true,
        env: {
          ...process.env,
          CAS_NO_MICRO_CHILD_PID: String(childProcess.pid),
          CAS_NO_MICRO_EXPECTED_EXE: path.resolve(expectedExecutable),
        },
      },
    );
    if (ps.status === 0 && await waitForPidExit(childProcess.pid, 1600)) {
      return "terminated-own-child-powershell";
    }
  }

  return "cleanup-failed";
}

async function waitForPidExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isPidAlive(pid)) return true;
    await delay(60);
  }
  return !isPidAlive(pid);
}

async function writeStatusBestEffort(status) {
  try {
    const temporaryPath = `${statusPath}.tmp`;
    await rm(temporaryPath, { force: true });
    await writeFile(temporaryPath, `${JSON.stringify(status, null, 2)}\n`, "utf8");
    try {
      await rename(temporaryPath, statusPath);
    } catch (error) {
      // Windows can reject rename-over-existing in some filesystem/AV combinations.
      // Status is diagnostic only, so replace the old breadcrumb and retry once.
      if (process.platform !== "win32") throw error;
      await rm(statusPath, { force: true });
      await rename(temporaryPath, statusPath);
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: safeError(error) };
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
