param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R89Builder = Join-Path $PSScriptRoot 'build-r89-local.ps1'
$R89Observer = Join-Path $PSScriptRoot 'r89-timestamp-observer.js'
$R89PaneJs = Join-Path $PSScriptRoot 'r89-pane-runtime.js'
$R89TruthJs = Join-Path $PSScriptRoot 'r89-telemetry-truth.js'
$R89PanePatch = Join-Path $PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'

$TempBuilder = Join-Path $PSScriptRoot '.build-r90-from-r89.generated.ps1'
$TempObserver = Join-Path $PSScriptRoot 'r90-timestamp-observer.js'
$TempPaneJs = Join-Path $PSScriptRoot 'r90-pane-runtime.js'
$TempTruthJs = Join-Path $PSScriptRoot 'r90-telemetry-truth.js'
$TempPanePatch = Join-Path $PSScriptRoot 'r90-r75-pane-runtime-patch-v4.inc.ps1'
$TempObserverCheck = Join-Path $PSScriptRoot '.r90-observer-syntax.generated.mjs'

foreach ($Path in @($R89Builder,$R89Observer,$R89PaneJs,$R89TruthJs,$R89PanePatch)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r90 required r89 source missing: $Path" }
}
foreach ($Path in @($TempBuilder,$TempObserver,$TempPaneJs,$TempTruthJs,$TempPanePatch,$TempObserverCheck)) {
    if (Test-Path -LiteralPath $Path) { throw "r90 refuses to overwrite pre-existing temporary path: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r90 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $StartIndex = $Text.IndexOf($Start)
    if ($StartIndex -lt 0) { throw "r90 block start missing: $Label" }
    $EndIndex = $Text.IndexOf($End,$StartIndex + $Start.Length)
    if ($EndIndex -le $StartIndex) { throw "r90 block end missing: $Label" }
    return $Text.Substring(0,$StartIndex) + $Replacement + "`n`n" + $Text.Substring($EndIndex)
}
function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r90 PowerShell parse failed: $Label :: $Summary"
    }
}

$Head = (git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'r90 git rev-parse failed' }
$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r90 git status failed' }
if ($Dirty.Count -gt 0) { throw "r90 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

$OriginalBuilder = [System.IO.File]::ReadAllText($R89Builder)
$OriginalObserver = [System.IO.File]::ReadAllText($R89Observer)
$OriginalPane = [System.IO.File]::ReadAllText($R89PaneJs)
$OriginalTruth = [System.IO.File]::ReadAllText($R89TruthJs)
$OriginalPanePatch = [System.IO.File]::ReadAllText($R89PanePatch)

# ---------------------------------------------------------------------------
# Timestamp semantic grouping / remount safety
# ---------------------------------------------------------------------------
$R90TimestampHelpers = @'
  function semanticTimestampGroupFor(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;
    const turn = element.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]');
    const selector = '[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]';
    let current = element.closest(selector);
    if (!(current instanceof Element) || isUserAuthoredSurface(current)) return null;
    let owner = current;
    let parent = current.parentElement;
    while (parent instanceof Element && parent !== turn) {
      if (parent.matches(selector) && !isUserAuthoredSurface(parent)) owner = parent;
      parent = parent.parentElement;
    }
    return owner;
  }

  function canonicalTimestampSegment(segment, root) {
    if (!(segment instanceof Element)) return segment;
    const grouped = semanticTimestampGroupFor(segment);
    if (!(grouped instanceof Element)) return segment;
    if (!(root instanceof Element)) return grouped;
    if (root === grouped || root.contains(grouped) || grouped.contains(root)) return grouped;
    return segment;
  }

  function nativeTurnTimeForEstimate(node, root) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element)) return null;
    const turn = element.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') ||
      (root instanceof Element ? root.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"]') : null);
    if (!(turn instanceof Element)) return null;
    const sent = Array.from(turn.querySelectorAll('[data-assistant-message-sent-time],time[datetime]'))
      .filter(function(candidate) { return candidate instanceof Element && !candidate.closest('[data-message-author-role="user"],[data-message-author="user"]'); });
    for (let index = sent.length - 1; index >= 0; index -= 1) {
      const parsed = nativeTime(sent[index]);
      if (parsed && Number.isFinite(parsed.epoch) && parsed.epoch > 0) return parsed;
    }
    return null;
  }

  function turnIsHistoricalForEstimate(node, root) {
    const exact = nativeTurnTimeForEstimate(node, root);
    if (!exact) return false;
    const started = Number(state.timestampRuntimeStartedAt);
    if (!Number.isFinite(started) || started <= 0) return false;
    return exact.epoch < started - 2000;
  }
'@

$R90Observer = Replace-Required $OriginalObserver `
    '  function activeGenerationUiPresentFor(node) {' `
    ($R90TimestampHelpers + "`n`n  function activeGenerationUiPresentFor(node) {") `
    'insert semantic timestamp helpers'

$OldSemanticRoot = @'
    const semantic = element.closest('[data-chatgpt-conversation-turn="true"],[data-turn-key],[data-message-author-role="assistant"],[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
    if (semantic instanceof Element && !isUserAuthoredSurface(semantic)) return semantic;
'@
$NewSemanticRoot = @'
    const semantic = semanticTimestampGroupFor(element);
    if (semantic instanceof Element && !isUserAuthoredSurface(semantic)) return semantic;
'@
$R90Observer = Replace-Required $R90Observer $OldSemanticRoot $NewSemanticRoot 'canonical semantic live-tail root'

$R90Observer = Replace-Required $R90Observer `
    '    const segment = segmentForMutation(node, root);' `
    "    const rawSegment = segmentForMutation(node, root);`n    const segment = canonicalTimestampSegment(rawSegment, root);" `
    'canonical mutation segment'

$TopLevelNeedle = '    topLevelSegments(root).forEach(function(segment) {'
$TopLevelCount = ([regex]::Matches($R90Observer,[regex]::Escape($TopLevelNeedle))).Count
if ($TopLevelCount -lt 3) { throw "r90 expected at least 3 topLevelSegments loops, found $TopLevelCount" }
$R90Observer = $R90Observer.Replace(
    $TopLevelNeedle,
    "    topLevelSegments(root).forEach(function(rawSegment) {`n      const segment = canonicalTimestampSegment(rawSegment, root);"
)

foreach ($Pair in @(
    @("    stampSegment(segment, root, Date.now(), 'first observed live output mutation locally');", "    if (turnIsHistoricalForEstimate(segment, root)) return;`n    stampSegment(segment, root, Date.now(), 'first observed live output mutation locally');"),
    @("      stampSegment(segment, root, Date.now(), 'first observed live output segment locally');", "      if (turnIsHistoricalForEstimate(segment, root)) return;`n      stampSegment(segment, root, Date.now(), 'first observed live output segment locally');")
)) {
    if (-not $R90Observer.Contains($Pair[0])) { throw "r90 timestamp estimate guard source missing: $($Pair[0])" }
    $R90Observer = $R90Observer.Replace($Pair[0],$Pair[1])
}

foreach ($Marker in @(
    'function semanticTimestampGroupFor(node) {',
    'function canonicalTimestampSegment(segment, root) {',
    'function turnIsHistoricalForEstimate(node, root) {',
    'const semantic = semanticTimestampGroupFor(element);',
    'const segment = canonicalTimestampSegment(rawSegment, root);',
    'if (turnIsHistoricalForEstimate(segment, root)) return;'
)) {
    if (-not $R90Observer.Contains($Marker)) { throw "r90 timestamp refinement invariant missing: $Marker" }
}
Write-Host 'R90_SEMANTIC_TIMESTAMP_CONTRACT_PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------
# Pane telemetry ownership: distinguish waiting from truly unowned, and accept
# the current envelope thread only when it is provably the same exact snapshot.
# ---------------------------------------------------------------------------
$R90Ownership = @'
  function paneTelemetryOwnership(threadId) {
    const paneThread = normalizePaneId(threadId);
    const metrics = state.metrics || {};
    const exact = metrics.externalExact && typeof metrics.externalExact === 'object' ? metrics.externalExact : null;
    const exactThread = normalizePaneId(exact && exact.threadId);
    const envelopeThread = normalizePaneId(metrics.externalThreadId);
    const exactUpdated = Number(exact && exact.updatedAt);
    const envelopeUpdated = Number(metrics.externalUpdatedAt);
    const sameEnvelope = !!exact && Number.isFinite(exactUpdated) && Number.isFinite(envelopeUpdated) && Math.abs(exactUpdated - envelopeUpdated) <= 1500;
    const sourceThread = exactThread || (sameEnvelope ? envelopeThread : '');
    const owned = !!paneThread && !!sourceThread && paneThread === sourceThread;
    const awaiting = !owned && !!paneThread && !!envelopeThread && paneThread === envelopeThread;
    const conflicting = !!paneThread && !!sourceThread && paneThread !== sourceThread;
    return {
      owned,
      awaiting,
      conflicting,
      paneThread,
      sourceThread,
      envelopeThread,
      sameEnvelope,
      exact,
    };
  }
'@
$R90Truth = Replace-BlockRequired $OriginalTruth `
    '  function paneTelemetryOwnership(threadId) {' `
    '  function paneActivityState(bar) {' `
    $R90Ownership `
    'pane ownership truth'

$OldSpeedUnowned = @'
    if (!ownership.owned) {
      return { text: '-- tok/s', source: 'unowned', confidence: 'unavailable', title: 'Unavailable: exact telemetry belongs to another thread.' };
    }
'@
$NewSpeedUnowned = @'
    if (!ownership.owned) {
      if (ownership.awaiting) {
        return { text: '-- tok/s', source: 'waiting', confidence: 'unavailable', title: 'Waiting for a pane-owned exact JSONL snapshot for the already matched current thread.' };
      }
      return { text: '-- tok/s', source: 'unowned', confidence: 'unavailable', title: 'Unavailable: exact telemetry belongs to another thread or has no provable pane ownership.' };
    }
'@
$R90Truth = Replace-Required $R90Truth $OldSpeedUnowned $NewSpeedUnowned 'waiting speed state'

$OldStatusHead = @'
    const ownership = paneTelemetryOwnership(threadId);
    const activity = ownership.owned ? paneActivityState(bar) : 'unowned';
    const exact = ownership.owned ? ownership.exact : null;
    const stateLabel = !ownership.owned ? 'UNOWNED' : activity.toUpperCase();
    const stateTitle = !ownership.owned
      ? 'No pane-owned exact JSONL snapshot is available.'
      : (activity === 'live'
        ? 'LIVE is backed by pane-scoped stop/busy UI evidence. Counts are exact JSONL snapshots and may update only at token_count boundaries.'
        : (activity === 'idle'
          ? 'IDLE is backed by a visible pane send/submit control. Counts are the last exact JSONL snapshot, not live activity.'
          : 'UNKNOWN: there is not enough pane-local UI evidence to claim LIVE or IDLE.'));
'@
$NewStatusHead = @'
    const ownership = paneTelemetryOwnership(threadId);
    const activity = ownership.owned ? paneActivityState(bar) : (ownership.awaiting ? 'waiting' : 'unowned');
    const exact = ownership.owned ? ownership.exact : null;
    const stateLabel = ownership.owned ? activity.toUpperCase() : (ownership.awaiting ? 'WAITING' : 'UNOWNED');
    const stateTitle = ownership.owned
      ? (activity === 'live'
        ? 'LIVE is backed by pane-scoped stop/busy UI evidence. Counts are exact JSONL snapshots and may update only at token_count boundaries.'
        : (activity === 'idle'
          ? 'IDLE is backed by a visible pane send/submit control. Counts are the last exact JSONL snapshot, not live activity.'
          : 'UNKNOWN: there is not enough pane-local UI evidence to claim LIVE or IDLE.'))
      : (ownership.awaiting
        ? 'WAITING: the current pane thread matches the collector envelope, but a same-envelope exact last_token_usage snapshot is not yet available. No global/native metrics are borrowed.'
        : 'UNOWNED: the available exact JSONL snapshot is not provably owned by this pane.');
'@
$R90Truth = Replace-Required $R90Truth $OldStatusHead $NewStatusHead 'waiting ownership presentation'

foreach ($Marker in @(
    'const sameEnvelope =',
    'const awaiting = !owned',
    "source: 'waiting'",
    "ownership.awaiting ? 'WAITING' : 'UNOWNED'",
    'No global/native metrics are borrowed.'
)) {
    if (-not $R90Truth.Contains($Marker)) { throw "r90 ownership refinement invariant missing: $Marker" }
}
Write-Host 'R90_PANE_OWNERSHIP_TRUTH_CONTRACT_PASS' -ForegroundColor Green

# Retarget runtime source identities without modifying the r89 baseline.
$R90Observer = $R90Observer.Replace('R89','R90').Replace('r89','r90')
$R90Pane = $OriginalPane.Replace('R89','R90').Replace('r89','r90')
$R90Truth = $R90Truth.Replace('R89','R90').Replace('r89','r90')
$R90PanePatch = $OriginalPanePatch.Replace('R89','R90').Replace('r89','r90')
$R90Builder = $OriginalBuilder.Replace('R89','R90').Replace('r89','r90').Replace('+89','+90')

foreach ($Marker in @(
    "`$R90Observer = Join-Path `$PSScriptRoot 'r90-timestamp-observer.js'",
    "`$R90PaneJs = Join-Path `$PSScriptRoot 'r90-pane-runtime.js'",
    "`$R90TelemetryTruthJs = Join-Path `$PSScriptRoot 'r90-telemetry-truth.js'",
    "`$R90PanePatch = Join-Path `$PSScriptRoot 'r90-r75-pane-runtime-patch-v4.inc.ps1'",
    'R90_RUNTIME_CORRECTNESS_PASS',
    'visible/package identity is r90 / 2.4.5+90'
)) {
    if (-not $R90Builder.Contains($Marker)) { throw "r90 generated builder invariant missing: $Marker" }
}
Assert-PowerShellParses $R90PanePatch 'retargeted r90 pane generation include'
Assert-PowerShellParses $R90Builder 'retargeted r90 wrapper'
Write-Host 'R90_GENERATED_POWERSHELL_PARSE_PASS' -ForegroundColor Green

try {
    Write-Utf8NoBom $TempObserver $R90Observer
    Write-Utf8NoBom $TempPaneJs $R90Pane
    Write-Utf8NoBom $TempTruthJs $R90Truth
    Write-Utf8NoBom $TempPanePatch $R90PanePatch
    Write-Utf8NoBom $TempBuilder $R90Builder

    Write-Utf8NoBom $TempObserverCheck ("function __r90ObserverSyntaxOnly(){`n" + $R90Observer + "`n}`n")
    node --check $TempObserverCheck
    if ($LASTEXITCODE -ne 0) { throw 'r90 timestamp observer JavaScript syntax check failed' }
    node --check $TempPaneJs
    if ($LASTEXITCODE -ne 0) { throw 'r90 pane runtime JavaScript syntax check failed' }
    node --check $TempTruthJs
    if ($LASTEXITCODE -ne 0) { throw 'r90 telemetry truth JavaScript syntax check failed' }
    Write-Host 'R90_GENERATED_JS_SYNTAX_PASS' -ForegroundColor Green

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r90 inherited r89 build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r90 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r90 nested build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R90_SEMANTIC_RUNTIME_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - nested command/tool/detail rows collapse to one semantic timestamp owner'
        Write-Host '  - exact/native timestamps remain authoritative; estimated timestamps remain visibly approximate'
        Write-Host '  - historical turns with native sent-time predating runtime startup cannot receive new Date.now() estimates'
        Write-Host '  - pane telemetry distinguishes WAITING from truly UNOWNED while still refusing global/native metric borrowing'
        Write-Host '  - same-envelope collector ownership may recover exact metrics when the exact snapshot omitted its thread field'
    } else {
        Write-Host ''
        Write-Host 'R90_SEMANTIC_RUNTIME_CORRECTNESS_PASS' -ForegroundColor Green
        Write-Host '  - semantic timestamp grouping reduces duplicate/drifting timestamps on expanded tool rows'
        Write-Host '  - historical/remounted rows are guarded from false current-time estimates when exact turn evidence exists'
        Write-Host '  - pane status ownership reports WAITING vs UNOWNED truthfully and recovers same-envelope exact ownership'
        Write-Host '  - visible/package identity is r90 / 2.4.5+90'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempObserver,$TempPaneJs,$TempTruthJs,$TempPanePatch,$TempObserverCheck)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r90] removed generated runtime/build helpers; r89 baseline remains untouched'
}
