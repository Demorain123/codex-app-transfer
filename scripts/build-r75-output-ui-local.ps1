param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R74Builder = Join-Path $PSScriptRoot 'build-r74-output-ui-local.ps1'
$TempBuilder = Join-Path $PSScriptRoot '.build-r75-output-ui-local.generated.ps1'

if (-not (Test-Path $R74Builder)) {
    throw "r75 requires r74 builder: $R74Builder"
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Original = [System.IO.File]::ReadAllText($R74Builder)

function Replace-BlockRequired(
    [string]$Text,
    [string]$StartMarker,
    [string]$EndMarker,
    [string]$Replacement,
    [string]$Label
) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r75 patch start marker missing: $Label" }
    $End = $Text.IndexOf($EndMarker, $Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r75 patch end marker missing: $Label" }
    return $Text.Substring(0, $Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r75 expected text missing: $Label" }
    return $Text.Replace($Old, $New)
}

# r75 is deliberately a tiny local finalizer layered on r74.  It keeps the
# existing context/cache/speed/session telemetry and only replaces the output
# timestamp segmentation/placement path that was too easy to miss in r74.
$NewSegmentation = @'
  function isSemanticOutputSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-local-conversation-final-assistant]')) return true;
    return node.matches('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"],[data-turn-key],[data-message-id]');
  }

  function directVisualChildren(parent) {
    return meaningfulDirectChildren(parent).filter(function(child) {
      if (!(child instanceof Element)) return false;
      if (child.hasAttribute(BADGE_ATTR)) return false;
      if (insideOwnUi(child) || insideComposer(child)) return false;
      return true;
    });
  }

  function unwrapSingleOutputSurface(node) {
    let current = node;
    for (let depth = 0; depth < 9; depth += 1) {
      if (!(current instanceof Element)) break;
      if (isSemanticOutputSurface(current)) return current;
      const children = directVisualChildren(current);
      if (children.length !== 1) return current;
      current = children[0];
    }
    return current instanceof Element ? current : node;
  }

  function topLevelSegments(root) {
    if (!(root instanceof Element)) return [];
    if (root.matches('[data-local-conversation-final-assistant]')) return [root];

    let container = root;
    for (let depth = 0; depth < 10; depth += 1) {
      const children = directVisualChildren(container);
      if (children.length === 1 && !isSemanticOutputSurface(container)) {
        container = children[0];
        continue;
      }
      break;
    }

    let candidates = directVisualChildren(container);
    if (candidates.length < 2) candidates = [container];
    candidates = candidates.map(unwrapSingleOutputSurface).filter(Boolean);

    const final = root.querySelector('[data-local-conversation-final-assistant]');
    if (final) {
      candidates = candidates.filter(function(candidate) {
        return candidate === final || !candidate.contains(final);
      });
      candidates.push(final);
    }

    const unique = [];
    const seen = new Set();
    for (const candidate of candidates) {
      if (!(candidate instanceof Element) || seen.has(candidate)) continue;
      if (!root.contains(candidate) && candidate !== root) continue;
      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate)) continue;
      if (normalizedText(candidate).length < 3) continue;
      seen.add(candidate);
      unique.push(candidate);
    }
    return unique;
  }

  function segmentForMutation(node, root) {
    if (!root) return null;
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideComposer(element) || insideOwnUi(element)) return null;

    const final = finalSurfaceFor(element, root);
    if (final) return final;
    const semantic = semanticProgressSurface(element, root);
    if (semantic) return semantic;

    const candidates = topLevelSegments(root);
    const containing = candidates
      .filter(function(candidate) { return candidate === element || candidate.contains(element); })
      .sort(function(a, b) {
        try { return a.getBoundingClientRect().height - b.getBoundingClientRect().height; }
        catch { return 0; }
      });
    return containing[0] || candidates[0] || root;
  }

  function structuralPath(node, stop) {
    const parts = [];
    let current = node;
    for (let depth = 0; depth < 18 && current && current !== stop; depth += 1) {
      const parent = current.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children || []).filter(function(child) {
        return !(child instanceof Element && child.hasAttribute(BADGE_ATTR));
      });
      const index = siblings.indexOf(current);
      parts.unshift(index >= 0 ? index : 0);
      current = parent;
    }
    return parts.join('.');
  }

  function segmentKey(segment, root) {
    if (!(segment instanceof Element) || !(root instanceof Element)) return '';
    const turn = root.closest('[data-turn-key]') || root;
    const rootId =
      root.getAttribute('data-content-search-assistant-turn-key') ||
      turn.getAttribute('data-turn-key') ||
      root.getAttribute('data-message-id') ||
      structuralPath(root, document.body);
    const semanticId =
      segment.getAttribute('data-turn-key') ||
      segment.getAttribute('data-message-id') ||
      segment.getAttribute('data-testid') ||
      segment.getAttribute('role') || '';
    const kind = segment.matches('[data-local-conversation-final-assistant]') ? 'final' : 'segment';
    return simpleHash(String(location.pathname || '') + '|' + String(location.hash || '') + '|' + rootId + '|' + structuralPath(segment, root) + '|' + semanticId + '|' + kind);
  }
'@

$NewStamp = @'
  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    const existing = segment.querySelector(':scope > [' + BADGE_ATTR + ']');
    if (existing) return;

    const cache = readSeenCache();
    const remembered = Number(cache[key]);
    const attrTime = Number(segment.getAttribute(FIRST_SEEN_ATTR));
    const when = Number.isFinite(attrTime) && attrTime > 0
      ? attrTime
      : (Number.isFinite(remembered) && remembered > 0 ? remembered : epoch);
    if (!Number.isFinite(when) || when <= 0) return;

    const badge = document.createElement('span');
    badge.setAttribute(BADGE_ATTR, 'true');
    badge.setAttribute('aria-label', 'Assistant output timestamp');
    badge.textContent = clock(when);
    badge.title = fullTime(when) + ' · ' + ((Number.isFinite(remembered) && remembered > 0) ? 'remembered local output time' : source);
    // r74 used an absolute top-right chip.  On current Codex many progress
    // surfaces live inside clipped/virtualized containers, so the chip could
    // exist but be invisible.  r75 keeps it inside normal flow as a tiny
    // right-aligned rail; this costs ~10px but survives overflow clipping.
    badge.style.cssText = 'position:relative;top:auto;right:auto;z-index:2;display:flex;width:100%;box-sizing:border-box;align-items:center;justify-content:flex-end;margin:0 0 1px 0;padding:0 2px;border:0;background:transparent;box-shadow:none;backdrop-filter:none;-webkit-backdrop-filter:none;color:color-mix(in srgb,CanvasText 52%,transparent);font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.72;';
    segment.insertBefore(badge, segment.firstChild);
    segment.setAttribute(HOST_ATTR, 'true');
    segment.setAttribute(FIRST_SEEN_ATTR, String(when));
    rememberSegmentTime(key, when);
  }
'@

$NewObserver = @'
  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    document.querySelectorAll(ASSISTANT_ROOT_SELECTOR).forEach(function(node) {
      const root = assistantRootFor(node) || (node instanceof Element ? node : null);
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root)) return;
      seen.add(root);
      roots.push(root);
    });
    return roots;
  }

  function baselineExistingDom() {
    const cache = readSeenCache();
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        const key = segmentKey(segment, root);
        if (!key) return;
        const native = nativeTime(segment) || nativeTime(root);
        const remembered = Number(cache[key]);
        if (native) {
          stampSegment(segment, root, native.epoch, native.source);
        } else if (Number.isFinite(remembered) && remembered > 0) {
          stampSegment(segment, root, remembered, 'remembered local output time');
        } else {
          state.baselineKeys.add(key);
        }
      });
    });
  }

  function stampMutationNode(node) {
    const root = assistantRootFor(node);
    if (!root) return;
    const segment = segmentForMutation(node, root);
    if (!segment || !isVisible(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    const native = nativeTime(segment) || nativeTime(root);
    const cache = readSeenCache();
    const remembered = Number(cache[key]);
    state.baselineKeys.delete(key);
    stampSegment(
      segment,
      root,
      native ? native.epoch : ((Number.isFinite(remembered) && remembered > 0) ? remembered : Date.now()),
      native ? native.source : ((Number.isFinite(remembered) && remembered > 0) ? 'remembered local output time' : 'first observed output change locally')
    );
  }

  function sweepOutputSegments(allowFresh) {
    const cache = readSeenCache();
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        if (segment.querySelector(':scope > [' + BADGE_ATTR + ']')) return;
        const key = segmentKey(segment, root);
        if (!key) return;
        const native = nativeTime(segment) || nativeTime(root);
        const remembered = Number(cache[key]);
        if (native) {
          stampSegment(segment, root, native.epoch, native.source);
          return;
        }
        if (Number.isFinite(remembered) && remembered > 0) {
          stampSegment(segment, root, remembered, 'remembered local output time');
          return;
        }
        if (allowFresh && !state.baselineKeys.has(key)) {
          stampSegment(segment, root, Date.now(), 'first observed output segment locally');
        }
      });
    });
  }

  function scheduleOutputSweep() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(function() {
      state.timer = null;
      try { sweepOutputSegments(true); } catch {}
    }, 90);
  }

  function installOutputObserver() {
    if (!document.body) { setTimeout(installOutputObserver, 80); return; }
    baselineExistingDom();
    const observer = new MutationObserver(function(records) {
      for (const record of records) {
        if (record.type === 'characterData') {
          stampMutationNode(record.target);
          continue;
        }
        for (const added of record.addedNodes || []) {
          stampMutationNode(added);
          if (added instanceof Element) {
            const textNodes = added.querySelectorAll('p,li,pre,[role="status"],[data-testid],[data-turn-key],[data-message-id],[data-local-conversation-final-assistant]');
            let count = 0;
            for (const probe of textNodes) {
              if (count++ >= 48) break;
              stampMutationNode(probe);
            }
          }
        }
      }
      scheduleOutputSweep();
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    state.observer = observer;
    setTimeout(function() { try { sweepOutputSegments(false); } catch {} }, 120);
  }
'@

try {
    # Build r75 from the already-reviewed r74 local builder without copying its
    # ~900 lines into another tracked file.  The generated builder stays in the
    # same scripts directory so $PSScriptRoot semantics remain identical.
    $Patched = $Original.Replace('r74', 'r75').Replace('R74', 'R75').Replace('+74', '+75')

    $Patched = Replace-BlockRequired \
        $Patched \
        '  function structuralProgressSurface(node, root) {' \
        '  function stampSegment(segment, root, epoch, source) {' \
        $NewSegmentation \
        'segmentation + stable structural key'

    $Patched = Replace-BlockRequired \
        $Patched \
        '  function stampSegment(segment, root, epoch, source) {' \
        '  function baselineExistingDom() {' \
        $NewStamp \
        'visible in-flow timestamp rail'

    $Patched = Replace-BlockRequired \
        $Patched \
        '  function baselineExistingDom() {' \
        '  function numberAt(obj, paths) {' \
        $NewObserver \
        'observer + periodic segment sweep'

    $OldPoll = @'
  function poll() {
    try { readNativeUsage(); } catch {}
    try { refreshUi(); } catch {}
    state.pollTimer = setTimeout(poll, 1500);
  }
'@
    $NewPoll = @'
  function poll() {
    try { readNativeUsage(); } catch {}
    try { sweepOutputSegments(true); } catch {}
    try { refreshUi(); } catch {}
    state.pollTimer = setTimeout(poll, 1500);
  }
'@
    $Patched = Replace-Required $Patched $OldPoll $NewPoll 'poll fallback timestamp sweep'

    foreach ($Marker in @(
        "const VERSION = 'r75.0';",
        'function topLevelSegments(root) {',
        'first observed output change locally',
        'sweepOutputSegments(true)',
        'R75_OUTPUT_UI_LOCAL_PASS'
    )) {
        if (-not $Patched.Contains($Marker)) { throw "r75 generated builder verification failed: $Marker" }
    }

    [System.IO.File]::WriteAllText($TempBuilder, $Patched, $Utf8NoBom)

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r75 generated builder failed with exit code $LASTEXITCODE" }

    Write-Host 'R75_TIMESTAMP_V3_PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
}
