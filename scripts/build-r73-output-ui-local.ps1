param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $RepoRoot 'src-tauri\resources\codex_no_micro_launcher.mjs'
$Builder = Join-Path $PSScriptRoot 'build-r73-local.ps1'

if (-not (Test-Path $Launcher)) { throw "r73 launcher not found: $Launcher" }
if (-not (Test-Path $Builder)) { throw "r73 builder not found: $Builder" }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Original = [System.IO.File]::ReadAllText($Launcher)
$Patched = $Original

function Replace-Exact([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) {
        throw "r73 local finalizer could not find expected block: $Label"
    }
    return $Text.Replace($Old, $New)
}

# r73.2: the Node startup inspector can only prove the No-Lagging guard before
# Electron's main module resumes. Renderer telemetry is armed later when Electron
# is required, so treating that later marker as a synchronous startup gate creates
# a false-negative race and can abort an otherwise healthy Codex launch.
$Patched = Replace-Exact $Patched 'const OUTPUT_TELEMETRY_RUNTIME = "r73.1";' 'const OUTPUT_TELEMETRY_RUNTIME = "r73.2";' 'outer telemetry runtime version'
$Patched = Replace-Exact $Patched "const VERSION = 'r73.1';" "const VERSION = 'r73.2';" 'renderer telemetry runtime version'
$Patched = Replace-Exact $Patched 'globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true && globalThis.__CODEX_OUTPUT_TELEMETRY_R73__ === true' 'globalThis.__CODEX_MICRO_DISABLED_LOCAL__ === true' 'startup marker race'
$Patched = $Patched.Replace('global No Lagging / output telemetry marker was not set', 'global No Lagging marker was not set')
$Patched = $Patched.Replace('timestampMode: "per-assistant-output",', 'timestampMode: "per-assistant-output-block",')
$Patched = $Patched.Replace('status: "armed",', 'status: "best-effort-armed",')

# Codex-Monitor proved that assistant turn wrappers are comparatively stable, but
# the user requirement is stricter: timestamp each visible model-output block, not
# merely one badge for the whole assistant turn. Keep the stable wrappers as roots
# and derive only shallow, visible top-level blocks. Never split paragraphs/lists
# into every child node; that would create noisy per-bullet timestamps.
$SegmentHelpers = @'
  function isVisibleElement(node) {
    if (!(node instanceof Element)) return false;
    try {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
      if (!node.getClientRects().length) return false;
    } catch {}
    return true;
  }

  function normalizedVisibleText(node) {
    return String(node && (node.innerText || node.textContent) || '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function isOutputBlockCandidate(node) {
    if (!isVisibleElement(node)) return false;
    if (node.id === HUD_ID || node.hasAttribute(BADGE_ATTR) || node.closest('#' + HUD_ID)) return false;
    if (/^(SCRIPT|STYLE|NOSCRIPT|INPUT|TEXTAREA|SELECT|OPTION)$/i.test(node.tagName || '')) return false;
    const text = normalizedVisibleText(node);
    const semantic = node.matches?.('[data-turn-key],[data-message-id],[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"]') ||
      node.querySelector?.('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"]');
    if (semantic) return true;
    if (text.length < 3) return false;
    const buttons = node.querySelectorAll?.('button,[role="button"]')?.length || 0;
    if (buttons > 0 && text.length < 28) return false;
    return true;
  }

  function shallowOutputBlocks(root) {
    if (!(root instanceof Element)) return [];
    const queue = [{ node: root, depth: 0 }];
    while (queue.length) {
      const current = queue.shift();
      if (!current || current.depth > 3) continue;
      const children = Array.from(current.node.children || []).filter(isOutputBlockCandidate);
      const structural = children.filter(function(child) {
        return !/^(P|SPAN|A|LI|UL|OL|CODE|PRE|TABLE|THEAD|TBODY|TR|TD|TH|SVG)$/i.test(child.tagName || '');
      });
      // The shallowest container with multiple meaningful structural children is
      // the closest available approximation of Codex's visible output/event blocks.
      // This catches progress cards, Created/Closed agent rows, tool/status blocks,
      // and final-answer blocks without timestamping every bullet or markdown line.
      if (structural.length >= 2) return structural;
      if (current.depth < 3) {
        for (const child of structural) queue.push({ node: child, depth: current.depth + 1 });
      }
    }
    return [root];
  }

  function assistantOutputSegments() {
    const seen = new Set();
    const result = [];
    for (const root of assistantNodes()) {
      for (const segment of shallowOutputBlocks(root)) {
        if (!(segment instanceof Element) || seen.has(segment)) continue;
        seen.add(segment);
        result.push(segment);
      }
    }
    return result;
  }

'@

if (-not $Patched.Contains('function assistantOutputSegments()')) {
    $Needle = '  function nativeTime(node) {'
    if (-not $Patched.Contains($Needle)) { throw 'r73 local finalizer could not find nativeTime insertion point' }
    $Patched = $Patched.Replace($Needle, $SegmentHelpers + $Needle)
}
$Patched = Replace-Exact $Patched '      assistantNodes().forEach(stamp);' '      assistantOutputSegments().forEach(stamp);' 'per-output-block scan'

# Preserve a live block's locally observed time across React remounts within the
# same Codex renderer. The DOM attribute remains authoritative for the current
# node; this small localStorage cache only prevents an immediate remount from
# making an already-seen block look newly emitted.
$CacheHelpers = @'
  const TIMESTAMP_CACHE_KEY = 'cas-output-timestamps-r73';
  const TIMESTAMP_CACHE_LIMIT = 600;

  function simpleHash(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }

  function timestampCacheId(node) {
    const text = normalizedVisibleText(node).slice(0, 480);
    if (!text) return '';
    return simpleHash(String(location.pathname || '') + '|' + String(location.hash || '') + '|' + text);
  }

  function readTimestampCache() {
    try {
      const value = JSON.parse(localStorage.getItem(TIMESTAMP_CACHE_KEY) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch { return {}; }
  }

  function cachedObservedTime(node) {
    const key = timestampCacheId(node);
    if (!key) return null;
    const value = Number(readTimestampCache()[key]);
    return Number.isFinite(value) && value > 0 ? value : null;
  }

  function rememberObservedTime(node, epoch) {
    const key = timestampCacheId(node);
    if (!key || !Number.isFinite(epoch) || epoch <= 0) return;
    try {
      const cache = readTimestampCache();
      cache[key] = epoch;
      const entries = Object.entries(cache)
        .map(function(entry) { return [entry[0], Number(entry[1])]; })
        .filter(function(entry) { return Number.isFinite(entry[1]); })
        .sort(function(a, b) { return b[1] - a[1]; })
        .slice(0, TIMESTAMP_CACHE_LIMIT);
      localStorage.setItem(TIMESTAMP_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
    } catch {}
  }

'@

if (-not $Patched.Contains("const TIMESTAMP_CACHE_KEY = 'cas-output-timestamps-r73';")) {
    $Needle = '  function stamp(node) {'
    if (-not $Patched.Contains($Needle)) { throw 'r73 local finalizer could not find stamp insertion point' }
    $Patched = $Patched.Replace($Needle, $CacheHelpers + $Needle)
}

$OldFirstSeen = @'
    let firstSeen = Number(node.getAttribute(FIRST_SEEN_ATTR));
    if (!Number.isFinite(firstSeen) || firstSeen <= 0) {
      firstSeen = Date.now();
      node.setAttribute(FIRST_SEEN_ATTR, String(firstSeen));
    }
'@
$NewFirstSeen = @'
    let firstSeen = Number(node.getAttribute(FIRST_SEEN_ATTR));
    if (!Number.isFinite(firstSeen) || firstSeen <= 0) {
      firstSeen = cachedObservedTime(node) || Date.now();
      node.setAttribute(FIRST_SEEN_ATTR, String(firstSeen));
      rememberObservedTime(node, firstSeen);
    }
'@
$Patched = Replace-Exact $Patched $OldFirstSeen $NewFirstSeen 'timestamp remount cache'

if ($Patched -eq $Original) { throw 'r73 local finalizer made no changes' }
if ($Patched.Contains('__CODEX_OUTPUT_TELEMETRY_R73__ === true')) { throw 'r73 marker race is still present after patch' }
if (-not $Patched.Contains('assistantOutputSegments().forEach(stamp);')) { throw 'r73 per-output-block scanner was not installed' }

Write-Host '[r73.2] applying temporary local source finalization'
[System.IO.File]::WriteAllText($Launcher, $Patched, $Utf8NoBom)

try {
    node --check $Launcher
    if ($LASTEXITCODE -ne 0) { throw 'r73.2 launcher JavaScript syntax check failed' }

    if ($RunFocusedTests) {
        & $Builder
    }
    else {
        & $Builder -SkipFocusedTests
    }

    Write-Host ''
    Write-Host 'R73_OUTPUT_UI_LOCAL_PASS'
    Write-Host 'Expected Transfer identity: Sub2API Grok Compat r73 / v2.4.5+73'
    Write-Host 'Expected Codex B-path UI: timestamp badge on each visible assistant/model output block; ctx/tok/s HUD only when real token telemetry is observable.'
}
finally {
    # Keep the Git worktree clean so the next git pull is never blocked by this
    # local validation patch. The compiled/deployed executable already contains
    # the finalized r73.2 launcher because include_str! is resolved during build.
    [System.IO.File]::WriteAllText($Launcher, $Original, $Utf8NoBom)
    Write-Host '[r73.2] restored tracked launcher source; worktree can remain pull-friendly'
}
