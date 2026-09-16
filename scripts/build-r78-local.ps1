param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R77Builder = Join-Path $PSScriptRoot 'build-r77-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$TempR78Builder = Join-Path $PSScriptRoot '.build-r78-from-r77.generated.ps1'

foreach ($Path in @($R77Builder, $R75Builder)) {
    if (-not (Test-Path $Path)) { throw "r78 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR77 = [System.IO.File]::ReadAllText($R77Builder)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r78 expected text missing: $Label" }
    return $Text.Replace($Old, $New)
}

function Replace-BlockRequired(
    [string]$Text,
    [string]$StartMarker,
    [string]$EndMarker,
    [string]$Replacement,
    [string]$Label
) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r78 patch start marker missing: $Label" }
    $End = $Text.IndexOf($EndMarker, $Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r78 patch end marker missing: $Label" }
    return $Text.Substring(0, $Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

# ---------------------------------------------------------------------------
# r78 timestamp v4
# ---------------------------------------------------------------------------
# The previous renderer could discover many current Codex output surfaces, but
# it still placed every badge as a child of the guessed segment and let a
# turn-level native sent-time leak into unrelated progress/tool segments.
#
# r78 follows the proven Codex-Monitor strategy for final assistant replies:
# use the native [data-assistant-message-sent-time] row as the stable reply
# action-row anchor and place our timestamp immediately after it. Progress,
# tool, command and agent surfaces keep their own first-observed timestamps and
# never inherit the final reply's native sent time. This produces one visible
# timestamp per output surface without disturbing Codex's fixed-height action
# row.
$NewStamp = @'
$NewStamp = @'
  function nativeTimeForSegment(segment, root) {
    if (!(segment instanceof Element)) return null;
    const direct = nativeTime(segment);
    if (direct) return direct;

    const isFinal = segment.matches('[data-local-conversation-final-assistant],[data-message-author-role="assistant"]') ||
      !!segment.querySelector('[data-assistant-message-sent-time]');
    if (!isFinal) return null;

    if (root instanceof Element) return nativeTime(root);
    return null;
  }

  function actionRowForSegment(segment, root) {
    if (!(segment instanceof Element)) return null;
    const isFinal = segment.matches('[data-local-conversation-final-assistant],[data-message-author-role="assistant"]') ||
      !!segment.querySelector('[data-assistant-message-sent-time]');
    if (!isFinal) return null;

    const turn = segment.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') ||
      (root instanceof Element ? root.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') : null) ||
      segment;
    const sentTime = turn.querySelector('[data-assistant-message-sent-time]');
    if (sentTime && sentTime.parentElement) return sentTime.parentElement;
    return null;
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
    if (!value) return true;
    return !(
      value.includes('native') ||
      value.includes('sent time') ||
      value.includes('persisted') ||
      value.includes('jsonl') ||
      value.includes('remembered')
    );
  }

  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
    const key = segmentKey(segment, root);
    if (!key) return;

    const actionRow = actionRowForSegment(segment, root);
    const host = actionRow && actionRow.parentElement;
    let existing = timestampBadgeForKey(key);
    if (!existing) {
      existing = segment.querySelector(':scope > [' + BADGE_ATTR + ']');
    }
    if (existing) return;

    const cache = readSeenCache();
    const remembered = Number(cache[key]);
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
    badge.title = fullTime(when) + ' · ' + (estimated ? 'estimated: ' : 'exact/remembered: ') + String(source || 'unknown source');
    badge.style.cssText = 'position:relative;z-index:2;display:flex;width:100%;box-sizing:border-box;align-items:center;justify-content:flex-end;min-height:11px;margin:2px 0 1px 0;padding:0 3px;border:0;background:transparent;box-shadow:none;backdrop-filter:none;-webkit-backdrop-filter:none;color:color-mix(in srgb,CanvasText 58%,transparent);font:9px/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.01em;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.82;';

    if (actionRow && host) {
      // Keep Codex's native fixed-height reply action row untouched. This is
      // the same safe layout strategy used by Codex-Monitor for reply chips.
      actionRow.insertAdjacentElement('afterend', badge);
    } else {
      // Progress/tool/agent surfaces own their timestamp. Appending rather than
      // prepending keeps the marker close to the end of the output that caused
      // the observation and survives clipped/virtualized top edges.
      segment.appendChild(badge);
    }

    segment.setAttribute(HOST_ATTR, 'true');
    segment.setAttribute(FIRST_SEEN_ATTR, String(when));
    rememberSegmentTime(key, when);
  }
'@
'@

$PatchedR75 = Replace-BlockRequired `
    $OriginalR75 `
    '$NewStamp = @''' `
    '$NewObserver = @''' `
    $NewStamp `
    'timestamp v4 action-row placement'

$PatchedR75 = Replace-Required `
    $PatchedR75 `
    'const native = nativeTime(segment) || nativeTime(root);' `
    'const native = nativeTimeForSegment(segment, root);' `
    'do not leak final reply native time into progress segments'

foreach ($Marker in @(
    'function nativeTimeForSegment(segment, root) {',
    'function actionRowForSegment(segment, root) {',
    "data-cas-timestamp-confidence",
    "actionRow.insertAdjacentElement('afterend', badge);",
    "segment.appendChild(badge);",
    "const native = nativeTimeForSegment(segment, root);"
)) {
    if (-not $PatchedR75.Contains($Marker)) { throw "r78 timestamp source verification failed: $Marker" }
}

# ---------------------------------------------------------------------------
# Reuse r77 telemetry recovery, but make the generated package/markers r78.
# ---------------------------------------------------------------------------
$PatchedR77 = $OriginalR77
$PatchedR77 = Replace-Required $PatchedR77 `
    '$R77OutputText = $OriginalR76Output.Replace(''r76'', ''r77'').Replace(''R76'', ''R77'').Replace(''+76'', ''+77'')' `
    '$R77OutputText = $OriginalR76Output.Replace(''r76'', ''r78'').Replace(''R76'', ''R78'').Replace(''+76'', ''+78'')' `
    'r78 output identity'
$PatchedR77 = Replace-Required $PatchedR77 `
    '$R77EntryText = $OriginalR76Local.Replace(''r76'', ''r77'').Replace(''R76'', ''R77'').Replace(''+76'', ''+77'')' `
    '$R77EntryText = $OriginalR76Local.Replace(''r76'', ''r78'').Replace(''R76'', ''R78'').Replace(''+76'', ''+78'')' `
    'r78 entry identity'
$PatchedR77 = Replace-Required $PatchedR77 "Replace('r75', 'r77')" "Replace('r75', 'r78')" 'r78 generated-source marker'
$PatchedR77 = Replace-Required $PatchedR77 'R77_EXACT_TOKEN_TELEMETRY_PASS' 'R78_EXACT_TOKEN_TELEMETRY_PASS' 'r78 exact telemetry marker'
$PatchedR77 = Replace-Required $PatchedR77 'R77_LOCAL_ENTRYPOINT_PASS' 'R78_LOCAL_ENTRYPOINT_PASS' 'r78 entrypoint marker'
$PatchedR77 = Replace-Required $PatchedR77 'R77_TIMESTAMP_TELEMETRY_RECOVERY_PASS' 'R78_TIMESTAMP_TELEMETRY_BASE_PASS' 'r78 wrapper pass marker'

try {
    Write-Utf8NoBom $R75Builder $PatchedR75
    Write-Utf8NoBom $TempR78Builder $PatchedR77

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempR78Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r78 local build failed with exit code $LASTEXITCODE" }

    Write-Host ''
    Write-Host 'R78_TIMESTAMP_ACTIONROW_V4_PASS' -ForegroundColor Green
    Write-Host '  - final assistant timestamps anchor below Codex native sent-time/action rows'
    Write-Host '  - progress/tool/agent outputs use their own first-observed time instead of inheriting final sent-time'
    Write-Host '  - estimated timestamps are visibly prefixed with ≈ and expose confidence metadata'
    Write-Host '  - r77 exact telemetry bridge/thread resolver is preserved in the generated r78 package'
}
finally {
    Write-Utf8NoBom $R75Builder $OriginalR75
    Remove-Item -LiteralPath $TempR78Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r78] restored temporary source patches; worktree remains pull-friendly'
}
