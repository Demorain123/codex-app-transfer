param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R85Builder = Join-Path $PSScriptRoot 'build-r85-local.ps1'
$TempR86Builder = Join-Path $PSScriptRoot '.build-r86-from-r85.generated.ps1'
if (-not (Test-Path -LiteralPath $R85Builder)) { throw "r86 requires r85 builder: $R85Builder" }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR85 = [System.IO.File]::ReadAllText($R85Builder)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r86 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
function Insert-AfterRequired([string]$Text,[string]$Needle,[string]$Insertion,[string]$Label) {
    $Index = $Text.IndexOf($Needle)
    if ($Index -lt 0) { throw "r86 insertion point missing: $Label" }
    $End = $Index + $Needle.Length
    return $Text.Substring(0,$End) + $Insertion + $Text.Substring($End)
}
function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens=$null; $Errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r86 PowerShell parse failed: $Label :: $Summary"
    }
}

# r85 fixed prose grouping, but the screenshot exposed four correctness bugs:
# 1) a broad conversation root can include a user bubble, so user content was stamped;
# 2) nativeTime(segment) searches descendants and could borrow another output's sent-time;
# 3) the r74 localStorage cache survives segmentation changes and can replay stale times;
# 4) Date.now() fallback was allowed from periodic sweeps/remounts, so historical DOM
#    could receive a current time after React virtualization/reload.
# r86 keeps r85 grouping but makes timestamp ownership strict and live-only.
$R86BuilderText = $OriginalR85.Replace('r85','r86').Replace('R85','R86').Replace('+85','+86')

# ---------------------------------------------------------------------------
# Strengthen the r85 segmentation body without changing provider/telemetry code.
# ---------------------------------------------------------------------------
$SemanticNeedle = @'
  function isSemanticOutputSurface(node) {
    return isStrongSemanticOutputSurface(node);
  }
'@
$SemanticExtra = @'

  function isUserAuthoredSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-message-author-role="user"],[data-message-author="user"]')) return true;
    const directUser = node.closest('[data-message-author-role="user"],[data-message-author="user"]');
    if (directUser) return true;
    const userDesc = node.querySelector('[data-message-author-role="user"],[data-message-author="user"]');
    const assistantDesc = node.querySelector('[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[data-content-search-assistant-turn-key]');
    return !!userDesc && !assistantDesc;
  }

  function isNativeMetadataSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-assistant-message-sent-time],time[datetime]')) return true;
    return false;
  }
'@
$R86BuilderText = Insert-AfterRequired $R86BuilderText $SemanticNeedle $SemanticExtra 'user/native timestamp ownership helpers'

$OldCollectGuard = "    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node)) return [];"
$NewCollectGuard = "    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node) || isUserAuthoredSurface(node) || isNativeMetadataSurface(node)) return [];"
$R86BuilderText = Replace-Required $R86BuilderText $OldCollectGuard $NewCollectGuard 'exclude user/native metadata from output segmentation'

$OldUniqueGuard = "      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate)) continue;"
$NewUniqueGuard = "      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate) || isNativeMetadataSurface(candidate)) continue;"
$R86BuilderText = Replace-Required $R86BuilderText $OldUniqueGuard $NewUniqueGuard 'exclude user/native metadata from timestamp candidates'

$OldMutationGuard = "    if (!element || insideComposer(element) || insideOwnUi(element)) return null;"
$NewMutationGuard = "    if (!element || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;"
$R86BuilderText = Replace-Required $R86BuilderText $OldMutationGuard $NewMutationGuard 'exclude user mutations from timestamps'

# Keep one semantic action row plus its expanded prose/detail as one event.
$BeforeVerticalSplit = @'
    // Horizontal icon/label/action rows stay atomic.
    if (verticalRowCount(children) < 2) return [node];
'@
$SemanticGrouping = @'
    // One tool/agent/status row plus its expanded prose belongs to one visible
    // event. This prevents "Messaged an agent" and its detail text from getting
    // two unrelated timestamps while still keeping consecutive events separate.
    const semanticChildren = children.filter(function(child) { return isStrongSemanticOutputSurface(child); });
    if (semanticChildren.length === 1) {
      const rest = children.filter(function(child) { return child !== semanticChildren[0]; });
      if (rest.length && rest.every(function(child) { return isPureProseSubtree(child, 0); }) && maxVerticalGap(children) <= 48) {
        return [node];
      }
    }

    // Horizontal icon/label/action rows stay atomic.
    if (verticalRowCount(children) < 2) return [node];
'@
$R86BuilderText = Replace-Required $R86BuilderText $BeforeVerticalSplit $SemanticGrouping 'group semantic row with its expanded detail'

# ---------------------------------------------------------------------------
# Replace the generated inner r75 stamp/observer bodies. These strings are
# embedded into the generated r86 builder and applied only after its own clean
# worktree gate, preserving the r83/r85 packaging safety model.
# ---------------------------------------------------------------------------
$StampBody = @'
  function nativeSentTimeForSegment(segment) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return null;
    const candidates = [];
    if (segment.matches('[data-assistant-message-sent-time],time[datetime]')) candidates.push(segment);
    segment.querySelectorAll('[data-assistant-message-sent-time],time[datetime]').forEach(function(node) { candidates.push(node); });
    for (const candidate of candidates) {
      if (!(candidate instanceof Element)) continue;
      if (candidate.closest('[data-message-author-role="user"],[data-message-author="user"]')) continue;
      const parsed = nativeTime(candidate);
      if (parsed) return parsed;
    }
    return null;
  }

  function isFinalAssistantSurface(segment) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return false;
    if (segment.matches('[data-local-conversation-final-assistant]')) return true;
    if (segment.querySelector('[data-local-conversation-final-assistant]')) return true;
    // A generic data-message-author-role="assistant" wrapper may contain an
    // entire multi-step turn, so it is identity/root only, never final by itself.
    return !!segment.querySelector('[data-assistant-message-sent-time]');
  }

  function nativeTimeForSegment(segment, root) {
    if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return null;
    const own = nativeSentTimeForSegment(segment);
    if (own) return own;
    if (!isFinalAssistantSurface(segment)) return null;
    const actionRow = actionRowForSegment(segment, root);
    if (!actionRow) return null;
    return nativeSentTimeForSegment(actionRow);
  }

  function actionRowForSegment(segment, root) {
    if (!(segment instanceof Element) || !isFinalAssistantSurface(segment)) return null;
    const turn = segment.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') ||
      (root instanceof Element ? root.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') : null) ||
      segment;
    const sentTimes = Array.from(turn.querySelectorAll('[data-assistant-message-sent-time]'))
      .filter(function(node) { return !node.closest('[data-message-author-role="user"],[data-message-author="user"]'); });
    const sentTime = sentTimes.length ? sentTimes[sentTimes.length - 1] : null;
    return sentTime && sentTime.parentElement ? sentTime.parentElement : null;
  }

  function timestampBadgeForKey(key) {
    if (!key) return null;
    const badges = document.querySelectorAll('[' + BADGE_ATTR + ']');
    for (const badge of badges) {
      if (badge.getAttribute('data-cas-output-key') === key) return badge;
    }
    return null;
  }

  function timestampIsEstimated(source) {
    const value = String(source || '').toLowerCase();
    return !(value.includes('native') || value.includes('sent time') || value.includes('jsonl'));
  }

  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment) || isUserAuthoredSurface(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;
    if (!state.timestampTimes) state.timestampTimes = new Map();

    const actionRow = actionRowForSegment(segment, root);
    const host = actionRow && actionRow.parentElement;
    let existing = timestampBadgeForKey(key);
    if (!existing) existing = segment.querySelector(':scope > [' + BADGE_ATTR + ']');
    if (existing) return;

    const remembered = Number(state.timestampTimes.get(key));
    const attrTime = Number(segment.getAttribute(FIRST_SEEN_ATTR));
    const when = Number.isFinite(attrTime) && attrTime > 0
      ? attrTime
      : (Number.isFinite(remembered) && remembered > 0 ? remembered : epoch);
    if (!Number.isFinite(when) || when <= 0) return;

    const estimated = timestampIsEstimated(source);
    const badge = document.createElement('div');
    badge.setAttribute(BADGE_ATTR, 'true');
    badge.setAttribute('data-cas-output-key', key);
    badge.setAttribute('data-cas-timestamp-confidence', estimated ? 'estimated' : 'exact');
    badge.setAttribute('aria-label', estimated ? 'Assistant output timestamp, estimated locally' : 'Assistant output timestamp');
    badge.textContent = (estimated ? '≈ ' : '') + clock(when);
    badge.title = fullTime(when) + ' · ' + (estimated ? 'estimated: ' : 'exact: ') + String(source || 'unknown source');
    badge.style.cssText = 'position:relative;z-index:2;display:flex;width:100%;box-sizing:border-box;align-items:center;justify-content:flex-end;min-height:10px;margin:2px 0 0 0;padding:0 3px;border:0;background:transparent;box-shadow:none;color:color-mix(in srgb,CanvasText 56%,transparent);font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.78;';

    if (actionRow && host) actionRow.insertAdjacentElement('afterend', badge);
    else segment.appendChild(badge);

    segment.setAttribute(HOST_ATTR, 'true');
    segment.setAttribute(FIRST_SEEN_ATTR, String(when));
    state.timestampTimes.set(key, when);
  }
'@

$ObserverBody = @'
  function strictAssistantRootFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    const direct = element.closest('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    if (direct) return direct;
    const broad = assistantRootFor(element);
    if (!(broad instanceof Element)) return null;
    const nested = broad.querySelector('[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
    return nested || broad;
  }

  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    const primary = '[data-content-search-assistant-turn-key],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]';
    document.querySelectorAll(primary).forEach(function(node) {
      const root = node instanceof Element ? node : null;
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root) || isUserAuthoredSurface(root)) return;
      seen.add(root); roots.push(root);
    });
    document.querySelectorAll('[data-chatgpt-conversation-turn="true"]').forEach(function(turn) {
      if (!(turn instanceof Element) || insideComposer(turn) || insideOwnUi(turn)) return;
      const nested = turn.querySelector(primary);
      const root = nested || (turn.querySelector('[data-assistant-message-sent-time]') ? turn : null);
      if (!(root instanceof Element) || seen.has(root) || isUserAuthoredSurface(root)) return;
      seen.add(root); roots.push(root);
    });
    return roots;
  }

  function resetTimestampArtifacts() {
    document.querySelectorAll('[' + BADGE_ATTR + ']').forEach(function(node) { node.remove(); });
    document.querySelectorAll('[' + HOST_ATTR + ']').forEach(function(node) {
      node.removeAttribute(HOST_ATTR);
      node.removeAttribute(FIRST_SEEN_ATTR);
    });
    try {
      for (let index = localStorage.length - 1; index >= 0; index -= 1) {
        const key = String(localStorage.key(index) || '');
        if (/^cas-r\d+-segment-times(?:-|$)/i.test(key) || key === 'cas-r74-segment-times') localStorage.removeItem(key);
      }
    } catch {}
    state.timestampTimes = new Map();
    state.timestampBaselineElements = new WeakSet();
    state.timestampBaselineKeys = new Set();
    state.timestampRuntimeStartedAt = Date.now();
  }

  function baselineExistingDom() {
    resetTimestampArtifacts();
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return;
        const key = segmentKey(segment, root);
        if (!key) return;
        state.timestampBaselineElements.add(segment);
        state.timestampBaselineKeys.add(key);
        const native = nativeTimeForSegment(segment, root);
        if (native) stampSegment(segment, root, native.epoch, native.source);
      });
    });
  }

  function hasRecentLiveUsage() {
    const updated = Number(state.metrics && state.metrics.externalUpdatedAt);
    if (!Number.isFinite(updated) || updated <= 0) return false;
    const age = Date.now() - updated;
    return age >= -5000 && age <= 90000;
  }

  function stampMutationNode(node) {
    const root = strictAssistantRootFor(node);
    if (!root) return;
    const segment = segmentForMutation(node, root);
    if (!(segment instanceof Element) || !isVisible(segment) || isUserAuthoredSurface(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;

    const native = nativeTimeForSegment(segment, root);
    if (native) {
      stampSegment(segment, root, native.epoch, native.source);
      return;
    }

    // Never assign "now" to content that was already on screen when r86 was
    // installed. React text mutations/remounts of historical output are not a
    // trustworthy generation timestamp.
    if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
    if (!hasRecentLiveUsage()) return;
    stampSegment(segment, root, Date.now(), 'first observed live output mutation locally');
  }

  function sweepOutputSegments(allowFresh) {
    assistantRootsNow().forEach(function(root) {
      topLevelSegments(root).forEach(function(segment) {
        if (!(segment instanceof Element) || isUserAuthoredSurface(segment)) return;
        if (segment.querySelector(':scope > [' + BADGE_ATTR + ']')) return;
        const key = segmentKey(segment, root);
        if (!key) return;
        const native = nativeTimeForSegment(segment, root);
        if (native) {
          stampSegment(segment, root, native.epoch, native.source);
          return;
        }
        if (!allowFresh) return;
        if (state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)) return;
        if (!hasRecentLiveUsage()) return;
        stampSegment(segment, root, Date.now(), 'first observed live output segment locally');
      });
    });
  }

  function scheduleOutputSweep() {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(function() {
      state.timer = null;
      try { sweepOutputSegments(false); } catch {}
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
            const probes = added.querySelectorAll('p,li,pre,[role="status"],[data-testid],[data-local-conversation-final-assistant],[data-message-author-role="assistant"]');
            let count = 0;
            for (const probe of probes) {
              if (count++ >= 64) break;
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

$StampB64 = [Convert]::ToBase64String($Utf8NoBom.GetBytes($StampBody))
$ObserverB64 = [Convert]::ToBase64String($Utf8NoBom.GetBytes($ObserverBody))

# Inject r86 stamp/observer rewrites into the generated r84/r85 inner builder,
# after it has produced $PatchedR75 but before it hashes/installs that source.
$InnerNeedle = @'
$PatchedR75 = Replace-BlockRequired `
    $OriginalR75 `
    '$NewSegmentation = @''' `
    '$NewStamp = @''' `
    $NewSegmentation `
    'per-output visual segmentation'
'@
$InnerExtraTemplate = @'

$R86StampBody = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__STAMP_B64__'))
$R86ObserverBody = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__OBSERVER_B64__'))
$R86StampWrapped = '$NewStamp = @''' + "`r`n" + $R86StampBody + "`r`n'@"
$R86ObserverWrapped = '$NewObserver = @''' + "`r`n" + $R86ObserverBody + "`r`n'@"
$PatchedR75 = Replace-BlockRequired $PatchedR75 '$NewStamp = @''' '$NewObserver = @''' $R86StampWrapped 'r86 strict timestamp ownership'
$PatchedR75 = Replace-BlockRequired $PatchedR75 '$NewObserver = @''' 'try {' $R86ObserverWrapped 'r86 live-only timestamp observer'
$PatchedR75 = $PatchedR75.Replace('try { sweepOutputSegments(true); } catch {}','try { sweepOutputSegments(false); } catch {}')
'@
$InnerExtra = $InnerExtraTemplate.Replace('__STAMP_B64__',$StampB64).Replace('__OBSERVER_B64__',$ObserverB64)
$R86BuilderText = Insert-AfterRequired $R86BuilderText $InnerNeedle $InnerExtra 'inject strict stamp/observer into generated timestamp source'

foreach ($Marker in @(
    'function isUserAuthoredSurface(node) {',
    'isUserAuthoredSurface(candidate)',
    'function nativeSentTimeForSegment(segment) {',
    'function isFinalAssistantSurface(segment) {',
    'state.timestampBaselineElements = new WeakSet();',
    'if (!hasRecentLiveUsage()) return;',
    "try { sweepOutputSegments(false); } catch {}",
    'R86_TIMESTAMP_GROUPING_PREFLIGHT_PASS',
    'R86_TIMESTAMP_ACTIONROW_V4_PASS',
    'R86_EXACT_TOKEN_TELEMETRY_PASS',
    'R86_R43_R65_CARRY_FORWARD_PACKAGE_PASS',
    'visible/package identity is r86 / 2.4.5+86'
)) {
    if (-not $R86BuilderText.Contains($Marker)) { throw "r86 generated builder verification failed: $Marker" }
}
if ($R86BuilderText.Contains("nativeTime(segment) || nativeTime(root)")) {
    throw 'r86 still contains broad root native-time inheritance'
}

Assert-PowerShellParses $R86BuilderText 'generated r86 builder'

Write-Host 'R86_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - user-authored bubbles are excluded from timestamp surfaces'
Write-Host '  - generic assistant wrappers are identity only; they are not treated as final replies'
Write-Host '  - progress/tool/prose outputs cannot inherit a broad root/native sent-time'
Write-Host '  - legacy r74-r85 structural timestamp cache is cleared and no longer reused'
Write-Host '  - historical baseline/remounted DOM is never assigned Date.now()'
Write-Host '  - Date.now() fallback is mutation-only and requires a recent exact JSONL usage pulse'
Write-Host '  - one semantic action row plus its expanded detail remains one timestamp event'
Write-Host '  - periodic/scheduled sweeps are exact-only; they cannot manufacture fresh historical times'
Write-Host '  - telemetry/provider/r43-r65 carry-forward are inherited unchanged from r85/r83'

try {
    Write-Utf8NoBom $TempR86Builder $R86BuilderText
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR86Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r86 nested builder failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R86_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R86_TIMESTAMP_CORRECTNESS_PASS' -ForegroundColor Green
        Write-Host '  - stale cross-version timestamp replay removed'
        Write-Host '  - user-message timestamp contamination removed'
        Write-Host '  - broad root sent-time leakage removed'
        Write-Host '  - historical remounts are left unstamped rather than given a false current time'
    }
}
finally {
    Remove-Item -LiteralPath $TempR86Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r86] removed temporary generated builder; tracked worktree stays pull-friendly'
}
