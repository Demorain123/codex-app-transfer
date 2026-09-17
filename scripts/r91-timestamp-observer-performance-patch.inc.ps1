# R91_TIMESTAMP_OBSERVER_PERFORMANCE_PATCH
# Executes inside the generated r86/r91 builder scope where $ObserverBody is
# the final r90-derived timestamp observer that the r78 generation layer uses.

function Replace-R91PerfBlock([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $TextN = $Text.Replace([char]13 + [char]10,[char]10).Replace([char]13,[char]10)
    $StartN = $Start.Replace([char]13 + [char]10,[char]10).Replace([char]13,[char]10)
    $ReplacementN = $Replacement.Replace([char]13 + [char]10,[char]10).Replace([char]13,[char]10)
    $StartIndex = $TextN.IndexOf($StartN)
    if ($StartIndex -lt 0) { throw "r91 perf block start missing: $Label" }
    if ([string]::IsNullOrEmpty($End)) {
        return $TextN.Substring(0,$StartIndex) + $ReplacementN
    }
    $EndN = $End.Replace([char]13 + [char]10,[char]10).Replace([char]13,[char]10)
    $EndIndex = $TextN.IndexOf($EndN,$StartIndex + $StartN.Length)
    if ($EndIndex -le $StartIndex) { throw "r91 perf block end missing: $Label" }
    return $TextN.Substring(0,$StartIndex) + $ReplacementN + [char]10 + [char]10 + $TextN.Substring($EndIndex)
}

$R91PerfHelpers = @'
  function ensureTimestampPerfState() {
    if (!state.timestampPerf || typeof state.timestampPerf !== 'object') {
      state.timestampPerf = {
        latestTurnCache: new WeakMap(),
      };
    }
    return state.timestampPerf;
  }
'@
$ObserverBody = $ObserverBody.Replace(
    '  function composerRectForNode(node) {',
    $R91PerfHelpers + [char]10 + [char]10 + '  function composerRectForNode(node) {'
)
if (-not $ObserverBody.Contains('function ensureTimestampPerfState() {')) {
    throw 'r91 observer perf helper insertion failed'
}

$R91LiveTailText = @'
  function liveTailTextFor(node) {
    const pane = paneForNode(node);
    const scope = pane instanceof Element ? pane : document;
    const parts = [];
    const latest = latestConversationTurnFor(node);
    if (latest instanceof Element) parts.push(normalizedText(latest).slice(-1800));

    const nodes = scope.querySelectorAll('[role="status"],[aria-busy="true"],[data-loading="true"],[data-state="loading"],[data-state="pending"],[data-state="running"]');
    const start = Math.max(0, nodes.length - 16);
    for (let index = start; index < nodes.length; index += 1) {
      const candidate = nodes[index];
      if (!(candidate instanceof Element) || !isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate)) continue;
      parts.push(normalizedText(candidate).slice(-320));
    }
    return parts.join(' ').slice(-2200).toLowerCase();
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function liveTailTextFor(node) {' '  function turnLooksUserAuthored(turn) {' $R91LiveTailText 'bounded live-tail text'

$R91ActiveGeneration = @'
  function activeGenerationUiPresentFor(node) {
    const pane = paneForNode(node);
    const composer = composerForPane(pane) || findComposerRoot();
    const scope = composer instanceof Element
      ? (composer.parentElement instanceof Element ? composer.parentElement : composer)
      : null;
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
    if (/(^|\b)(thinking|working|generating|running|pausing|waiting|step\s*\d+\s*\/\s*\d+)(\b|$)|思考|处理中|正在生成|正在运行|等待中|暂停片刻/i.test(tailText)) return true;
    return false;
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function activeGenerationUiPresentFor(node) {' '  function latestConversationTurnFor(node) {' $R91ActiveGeneration 'composer-scoped generation detection'

$R91LatestTurn = @'
  function latestConversationTurnFor(node) {
    const pane = paneForNode(node);
    const scope = pane instanceof Element ? pane : document;
    const perf = ensureTimestampPerfState();
    const now = performance.now();
    const cached = perf.latestTurnCache.get(scope);
    if (cached && now - cached.at < 300 && cached.turn instanceof Element && cached.turn.isConnected) {
      return cached.turn;
    }

    function lastVisible(selector) {
      const nodes = scope.querySelectorAll(selector);
      for (let index = nodes.length - 1; index >= 0; index -= 1) {
        const candidate = nodes[index];
        if (!(candidate instanceof Element) || insideComposer(candidate) || insideOwnUi(candidate) || turnLooksUserAuthored(candidate) || !isVisible(candidate)) continue;
        return candidate;
      }
      return null;
    }

    let latest = lastVisible('[data-chatgpt-conversation-turn="true"]');
    if (!latest) latest = lastVisible('[data-turn-key]');
    if (!latest) {
      const composer = composerForPane(pane) || findComposerRoot();
      let cr = null;
      try { cr = composer instanceof Element ? composer.getBoundingClientRect() : null; } catch { cr = null; }
      if (cr) {
        const candidates = scope.querySelectorAll('[data-message-author-role="assistant"],[role="status"],[data-testid],p,pre');
        for (let index = candidates.length - 1; index >= 0; index -= 1) {
          const candidate = candidates[index];
          if (!(candidate instanceof Element) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate) || !isVisible(candidate)) continue;
          let rect;
          try { rect = candidate.getBoundingClientRect(); } catch { continue; }
          if (rect.bottom <= cr.top + 90 && rect.bottom >= cr.top - Math.max(520, Math.min(980, innerHeight * 0.72))) {
            latest = candidate;
            break;
          }
        }
      }
    }

    if (latest instanceof Element) perf.latestTurnCache.set(scope, { turn: latest, at: now });
    return latest instanceof Element ? latest : null;
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function latestConversationTurnFor(node) {' '  function isLatestTurnSurface(node) {' $R91LatestTurn 'cached latest-turn lookup'

$R91SweepLiveTail = @'
  function sweepLiveTailSegments() {
    for (const composer of findComposerRoots()) {
      if (!activeGenerationUiPresentFor(composer)) continue;
      const latest = latestConversationTurnFor(composer);
      if (!(latest instanceof Element)) continue;
      const root = liveTailRootFor(latest) || latest;
      if (root instanceof Element) stampLiveRoot(root);
    }
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function sweepLiveTailSegments() {' '  function sweepOutputSegments(allowFresh) {' $R91SweepLiveTail 'bounded live-tail sweep'

$R91ScheduleSweep = @'
  function scheduleOutputSweep() {
    if (state.timer) return;
    state.timer = setTimeout(function() {
      state.timer = null;
      try { sweepLiveTailSegments(); } catch {}
    }, 180);
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function scheduleOutputSweep() {' '  function installOutputObserver() {' $R91ScheduleSweep 'throttled output sweep'

$R91InstallObserver = @'
  function installOutputObserver() {
    if (!document.body) { setTimeout(installOutputObserver, 120); return; }
    baselineExistingDom();
    const observer = new MutationObserver(function(records) {
      let relevant = false;
      for (const record of records) {
        if (record.type === 'characterData') {
          const parent = record.target && record.target.parentElement;
          if (parent instanceof Element && !insideComposer(parent) && !insideOwnUi(parent)) {
            stampMutationNode(record.target);
            relevant = true;
          }
          continue;
        }
        for (const added of record.addedNodes || []) {
          const element = added instanceof Element ? added : added && added.parentElement;
          if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element)) continue;
          stampMutationNode(added);
          relevant = true;
          if (added instanceof Element) {
            const probes = added.querySelectorAll('[role="status"],[data-testid],[data-local-conversation-final-assistant],[data-message-author-role="assistant"],[data-turn-key]');
            let count = 0;
            for (const probe of probes) {
              if (count++ >= 24) break;
              stampMutationNode(probe);
            }
          }
        }
      }
      if (relevant) scheduleOutputSweep();
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    state.observer = observer;

    const reconcileExact = function() {
      try { sweepOutputSegments(false); } catch {}
    };
    if (typeof requestIdleCallback === 'function') requestIdleCallback(reconcileExact, { timeout: 800 });
    else setTimeout(reconcileExact, 350);
  }
'@
$ObserverBody = Replace-R91PerfBlock $ObserverBody '  function installOutputObserver() {' '' $R91InstallObserver 'bounded mutation observer'

foreach ($Marker in @(
    'function ensureTimestampPerfState() {',
    'latestTurnCache: new WeakMap()',
    'const start = Math.max(0, nodes.length - 16);',
    'composer.parentElement instanceof Element',
    'now - cached.at < 300',
    'if (state.timer) return;',
    'count++ >= 24',
    "requestIdleCallback(reconcileExact, { timeout: 800 })"
)) {
    if (-not $ObserverBody.Contains($Marker)) {
        throw "r91 observer performance invariant missing: $Marker"
    }
}

foreach ($Forbidden in @(
    "scope.querySelectorAll('[role=\"status\"],[data-testid],p,span,div')",
    'try { sweepOutputSegments(false); } catch {}' + [char]10 + '    }, 90);'
)) {
    if ($ObserverBody.Contains($Forbidden)) {
        throw "r91 observer performance retained unbounded hot-path marker: $Forbidden"
    }
}

Write-Host 'R91_BOUNDED_TIMESTAMP_OBSERVER_SOURCE_PASS' -ForegroundColor Green
