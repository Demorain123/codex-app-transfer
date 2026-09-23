param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LauncherPath = Join-Path $RepoRoot 'src-tauri\resources\codex_no_micro_launcher.mjs'
$TauriPath = Join-Path $RepoRoot 'src-tauri\tauri.conf.json'
$AppLayoutPath = Join-Path $RepoRoot 'frontend\src\layout\AppLayout.vue'
$TopTabPath = Join-Path $RepoRoot 'frontend\src\layout\TopTabBar.vue'
$BaseBuilderPath = Join-Path $PSScriptRoot 'build-r73-local.ps1'

foreach ($Path in @($LauncherPath, $TauriPath, $AppLayoutPath, $TopTabPath, $BaseBuilderPath)) {
    if (-not (Test-Path $Path)) { throw "r74 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Original = @{}
foreach ($Path in @($LauncherPath, $TauriPath, $AppLayoutPath, $TopTabPath, $BaseBuilderPath)) {
    $Original[$Path] = [System.IO.File]::ReadAllText($Path)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r74 local finalizer could not find expected text: $Label" }
    return $Text.Replace($Old, $New)
}

# CAS-VISIBLE-IDENTITY-OVERRIDE
# Preview wrappers may keep the historical rXX build pipeline/markers while
# asking the final visible package identity to use a dotted revision such as
# r94.1. Environment variables are inherited by all nested generated builders,
# so this hook reaches the actual visible-identity owner without renaming the
# r75-r94 runtime chain.
$VisibleRevisionOverride = $env:CAS_TRANSFER_VISIBLE_REVISION
$VisibleVersionOverride = $env:CAS_TRANSFER_VISIBLE_VERSION
if ([string]::IsNullOrWhiteSpace($VisibleRevisionOverride) -xor
    [string]::IsNullOrWhiteSpace($VisibleVersionOverride)) {
    throw 'visible identity override requires both CAS_TRANSFER_VISIBLE_REVISION and CAS_TRANSFER_VISIBLE_VERSION'
}

# The r74 renderer runtime is deliberately injected only through the existing No-Lagging B path.
# It does not patch app.asar, session JSONL, prompts, responses, auth or provider traffic.
$NewTelemetryFunction = @'
function outputTelemetryRuntimeSource(proxyPort) {
  const retryStatusUrl =
    Number.isInteger(proxyPort) && proxyPort > 0 && proxyPort <= 65535
      ? JSON.stringify(`http://127.0.0.1:${proxyPort}/_cas/transfer-retry-status`)
      : "null";
  return String.raw`
(() => {
  'use strict';

  const VERSION = 'r74.0';
  const ROOT_KEY = '__casOutputTelemetryRuntime';
  const STYLE_ID = 'cas-output-telemetry-style';
  const BADGE_ATTR = 'data-cas-output-timestamp';
  const HOST_ATTR = 'data-cas-output-stamped';
  const FIRST_SEEN_ATTR = 'data-cas-output-first-seen';
  const STATUS_ID = 'cas-live-statusbar';
  const MIRROR_ID = 'cas-usage-mirror';
  const ANALYTICS_ID = 'cas-telemetry-analytics';
  const HISTORY_KEY = 'cas-r74-live-history';
  const SEEN_KEY = 'cas-r74-segment-times';
  const HISTORY_LIMIT = 360;
  const SAMPLE_INTERVAL_MS = 10000;
  const CACHE_LIMIT = 800;

  // CAS-R94-1-TRANSFER-RETRY-GENERATED-CARRY
  // Generated-chain owner for the Transfer-only retry indicator. This survives
  // r75-r94 telemetry transforms instead of being lost when r74 replaces the
  // tracked launcher telemetry function.
  const RETRY_STATUS_URL = ${retryStatusUrl};
  const RETRY_ID = 'cas-transfer-retry-status-chip';
  const RETRY_MARKER = 'CAS-R94-1-TRANSFER-RETRY-CODEX-OVERLAY';

  const old = window[ROOT_KEY];
  if (old && old.version === VERSION && old.retryFeature === RETRY_MARKER) {
    try { old.refresh && old.refresh(); } catch {}
    return { ok: true, version: VERSION, reused: true };
  }
  try { old && old.cleanup && old.cleanup(); } catch {}

  const state = {
    version: VERSION,
    observer: null,
    timer: null,
    pollTimer: null,
    sampleTimer: null,
    retryTimer: null,
    retryFeature: RETRY_MARKER,
    retry: {
      statusAvailable: false,
      active: false,
      activeCount: 0,
      attempt: 0,
      maxRetries: 0,
      infinite: false,
      elapsedMs: 0,
      maxDurationMs: 0,
      delayMs: 0,
      reason: '',
    },
    baselineKeys: new Set(),
    metrics: {
      seen: false,
      contextTokens: null,
      contextWindow: null,
      contextPercent: null,
      inputTokens: null,
      cachedInputTokens: null,
      outputTokens: null,
      reasoningTokens: null,
      sessionTotalTokens: null,
      cacheHitPercent: null,
      outputBase: null,
      speedStartedAt: null,
      outputSpeed: null,
      nativeSpeed: null,
      nativeCacheHit: null,
      nativeSessionTotal: null,
      model: null,
      updatedAt: 0,
      done: false,
    },
    history: [],
    lastSampleAt: 0,
    nativePanelVisible: false,
  };

  function pad2(value) { return String(value).padStart(2, '0'); }
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
    } catch { return new Date(epoch).toLocaleString(); }
  }
  function shortNumber(value) {
    if (!Number.isFinite(value)) return '--';
    if (Math.abs(value) >= 1000000000) return (value / 1000000000).toFixed(2).replace(/\.00$/, '') + 'B';
    if (Math.abs(value) >= 1000000) return (value / 1000000).toFixed(2).replace(/\.00$/, '') + 'M';
    if (Math.abs(value) >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return String(Math.round(value));
  }
  function retryHours(ms) {
    return (Math.max(0, Number(ms) || 0) / 3600000).toFixed(2);
  }
  function retryRemainingMs(retry) {
    const max = Math.max(0, Number(retry && retry.maxDurationMs) || 0);
    const elapsed = Math.max(0, Number(retry && retry.elapsedMs) || 0);
    return Math.max(0, max - elapsed);
  }

  function transferRetryLabel(retry) {
    const denominator = retry && retry.infinite ? '∞' : String(Number(retry && retry.maxRetries) || 0);
    const attempt = Number(retry && retry.attempt) || 0;
    let label = (retry && retry.active ? 'TRANSFER RETRY ' : 'TRANSFER RETRY READY ') + attempt + '/' + denominator;
    if (retry && retry.infinite && Number(retry.maxDurationMs) > 0) {
      const max = Number(retry.maxDurationMs) || 0;
      if (retry.active) {
        label += ' · left ' + retryHours(retryRemainingMs(retry)) + 'h/' + retryHours(max) + 'h';
      } else {
        label += ' · window ' + retryHours(max) + 'h';
      }
    }
    return label;
  }

  function parseCompactNumber(text) {
    const match = String(text || '').trim().match(/^([\d,.]+)\s*([KMB])?$/i);
    if (!match) return null;
    const base = Number(match[1].replace(/,/g, ''));
    if (!Number.isFinite(base)) return null;
    const scale = ({ K: 1e3, M: 1e6, B: 1e9 })[String(match[2] || '').toUpperCase()] || 1;
    return base * scale;
  }
  function normalizedText(node) {
    return String(node && (node.innerText || node.textContent) || '').replace(/\s+/g, ' ').trim();
  }
  function isVisible(node) {
    if (!(node instanceof Element)) return false;
    if (!node.isConnected) return false;
    try {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
      return node.getClientRects().length > 0;
    } catch { return true; }
  }
  function insideOwnUi(node) {
    if (!(node instanceof Element)) return false;
    return !!node.closest('#' + STATUS_ID + ',#' + MIRROR_ID + ',#' + ANALYTICS_ID);
  }
  function insideComposer(node) {
    if (!(node instanceof Element)) return false;
    return !!node.closest('[data-codex-composer-root],[data-codex-composer="true"],[data-thread-find-composer="true"],form,[contenteditable="true"],textarea');
  }
  function simpleHash(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }
  function readJsonStorage(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return value == null ? fallback : value;
    } catch { return fallback; }
  }
  function writeJsonStorage(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  }
  function readSeenCache() {
    const value = readJsonStorage(SEEN_KEY, {});
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  }
  function rememberSegmentTime(key, epoch) {
    if (!key || !Number.isFinite(epoch)) return;
    try {
      const cache = readSeenCache();
      cache[key] = epoch;
      const entries = Object.entries(cache)
        .map(function(entry) { return [entry[0], Number(entry[1])]; })
        .filter(function(entry) { return Number.isFinite(entry[1]); })
        .sort(function(a, b) { return b[1] - a[1]; })
        .slice(0, CACHE_LIMIT);
      writeJsonStorage(SEEN_KEY, Object.fromEntries(entries));
    } catch {}
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '[' + HOST_ATTR + '=\"true\"]{position:relative!important;}',
      '[' + BADGE_ATTR + ']{position:absolute;top:2px;right:4px;z-index:22;display:inline-flex;align-items:center;padding:1px 5px;border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:999px;background:color-mix(in srgb,Canvas 91%,transparent);color:color-mix(in srgb,CanvasText 58%,transparent);box-shadow:0 1px 4px color-mix(in srgb,CanvasText 8%,transparent);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);font:9px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.78;}',
      '[' + BADGE_ATTR + ']:hover{opacity:1;}',
      '#' + STATUS_ID + '{box-sizing:border-box;width:100%;margin:0 0 5px 0;padding:4px 9px;display:flex;align-items:center;gap:8px;overflow:hidden;border:1px solid color-mix(in srgb,CanvasText 12%,transparent);border-radius:11px;background:color-mix(in srgb,Canvas 90%,transparent);color:color-mix(in srgb,CanvasText 72%,transparent);box-shadow:0 1px 5px color-mix(in srgb,CanvasText 7%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);font:10px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;-webkit-app-region:no-drag;cursor:pointer;}',
      '#' + STATUS_ID + ' .cas-status-item{white-space:nowrap;}',
      '#' + STATUS_ID + ' .cas-status-muted{color:color-mix(in srgb,CanvasText 44%,transparent);}',
      '#' + STATUS_ID + ' .cas-status-spacer{flex:1 1 auto;min-width:2px;}',
      '#' + MIRROR_ID + '{position:fixed;right:10px;top:88px;z-index:2147483645;width:min(232px,calc(100vw - 20px));box-sizing:border-box;padding:10px;border:1px solid color-mix(in srgb,CanvasText 12%,transparent);border-radius:14px;background:color-mix(in srgb,Canvas 92%,transparent);color:CanvasText;box-shadow:0 8px 28px color-mix(in srgb,CanvasText 12%,transparent);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);font:11px/1.4 system-ui,sans-serif;-webkit-app-region:no-drag;cursor:pointer;}',
      '#' + MIRROR_ID + '[hidden]{display:none!important;}',
      '#' + MIRROR_ID + ' .cas-mirror-title{display:flex;align-items:center;justify-content:space-between;font-weight:650;margin-bottom:7px;}',
      '#' + MIRROR_ID + ' .cas-mirror-line{display:flex;justify-content:space-between;gap:8px;margin-top:5px;color:color-mix(in srgb,CanvasText 66%,transparent);}',
      '#' + MIRROR_ID + ' .cas-mirror-track{height:5px;margin-top:5px;border-radius:999px;background:color-mix(in srgb,CanvasText 11%,transparent);overflow:hidden;}',
      '#' + MIRROR_ID + ' .cas-mirror-fill{height:100%;border-radius:999px;background:color-mix(in srgb,CanvasText 42%,transparent);}',
      '#' + ANALYTICS_ID + '{position:fixed;z-index:2147483647;width:min(430px,calc(100vw - 24px));max-height:min(520px,calc(100vh - 24px));overflow:auto;box-sizing:border-box;padding:12px;border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:14px;background:color-mix(in srgb,Canvas 96%,transparent);color:CanvasText;box-shadow:0 12px 38px color-mix(in srgb,CanvasText 18%,transparent);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);font:11px/1.4 system-ui,sans-serif;-webkit-app-region:no-drag;}',
      '#' + ANALYTICS_ID + '[hidden]{display:none!important;}',
      '#' + ANALYTICS_ID + ' .cas-analytics-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px;font-weight:650;}',
      '#' + ANALYTICS_ID + ' .cas-chart{margin-top:9px;padding:8px;border:1px solid color-mix(in srgb,CanvasText 10%,transparent);border-radius:10px;background:color-mix(in srgb,Canvas 82%,transparent);}',
      '#' + ANALYTICS_ID + ' .cas-chart-title{display:flex;justify-content:space-between;gap:8px;margin-bottom:5px;color:color-mix(in srgb,CanvasText 70%,transparent);}',
      '#' + ANALYTICS_ID + ' svg{display:block;width:100%;height:70px;overflow:visible;}',
      '#' + ANALYTICS_ID + ' .cas-breakdown{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:5px 8px;margin-top:10px;}',
      '#' + ANALYTICS_ID + ' .cas-breakdown-track{height:5px;border-radius:999px;background:color-mix(in srgb,CanvasText 10%,transparent);overflow:hidden;}',
      '#' + ANALYTICS_ID + ' .cas-breakdown-fill{height:100%;background:color-mix(in srgb,CanvasText 42%,transparent);}',
      '@media(max-width:1100px){#' + MIRROR_ID + '{right:7px;top:78px;width:205px;padding:8px;}#' + STATUS_ID + '{gap:6px;font-size:9px;padding:3px 7px;}#' + STATUS_ID + ' .cas-status-secondary{display:none;}}',
      '@media(max-width:760px){#' + MIRROR_ID + '{top:auto;bottom:88px;width:auto;max-width:calc(100vw - 14px);padding:6px 8px;}#' + MIRROR_ID + ' .cas-mirror-extra,#' + MIRROR_ID + ' .cas-mirror-track{display:none;}#' + MIRROR_ID + ' .cas-mirror-title{margin:0;gap:10px;}#' + STATUS_ID + ' .cas-status-tertiary{display:none;}}',
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  const ASSISTANT_ROOT_SELECTOR = [
    '[data-content-search-assistant-turn-key]',
    '[data-local-conversation-final-assistant]',
    '[data-chatgpt-conversation-turn="true"]',
  ].join(',');

  function assistantRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideOwnUi(element) || insideComposer(element)) return null;
    let root = element.closest(ASSISTANT_ROOT_SELECTOR);
    if (!root) return null;
    if (root.matches('[data-chatgpt-conversation-turn="true"]')) {
      const assistantMarker = root.querySelector('[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[data-assistant-message-sent-time]');
      if (!assistantMarker) return null;
    }
    return root;
  }

  function nativeTime(node) {
    if (!(node instanceof Element)) return null;
    const sent = node.querySelector('[data-assistant-message-sent-time],time[datetime]') ||
      node.closest('[data-assistant-message-sent-time]');
    if (!sent) return null;
    const values = [
      sent.getAttribute('datetime'), sent.getAttribute('data-timestamp'), sent.getAttribute('title'),
      sent.getAttribute('aria-label'), sent.textContent,
    ].filter(Boolean).map(function(value) { return String(value).trim(); }).filter(Boolean);
    for (const value of values) {
      const numeric = Number(value);
      if (Number.isFinite(numeric) && numeric > 1000000000) {
        const epoch = numeric > 10000000000 ? numeric : numeric * 1000;
        return { epoch: epoch, source: 'Codex message time' };
      }
      const parsed = Date.parse(value);
      if (Number.isFinite(parsed)) return { epoch: parsed, source: 'Codex message time' };
    }
    return null;
  }

  function meaningfulDirectChildren(parent) {
    if (!(parent instanceof Element)) return [];
    return Array.from(parent.children || []).filter(function(child) {
      if (!isVisible(child) || insideOwnUi(child) || insideComposer(child)) return false;
      if (/^(SCRIPT|STYLE|NOSCRIPT|SVG)$/i.test(child.tagName || '')) return false;
      const text = normalizedText(child);
      if (text.length < 3) return false;
      const display = (() => { try { return getComputedStyle(child).display; } catch { return 'block'; } })();
      return display !== 'inline';
    });
  }

  function finalSurfaceFor(node, root) {
    if (!(root instanceof Element)) return null;
    if (root.matches('[data-local-conversation-final-assistant]')) return root;
    const element = node instanceof Element ? node : node && node.parentElement;
    const closest = element && element.closest('[data-local-conversation-final-assistant]');
    if (closest && root.contains(closest)) return closest;
    const final = root.querySelector('[data-local-conversation-final-assistant]');
    if (final && element && final.contains(element)) return final;
    return null;
  }

  function semanticProgressSurface(node, root) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element) return null;
    const selector = '[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"],[data-turn-key],[data-message-id]';
    const candidate = element.closest(selector);
    if (candidate && root.contains(candidate) && !insideComposer(candidate)) return candidate;
    return null;
  }

  function structuralProgressSurface(node, root) {
    let current = node instanceof Element ? node : node && node.parentElement;
    if (!current) return null;
    while (current && current !== root && root.contains(current)) {
      const parent = current.parentElement;
      if (!parent || !root.contains(parent)) break;
      const siblings = meaningfulDirectChildren(parent);
      if (siblings.length >= 2 && siblings.includes(current)) {
        const tag = String(current.tagName || '').toUpperCase();
        if (!/^(P|SPAN|A|LI|UL|OL|CODE|PRE|TABLE|THEAD|TBODY|TR|TD|TH)$/.test(tag)) return current;
      }
      current = parent;
    }
    return null;
  }

  function segmentForMutation(node, root) {
    if (!root || insideComposer(node instanceof Element ? node : node && node.parentElement)) return null;
    const final = finalSurfaceFor(node, root);
    if (final) return final;
    const semantic = semanticProgressSurface(node, root);
    if (semantic) return semantic;
    return structuralProgressSurface(node, root) || root;
  }

  function segmentIndex(segment, root) {
    if (!(segment instanceof Element) || !(root instanceof Element)) return 0;
    const parent = segment.parentElement;
    if (!parent) return 0;
    const siblings = meaningfulDirectChildren(parent);
    const index = siblings.indexOf(segment);
    return index >= 0 ? index : 0;
  }

  function segmentKey(segment, root) {
    const rootId = root && (
      root.getAttribute('data-content-search-assistant-turn-key') ||
      root.getAttribute('data-turn-key') || root.getAttribute('data-message-id') || ''
    );
    const text = normalizedText(segment).slice(0, 700);
    if (!text) return '';
    return simpleHash(String(location.pathname || '') + '|' + String(location.hash || '') + '|' + rootId + '|' + segmentIndex(segment, root) + '|' + text);
  }

  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    const existing = segment.querySelector(':scope > [' + BADGE_ATTR + ']');
    if (existing) return;
    const cache = readSeenCache();
    const remembered = Number(cache[key]);
    const when = Number.isFinite(remembered) && remembered > 0 ? remembered : epoch;
    const badge = document.createElement('span');
    badge.setAttribute(BADGE_ATTR, 'true');
    badge.setAttribute('aria-label', 'Assistant output timestamp');
    badge.textContent = clock(when);
    badge.title = fullTime(when) + ' · ' + (remembered ? 'remembered local output time' : source);
    segment.appendChild(badge);
    segment.setAttribute(HOST_ATTR, 'true');
    segment.setAttribute(FIRST_SEEN_ATTR, String(when));
    rememberSegmentTime(key, when);
  }

  function baselineExistingDom() {
    document.querySelectorAll(ASSISTANT_ROOT_SELECTOR).forEach(function(root) {
      if (!(root instanceof Element) || insideComposer(root)) return;
      const final = root.matches('[data-local-conversation-final-assistant]') ? root : root.querySelector('[data-local-conversation-final-assistant]');
      if (final) {
        const key = segmentKey(final, root);
        if (key) state.baselineKeys.add(key);
        const native = nativeTime(final) || nativeTime(root);
        if (native) stampSegment(final, root, native.epoch, native.source);
      }
      const nodes = root.querySelectorAll('*');
      let count = 0;
      for (const node of nodes) {
        if (count >= 500) break;
        if (!isVisible(node) || insideComposer(node) || normalizedText(node).length < 3) continue;
        const key = segmentKey(node, root);
        if (key) state.baselineKeys.add(key);
        count += 1;
      }
    });
  }

  function handleOutputMutation(node) {
    const root = assistantRootFor(node);
    if (!root) return;
    const segment = segmentForMutation(node, root);
    if (!segment || !isVisible(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    const native = nativeTime(segment) || nativeTime(root);
    if (state.baselineKeys.has(key) && !native) return;
    const cache = readSeenCache();
    const remembered = Number(cache[key]);
    if (Number.isFinite(remembered) && remembered > 0) {
      stampSegment(segment, root, remembered, 'remembered local output time');
      return;
    }
    stampSegment(segment, root, native ? native.epoch : Date.now(), native ? native.source : 'first observed live locally');
  }

  function installOutputObserver() {
    if (!document.body) { setTimeout(installOutputObserver, 80); return; }
    baselineExistingDom();
    const observer = new MutationObserver(function(records) {
      for (const record of records) {
        if (record.type === 'characterData') {
          handleOutputMutation(record.target);
          continue;
        }
        for (const added of record.addedNodes || []) {
          handleOutputMutation(added);
          if (added instanceof Element) {
            const roots = added.matches(ASSISTANT_ROOT_SELECTOR) ? [added] : Array.from(added.querySelectorAll(ASSISTANT_ROOT_SELECTOR));
            roots.forEach(function(root) {
              const probe = root.querySelector('[data-local-conversation-final-assistant]') || root.firstElementChild || root;
              handleOutputMutation(probe);
            });
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    state.observer = observer;
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
    let last = obj.last_token_usage || obj.lastTokenUsage || payload.last_token_usage || payload.lastTokenUsage;
    let total = obj.total_token_usage || obj.totalTokenUsage || payload.total_token_usage || payload.totalTokenUsage;
    let usage = obj.usage || payload.usage;
    if ((!last || typeof last !== 'object') && usage && typeof usage === 'object') last = usage;
    if ((!last || typeof last !== 'object') && type !== 'token_count') return false;
    last = last && typeof last === 'object' ? last : payload;
    total = total && typeof total === 'object' ? total : null;

    const input = numberAt(last, [['input_tokens'], ['inputTokens'], ['prompt_tokens'], ['promptTokens']]);
    const cached = numberAt(last, [['cached_input_tokens'], ['cachedInputTokens'], ['cached_tokens'], ['cachedTokens']]);
    const output = numberAt(last, [['output_tokens'], ['outputTokens'], ['completion_tokens'], ['completionTokens']]);
    const reasoning = numberAt(last, [['reasoning_output_tokens'], ['reasoningTokens']]);
    const contextWindow = numberAt(obj, [['model_context_window'], ['modelContextWindow'], ['payload', 'model_context_window'], ['payload', 'modelContextWindow']]) || numberAt(payload, [['model_context_window'], ['modelContextWindow']]);
    const sessionTotal = total ? numberAt(total, [['total_tokens'], ['totalTokens']]) : null;
    if (![input, cached, output, reasoning, contextWindow, sessionTotal].some(Number.isFinite)) return false;

    const m = state.metrics;
    const now = performance.now();
    m.seen = true;
    if (Number.isFinite(output)) {
      if (!Number.isFinite(m.outputTokens) || output < m.outputTokens || m.done) {
        m.outputBase = Math.max(0, output - 1);
        m.speedStartedAt = now;
        m.done = false;
      } else if (!m.speedStartedAt) {
        m.outputBase = m.outputTokens || 0;
        m.speedStartedAt = now;
      }
      m.outputTokens = output;
      if (Number.isFinite(m.outputBase) && m.speedStartedAt) {
        const delta = Math.max(0, output - m.outputBase);
        const seconds = Math.max((now - m.speedStartedAt) / 1000, 0.25);
        if (delta > 0) m.outputSpeed = delta / seconds;
      }
    }
    if (Number.isFinite(input)) m.inputTokens = input;
    if (Number.isFinite(cached)) m.cachedInputTokens = cached;
    if (Number.isFinite(reasoning)) m.reasoningTokens = reasoning;
    if (Number.isFinite(contextWindow) && contextWindow > 0) m.contextWindow = contextWindow;
    if (Number.isFinite(sessionTotal)) m.sessionTotalTokens = sessionTotal;
    if (Number.isFinite(m.inputTokens) && Number.isFinite(m.contextWindow) && m.contextWindow > 0) {
      m.contextTokens = m.inputTokens;
      m.contextPercent = Math.max(0, Math.min(100, (m.contextTokens / m.contextWindow) * 100));
    }
    if (Number.isFinite(m.cachedInputTokens) && Number.isFinite(m.inputTokens) && m.inputTokens > 0) {
      m.cacheHitPercent = Math.max(0, Math.min(100, (m.cachedInputTokens / m.inputTokens) * 100));
    }
    m.updatedAt = Date.now();
    refreshUi();
    return true;
  }

  function consumeValue(value, depth) {
    depth = depth || 0;
    if (depth > 6 || value == null) return false;
    if (Array.isArray(value)) return value.some(function(item) { return consumeValue(item, depth + 1); });
    if (typeof value !== 'object') return false;
    let hit = consumeTokenObject(value);
    for (const key of Object.keys(value)) {
      if (['last_token_usage','lastTokenUsage','total_token_usage','totalTokenUsage','usage'].includes(key)) continue;
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
      if (!/token_count|last_token_usage|total_token_usage|model_context_window|usage/i.test(line)) continue;
      try { consumeValue(JSON.parse(line), 0); } catch {}
    }
  }

  function installFetchObserver() {
    if (typeof window.fetch !== 'function' || window.fetch.__casR74Wrapped) return;
    const nativeFetch = window.fetch.bind(window);
    const wrapped = async function(input, init) {
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
    wrapped.__casR74Wrapped = true;
    wrapped.__casNativeFetch = nativeFetch;
    window.fetch = wrapped;
  }

  function findNativeUsagePanel() {
    const candidates = [];
    const all = document.querySelectorAll('aside,section,div');
    for (const node of all) {
      if (!(node instanceof Element) || insideOwnUi(node) || !isVisible(node)) continue;
      const text = normalizedText(node);
      if (text.length < 20 || text.length > 2200) continue;
      if (!/(Usage|用量|上下文)/i.test(text)) continue;
      if (!/(token\/s|tokens\/s|缓存命中|cache hit|context)/i.test(text)) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width < 150 || rect.height < 100) continue;
      const score = (rect.left > innerWidth * 0.55 ? 5 : 0) + (text.length < 1000 ? 2 : 0) + (/token\/s|tokens\/s/i.test(text) ? 3 : 0);
      candidates.push({ node: node, text: text, score: score, area: rect.width * rect.height });
    }
    candidates.sort(function(a, b) { return b.score - a.score || a.area - b.area; });
    return candidates.length ? candidates[0] : null;
  }

  function readNativeUsage() {
    const candidate = findNativeUsagePanel();
    state.nativePanelVisible = !!candidate;
    if (!candidate) return;
    const text = candidate.text;
    const speedMatch = text.match(/([\d.]+)\s*tokens?\/?s/i);
    if (speedMatch) state.metrics.nativeSpeed = Number(speedMatch[1]);
    const cacheMatch = text.match(/(?:缓存命中|cache\s*hit)\s*([\d.]+)%/i);
    if (cacheMatch) state.metrics.nativeCacheHit = Number(cacheMatch[1]);
    const totalMatch = text.match(/(?:累计|session\s*total|total)\s*([\d.,]+\s*[KMB]?)/i);
    if (totalMatch) state.metrics.nativeSessionTotal = parseCompactNumber(totalMatch[1].replace(/\s+/g, ''));
    const ctxMatch = text.match(/([\d.,]+\s*[KMB]?)\s*\/\s*([\d.,]+\s*[KMB]?)\s*[·•]?\s*([\d.]+)%/i);
    if (ctxMatch) {
      const used = parseCompactNumber(ctxMatch[1].replace(/\s+/g, ''));
      const limit = parseCompactNumber(ctxMatch[2].replace(/\s+/g, ''));
      const percent = Number(ctxMatch[3]);
      if (Number.isFinite(used)) state.metrics.contextTokens = used;
      if (Number.isFinite(limit)) state.metrics.contextWindow = limit;
      if (Number.isFinite(percent)) state.metrics.contextPercent = percent;
      state.metrics.seen = true;
    }
  }

  function readModelLabel() {
    const trigger = document.querySelector('[data-codex-intelligence-trigger="true"]');
    const text = normalizedText(trigger);
    if (text && text.length < 90) state.metrics.model = text;
  }

  function findComposerRoot() {
    const direct = document.querySelector('[data-codex-composer-root],[data-thread-find-composer="true"],[data-codex-composer="true"]');
    if (direct && isVisible(direct)) return direct;
    const editable = document.querySelector('.ProseMirror[contenteditable="true"],[role="textbox"][contenteditable="true"],textarea');
    if (!editable) return null;
    return editable.closest('[data-testid*="composer"],.composer-surface-chrome,form') || editable.parentElement;
  }

  function ensureStatusBar() {
    let bar = document.getElementById(STATUS_ID);
    if (!bar) {
      bar = document.createElement('div');
      bar.id = STATUS_ID;
      bar.title = 'Click for live telemetry charts';
      bar.addEventListener('click', function(event) {
        event.stopPropagation();
        toggleAnalytics(bar);
      });
    }
    const composer = findComposerRoot();
    if (!composer || !composer.parentElement) return bar;
    if (bar.parentElement !== composer.parentElement || bar.nextSibling !== composer) {
      composer.parentElement.insertBefore(bar, composer);
    }
    return bar;
  }

  function effectiveSpeed() {
    const m = state.metrics;
    return Number.isFinite(m.nativeSpeed) ? m.nativeSpeed : m.outputSpeed;
  }
  function effectiveCacheHit() {
    const m = state.metrics;
    return Number.isFinite(m.nativeCacheHit) ? m.nativeCacheHit : m.cacheHitPercent;
  }
  function effectiveSessionTotal() {
    const m = state.metrics;
    return Number.isFinite(m.nativeSessionTotal) ? m.nativeSessionTotal : m.sessionTotalTokens;
  }

  function statusHtml() {
    const m = state.metrics;
    const context = Number.isFinite(m.contextPercent) ? ('ctx ' + m.contextPercent.toFixed(1) + '%') : 'ctx --';
    const input = 'in ' + shortNumber(m.inputTokens);
    const output = 'out ' + shortNumber(m.outputTokens);
    const cache = Number.isFinite(effectiveCacheHit()) ? ('cache ' + effectiveCacheHit().toFixed(1) + '%') : 'cache --';
    const speed = Number.isFinite(effectiveSpeed()) ? (effectiveSpeed().toFixed(1) + ' tok/s') : '-- tok/s';
    const session = 'session ' + shortNumber(effectiveSessionTotal());
    const model = m.model || '';
    return [
      '<span class="cas-status-item">' + context + '</span>',
      '<span class="cas-status-item">' + input + '</span>',
      '<span class="cas-status-item">' + output + '</span>',
      '<span class="cas-status-item cas-status-secondary">' + cache + '</span>',
      '<span class="cas-status-item">' + speed + '</span>',
      '<span class="cas-status-item cas-status-tertiary">' + session + '</span>',
      '<span class="cas-status-spacer"></span>',
      '<span class="cas-status-item cas-status-muted cas-status-secondary">' + model.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</span>',
    ].join('');
  }

  function ensureMirror() {
    let mirror = document.getElementById(MIRROR_ID);
    if (!mirror && document.body) {
      mirror = document.createElement('div');
      mirror.id = MIRROR_ID;
      mirror.addEventListener('click', function(event) {
        event.stopPropagation();
        toggleAnalytics(mirror);
      });
      document.body.appendChild(mirror);
    }
    return mirror;
  }

  function renderMirror() {
    const mirror = ensureMirror();
    if (!mirror) return;
    if (state.nativePanelVisible) { mirror.hidden = true; return; }
    mirror.hidden = false;
    const m = state.metrics;
    const context = Number.isFinite(m.contextPercent) ? m.contextPercent : null;
    const speed = effectiveSpeed();
    const cache = effectiveCacheHit();
    const session = effectiveSessionTotal();
    mirror.innerHTML = [
      '<div class="cas-mirror-title"><span>Usage</span><span>' + (Number.isFinite(speed) ? speed.toFixed(1) + ' tok/s' : '-- tok/s') + '</span></div>',
      '<div class="cas-mirror-line"><span>Context</span><span>' + (Number.isFinite(context) ? (shortNumber(m.contextTokens) + ' / ' + shortNumber(m.contextWindow) + ' · ' + context.toFixed(1) + '%') : '--') + '</span></div>',
      '<div class="cas-mirror-track"><div class="cas-mirror-fill" style="width:' + (Number.isFinite(context) ? Math.max(0, Math.min(100, context)) : 0) + '%"></div></div>',
      '<div class="cas-mirror-line cas-mirror-extra"><span>Cache hit</span><span>' + (Number.isFinite(cache) ? cache.toFixed(1) + '%' : '--') + '</span></div>',
      '<div class="cas-mirror-line cas-mirror-extra"><span>Input / Output</span><span>' + shortNumber(m.inputTokens) + ' / ' + shortNumber(m.outputTokens) + '</span></div>',
      '<div class="cas-mirror-line cas-mirror-extra"><span>Session</span><span>' + shortNumber(session) + '</span></div>',
    ].join('');
  }

  function loadHistory() {
    const values = readJsonStorage(HISTORY_KEY, []);
    return Array.isArray(values) ? values.filter(function(item) { return item && Number.isFinite(Number(item.t)); }).slice(-HISTORY_LIMIT) : [];
  }
  state.history = loadHistory();

  function sampleHistory(force) {
    const m = state.metrics;
    if (!m.seen) return;
    const now = Date.now();
    if (!force && now - state.lastSampleAt < SAMPLE_INTERVAL_MS) return;
    state.lastSampleAt = now;
    state.history.push({
      t: now,
      context: Number.isFinite(m.contextPercent) ? m.contextPercent : null,
      speed: Number.isFinite(effectiveSpeed()) ? effectiveSpeed() : null,
      cache: Number.isFinite(effectiveCacheHit()) ? effectiveCacheHit() : null,
      input: Number.isFinite(m.inputTokens) ? m.inputTokens : null,
      output: Number.isFinite(m.outputTokens) ? m.outputTokens : null,
      reasoning: Number.isFinite(m.reasoningTokens) ? m.reasoningTokens : null,
      session: Number.isFinite(effectiveSessionTotal()) ? effectiveSessionTotal() : null,
    });
    state.history = state.history.slice(-HISTORY_LIMIT);
    writeJsonStorage(HISTORY_KEY, state.history);
  }

  function makeSparkline(values, maxHint) {
    const clean = values.map(function(value) { return Number.isFinite(value) ? value : null; });
    const finite = clean.filter(Number.isFinite);
    if (finite.length < 2) return '<div style="height:70px;display:grid;place-items:center;color:color-mix(in srgb,CanvasText 40%,transparent)">Waiting for samples…</div>';
    const width = 360;
    const height = 70;
    const min = Math.min.apply(null, finite.concat([0]));
    const max = Math.max.apply(null, finite.concat(Number.isFinite(maxHint) ? [maxHint] : []));
    const range = Math.max(max - min, 1);
    const points = [];
    for (let i = 0; i < clean.length; i += 1) {
      const value = clean[i];
      if (!Number.isFinite(value)) continue;
      const x = clean.length <= 1 ? 0 : (i / (clean.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 6) - 3;
      points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    return '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<line x1="0" y1="' + (height - 1) + '" x2="' + width + '" y2="' + (height - 1) + '" stroke="currentColor" opacity=".10" />' +
      '<line x1="0" y1="' + (height / 2) + '" x2="' + width + '" y2="' + (height / 2) + '" stroke="currentColor" opacity=".08" stroke-dasharray="3 3" />' +
      '<polyline fill="none" stroke="currentColor" opacity=".62" stroke-width="2" vector-effect="non-scaling-stroke" points="' + points.join(' ') + '" />' +
      '</svg>';
  }

  function breakdownRows() {
    const m = state.metrics;
    const rows = [
      ['Input', m.inputTokens], ['Cached', m.cachedInputTokens], ['Output', m.outputTokens], ['Reasoning', m.reasoningTokens],
    ];
    const max = Math.max.apply(null, rows.map(function(row) { return Number(row[1]) || 0; }).concat([1]));
    return rows.map(function(row) {
      const value = Number(row[1]);
      const width = Number.isFinite(value) ? Math.max(1, Math.min(100, (value / max) * 100)) : 0;
      return '<span>' + row[0] + '</span><div class="cas-breakdown-track"><div class="cas-breakdown-fill" style="width:' + width + '%"></div></div><span>' + shortNumber(value) + '</span>';
    }).join('');
  }

  function renderAnalytics() {
    const panel = document.getElementById(ANALYTICS_ID);
    if (!panel || panel.hidden) return;
    const recent = state.history.slice(-180);
    const ctx = recent.map(function(item) { return Number(item.context); });
    const speed = recent.map(function(item) { return Number(item.speed); });
    const cache = recent.map(function(item) { return Number(item.cache); });
    const latestCtx = ctx.filter(Number.isFinite).slice(-1)[0];
    const latestSpeed = speed.filter(Number.isFinite).slice(-1)[0];
    const latestCache = cache.filter(Number.isFinite).slice(-1)[0];
    panel.innerHTML = [
      '<div class="cas-analytics-header"><span>Live telemetry · recent samples</span><button data-cas-close style="border:0;background:transparent;color:inherit;cursor:pointer;font:inherit">×</button></div>',
      '<div class="cas-chart"><div class="cas-chart-title"><span>Context used</span><span>' + (Number.isFinite(latestCtx) ? latestCtx.toFixed(1) + '%' : '--') + '</span></div>' + makeSparkline(ctx, 100) + '</div>',
      '<div class="cas-chart"><div class="cas-chart-title"><span>Output speed</span><span>' + (Number.isFinite(latestSpeed) ? latestSpeed.toFixed(1) + ' tok/s' : '--') + '</span></div>' + makeSparkline(speed, null) + '</div>',
      '<div class="cas-chart"><div class="cas-chart-title"><span>Cache hit</span><span>' + (Number.isFinite(latestCache) ? latestCache.toFixed(1) + '%' : '--') + '</span></div>' + makeSparkline(cache, 100) + '</div>',
      '<div class="cas-breakdown">' + breakdownRows() + '</div>',
    ].join('');
    const close = panel.querySelector('[data-cas-close]');
    if (close) close.addEventListener('click', function(event) { event.stopPropagation(); panel.hidden = true; });
  }

  function ensureAnalytics() {
    let panel = document.getElementById(ANALYTICS_ID);
    if (!panel && document.body) {
      panel = document.createElement('div');
      panel.id = ANALYTICS_ID;
      panel.hidden = true;
      document.body.appendChild(panel);
    }
    return panel;
  }

  function positionAnalytics(anchor, panel) {
    const rect = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
    const gap = 7;
    const width = Math.min(430, innerWidth - 24);
    const left = rect ? Math.max(12, Math.min(innerWidth - width - 12, rect.right - width)) : Math.max(12, innerWidth - width - 12);
    const topCandidate = rect ? rect.top - 390 - gap : 100;
    const top = Math.max(12, Math.min(innerHeight - 220, topCandidate > 12 ? topCandidate : ((rect ? rect.bottom : 80) + gap)));
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
  }

  function toggleAnalytics(anchor) {
    const panel = ensureAnalytics();
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      sampleHistory(true);
      positionAnalytics(anchor, panel);
      renderAnalytics();
    }
  }

  function renderTransferRetry() {
    let chip = document.getElementById(RETRY_ID);
    const retry = state.retry;
    const policyEnabled =
      retry &&
      retry.statusAvailable === true &&
      (retry.infinite === true || Number(retry.maxRetries) > 0);
    if (!policyEnabled) {
      if (chip) chip.remove();
      return;
    }

    const bars = Array.from(document.querySelectorAll(
      '[data-cas-status-inside-composer="true"][data-cas-status-owner="r94-inline-safe"]'
    ));
    const inline = bars.length === 1 && bars[0] instanceof Element;
    if (!chip) {
      chip = document.createElement('span');
      chip.id = RETRY_ID;
      chip.setAttribute('aria-label', 'Transfer upstream retry');
      chip.style.cssText =
        'display:inline-flex;align-items:center;padding:2px 7px;border:1px solid rgba(128,128,128,.32);' +
        'border-radius:999px;background:rgba(128,128,128,.10);color:inherit;' +
        'font:600 9px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;' +
        'white-space:nowrap;pointer-events:none;z-index:2147483646;';
    }
    chip.textContent =
      transferRetryLabel(retry) +
      (retry.active && retry.activeCount > 1 ? ' · active ' + retry.activeCount : '') +
      (retry.active && retry.delayMs ? ' · wait ' + retry.delayMs + 'ms' : '');
    chip.style.borderColor = retry.active ? 'rgba(230,167,0,.62)' : 'rgba(128,128,128,.32)';
    chip.style.background = retry.active ? 'rgba(90,67,0,.88)' : 'rgba(128,128,128,.10)';
    chip.style.color = retry.active ? '#ffe08a' : 'inherit';
    chip.style.fontWeight = retry.active ? '700' : '600';
    chip.title = retry.active
      ? 'Transfer is retrying a connect-stage upstream failure. Codex native retry budget remains unchanged.'
      : 'Transfer connect-stage retry policy is armed and waiting for a qualifying failure.';

    if (inline) {
      chip.style.position = 'static';
      chip.style.marginLeft = '8px';
      if (chip.parentElement !== bars[0]) bars[0].appendChild(chip);
    } else {
      chip.style.position = 'fixed';
      chip.style.right = '18px';
      chip.style.bottom = '72px';
      chip.style.marginLeft = '0';
      if (chip.parentElement !== document.body && document.body) document.body.appendChild(chip);
    }
  }

  async function pollTransferRetryStatus() {
    if (!RETRY_STATUS_URL) return;
    let nextDelay = 1500;
    try {
      const response = await window.fetch(RETRY_STATUS_URL, { cache: 'no-store' });
      if (!response.ok) throw new Error('retry status http ' + response.status);
      const value = await response.json();
      const retry = state.retry;
      retry.statusAvailable = true;
      retry.active = value && value.active === true;
      retry.activeCount = Number(value && value.activeCount) || 0;
      retry.attempt = Number(value && value.attempt) || 0;
      retry.maxRetries = Number(value && value.maxRetries) || 0;
      retry.infinite = value && value.infinite === true;
      retry.elapsedMs = Number(value && value.elapsedMs) || 0;
      retry.maxDurationMs = Number(value && value.maxDurationMs) || 0;
      retry.delayMs = Number(value && value.delayMs) || 0;
      retry.reason = String((value && value.reason) || '');
      nextDelay = retry.active ? 200 : ((retry.maxRetries > 0 || retry.infinite) ? 700 : 2000);
      renderTransferRetry();
    } catch {
      state.retry.statusAvailable = false;
      state.retry.active = false;
      renderTransferRetry();
      nextDelay = 2000;
    } finally {
      state.retryTimer = setTimeout(pollTransferRetryStatus, nextDelay);
    }
  }

  function refreshUi() {
    ensureStyle();
    readModelLabel();
    const bar = ensureStatusBar();
    if (bar) bar.innerHTML = statusHtml();
    renderTransferRetry();
    renderMirror();
    sampleHistory(false);
    renderAnalytics();
  }

  function poll() {
    try { readNativeUsage(); } catch {}
    try { refreshUi(); } catch {}
    state.pollTimer = setTimeout(poll, 1500);
  }

  function cleanup() {
    try { state.observer && state.observer.disconnect(); } catch {}
    if (state.timer) clearTimeout(state.timer);
    if (state.pollTimer) clearTimeout(state.pollTimer);
    if (state.sampleTimer) clearTimeout(state.sampleTimer);
    if (state.retryTimer) clearTimeout(state.retryTimer);
    const retryChip = document.getElementById(RETRY_ID);
    if (retryChip) retryChip.remove();
    document.querySelectorAll('[' + BADGE_ATTR + ']').forEach(function(node) { node.remove(); });
    document.querySelectorAll('[' + HOST_ATTR + ']').forEach(function(node) {
      node.removeAttribute(HOST_ATTR);
      node.removeAttribute(FIRST_SEEN_ATTR);
    });
    for (const id of [STATUS_ID, MIRROR_ID, ANALYTICS_ID, STYLE_ID]) {
      const node = document.getElementById(id);
      if (node) node.remove();
    }
  }

  state.refresh = refreshUi;
  state.cleanup = cleanup;
  window[ROOT_KEY] = state;
  ensureStyle();
  installFetchObserver();
  installOutputObserver();
  ensureAnalytics();
  if (RETRY_STATUS_URL) {
    state.retryTimer = setTimeout(pollTransferRetryStatus, 50);
  }
  poll();
  document.addEventListener('click', function(event) {
    const panel = document.getElementById(ANALYTICS_ID);
    if (!panel || panel.hidden) return;
    if (panel.contains(event.target)) return;
    const bar = document.getElementById(STATUS_ID);
    const mirror = document.getElementById(MIRROR_ID);
    if ((bar && bar.contains(event.target)) || (mirror && mirror.contains(event.target))) return;
    panel.hidden = true;
  }, true);
  return { ok: true, version: VERSION, reused: false };
})()
`;
}
'@

try {
    # --- Temporary r74 visible identity ---
    $Tauri = $Original[$TauriPath]
    $Tauri = Replace-Required $Tauri '"version": "2.4.5+73"' '"version": "2.4.5+74"' 'Tauri version'
    $Tauri = Replace-Required $Tauri 'Codex App Transfer — Sub2API Grok Compat r73 — v2.4.5+73' 'Codex App Transfer — Sub2API Grok Compat r74 — v2.4.5+74' 'Windows title'

    $AppLayout = $Original[$AppLayoutPath].Replace('Sub2API Grok Compat r73 — v2.4.5+73', 'Sub2API Grok Compat r74 — v2.4.5+74')
    $TopTab = $Original[$TopTabPath].Replace('Sub2API Grok Compat r73 · v2.4.5+73', 'Sub2API Grok Compat r74 · v2.4.5+74')

    $Builder = $Original[$BaseBuilderPath]
    $Builder = $Builder.Replace('[r73]', '[r74]').Replace('R73_LOCAL_BUILD_PASS', 'R74_LOCAL_BUILD_PASS').Replace('R73_DEPLOY_PASS', 'R74_DEPLOY_PASS')
    $Builder = $Builder.Replace('Sub2API Grok Compat r73 / v2.4.5+73', 'Sub2API Grok Compat r74 / v2.4.5+74')

    $VisibleIdentity = 'Sub2API Grok Compat r74 / v2.4.5+74'
    if (-not [string]::IsNullOrWhiteSpace($VisibleRevisionOverride)) {
        $Tauri = [regex]::Replace(
            $Tauri,
            '"version"\s*:\s*"2\.4\.5\+\d+(?:\.\d+)?"',
            ('"version": "' + $VisibleVersionOverride + '"')
        )
        $Tauri = [regex]::Replace(
            $Tauri,
            'Codex App Transfer — Sub2API Grok Compat r\d+(?:\.\d+)? — v2\.4\.5\+\d+(?:\.\d+)?',
            ('Codex App Transfer — Sub2API Grok Compat ' + $VisibleRevisionOverride + ' — v' + $VisibleVersionOverride)
        )
        $AppLayout = [regex]::Replace(
            $AppLayout,
            'Sub2API Grok Compat r\d+(?:\.\d+)? — v2\.4\.5\+\d+(?:\.\d+)?',
            ('Sub2API Grok Compat ' + $VisibleRevisionOverride + ' — v' + $VisibleVersionOverride)
        )
        $TopTab = [regex]::Replace(
            $TopTab,
            'Sub2API Grok Compat r\d+(?:\.\d+)? · v2\.4\.5\+\d+(?:\.\d+)?',
            ('Sub2API Grok Compat ' + $VisibleRevisionOverride + ' · v' + $VisibleVersionOverride)
        )
        $Builder = [regex]::Replace(
            $Builder,
            'Sub2API Grok Compat r\d+(?:\.\d+)? / v2\.4\.5\+\d+(?:\.\d+)?',
            ('Sub2API Grok Compat ' + $VisibleRevisionOverride + ' / v' + $VisibleVersionOverride)
        )
        $VisibleIdentity = 'Sub2API Grok Compat ' + $VisibleRevisionOverride + ' / v' + $VisibleVersionOverride

        foreach ($Check in @(
            @{ Text = $Tauri; Marker = ('"version": "' + $VisibleVersionOverride + '"') },
            @{ Text = $Tauri; Marker = ('Codex App Transfer — Sub2API Grok Compat ' + $VisibleRevisionOverride + ' — v' + $VisibleVersionOverride) },
            @{ Text = $AppLayout; Marker = ('Sub2API Grok Compat ' + $VisibleRevisionOverride + ' — v' + $VisibleVersionOverride) },
            @{ Text = $TopTab; Marker = ('Sub2API Grok Compat ' + $VisibleRevisionOverride + ' · v' + $VisibleVersionOverride) },
            @{ Text = $Builder; Marker = $VisibleIdentity }
        )) {
            if (-not $Check.Text.Contains($Check.Marker)) {
                throw "visible identity override failed to materialize: $($Check.Marker)"
            }
        }
        Write-Host ("R74_VISIBLE_IDENTITY_OVERRIDE_PASS: {0}" -f $VisibleIdentity) -ForegroundColor Green
    }

    Write-Utf8NoBom $TauriPath $Tauri
    Write-Utf8NoBom $AppLayoutPath $AppLayout
    Write-Utf8NoBom $TopTabPath $TopTab
    Write-Utf8NoBom $BaseBuilderPath $Builder

    # --- Replace only the renderer telemetry runtime, keep the proven No-Lagging guard ---
    $Launcher = $Original[$LauncherPath]
    $Launcher = $Launcher.Replace('const OUTPUT_TELEMETRY_RUNTIME = "r73.1";', 'const OUTPUT_TELEMETRY_RUNTIME = "r74.0";')
    $Start = $Launcher.IndexOf('function outputTelemetryRuntimeSource')
    if ($Start -lt 0) { throw 'r74 could not locate telemetry runtime function start' }
    $End = $Launcher.IndexOf('function stubExpression(', $Start)
    if ($End -le $Start) { throw 'r74 could not locate telemetry runtime function end' }
    $Launcher = $Launcher.Substring(0, $Start) + $NewTelemetryFunction + "`r`n`r`n" + $Launcher.Substring($End)
    $Launcher = $Launcher.Replace('globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true && globalThis.__CODEX_OUTPUT_TELEMETRY_R73__ === true', 'globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true')
    $Launcher = $Launcher.Replace('global No Lagging / output telemetry marker was not set', 'global No Lagging marker was not set')
    $Launcher = $Launcher.Replace('status: "armed",', 'status: "best-effort-armed",')
    $Launcher = $Launcher.Replace('timestampMode: "per-assistant-output",', 'timestampMode: "live-output-segment + single-final-answer",')
    $Launcher = $Launcher.Replace('metricMode: "best-effort-live-stream",', 'metricMode: "responsive-mirror + composer-status + local-history",')
    foreach ($Marker in @(
        'CAS-R94-1-TRANSFER-RETRY-GENERATED-CARRY',
        '/_cas/transfer-retry-status',
        'TRANSFER RETRY ',
        "retry.infinite ? '∞'",
        'retry.maxDurationMs',
        'retryRemainingMs',
        'TRANSFER RETRY READY ',
        'statusAvailable',
        'pollTransferRetryStatus'
    )) {
        if (-not $Launcher.Contains($Marker)) {
            throw "r74 generated retry carry-forward missing: $Marker"
        }
    }
    Write-Host 'R74_TRANSFER_RETRY_GENERATED_CARRY_PASS' -ForegroundColor Green
    Write-Utf8NoBom $LauncherPath $Launcher

    Write-Host '[r74] local source finalization applied'
    node --check $LauncherPath
    if ($LASTEXITCODE -ne 0) { throw 'r74 launcher JavaScript syntax check failed' }

    if ($RunFocusedTests) {
        & $BaseBuilderPath
    }
    else {
        & $BaseBuilderPath -SkipFocusedTests
    }
    if ($LASTEXITCODE -ne 0) { throw "r74 desktop build failed with exit code $LASTEXITCODE" }

    Write-Host ''
    Write-Host 'R74_OUTPUT_UI_LOCAL_PASS'
    Write-Host ("Expected identity: {0}" -f $VisibleIdentity)
    Write-Host 'Expected B-path UI:'
    Write-Host '  - live progress/model-output blocks receive one timestamp when first emitted'
    Write-Host '  - final answer receives only one timestamp for the whole final-answer surface'
    Write-Host '  - native right Usage remains untouched; compact mirror appears when native Usage is hidden'
    Write-Host '  - persistent status bar mounts directly above the composer'
    Write-Host '  - click status bar or compact Usage mirror for Context / tok-s / cache history charts'
}
finally {
    foreach ($Path in @($LauncherPath, $TauriPath, $AppLayoutPath, $TopTabPath, $BaseBuilderPath)) {
        Write-Utf8NoBom $Path $Original[$Path]
    }
    Write-Host '[r74] restored tracked sources; worktree remains pull-friendly'
}
