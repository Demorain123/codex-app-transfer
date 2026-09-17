param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R88Builder = Join-Path $PSScriptRoot 'build-r88-local.ps1'
$R89Observer = Join-Path $PSScriptRoot 'r89-timestamp-observer.js'
$R89PaneJs = Join-Path $PSScriptRoot 'r89-pane-runtime.js'
$R89TelemetryTruthJs = Join-Path $PSScriptRoot 'r89-telemetry-truth.js'
$R89PanePatch = Join-Path $PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'
$TempBuilder = Join-Path $PSScriptRoot '.build-r89-from-r88.generated.ps1'
$TempObserverCheck = Join-Path $PSScriptRoot '.r89-observer-syntax.generated.mjs'

foreach ($Path in @($R88Builder,$R89Observer,$R89PaneJs,$R89TelemetryTruthJs,$R89PanePatch)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r89 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR88 = [System.IO.File]::ReadAllText($R88Builder)
$ObserverText = [System.IO.File]::ReadAllText($R89Observer)
$PaneJsText = [System.IO.File]::ReadAllText($R89PaneJs)
$TelemetryTruthText = [System.IO.File]::ReadAllText($R89TelemetryTruthJs)
$PanePatchText = [System.IO.File]::ReadAllText($R89PanePatch)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r89 PowerShell parse failed: $Label :: $Summary"
    }
}

$Head = (git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'r89 git rev-parse failed' }
$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r89 git status failed' }
if ($Dirty.Count -gt 0) { throw "r89 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

# Runtime-smoke regressions from r88 must be represented as explicit preflight
# contracts before any nested builder or Cargo work starts.
foreach ($Marker in @(
    'function canonicalComposerForEditable(editable) {',
    'if (roots.length) return roots;',
    'function removeLegacyOrDuplicateStatusBars() {',
    'function statusBarForComposer(composer) {',
    'bar.nextSibling === composer',
    'parent.insertBefore(bar, composer)',
    'data-cas-copy-value',
    'navigator.clipboard.writeText(value)',
    'function sessionIdFromVisibleMetadata(scope) {',
    'function statusHtmlForPane(sessionId, threadId, agentId) {',
    'cas-status-identity-row'
)) {
    if (-not $PaneJsText.Contains($Marker)) { throw "r89 pane runtime invariant missing: $Marker" }
}
foreach ($Forbidden in @(
    'shortPaneId(',
    'sessionId = externalThreadId',
    "sid ' + shortPaneId",
    "tid ' + shortPaneId",
    'position:fixed'
)) {
    if ($PaneJsText.Contains($Forbidden)) { throw "r89 pane runtime contains forbidden r88 behavior: $Forbidden" }
}
Write-Host 'R89_SINGLE_BAR_FULL_ID_CONTRACT_PASS' -ForegroundColor Green
Write-Host 'R89_INLINE_COMPOSER_STATUS_CONTRACT_PASS' -ForegroundColor Green

foreach ($Marker in @(
    'function isNearComposerLiveTail(node) {',
    'function visibleBusyHint(scope) {',
    'function isPureUserTurn(node) {',
    'function activeGenerationUiPresentFor(node) {',
    'function liveTailRootFor(node) {',
    'function liveTailCandidatesForComposer(composer) {',
    'function sweepLiveTailSegments() {',
    'isNearComposerLiveTail(element)',
    'try { sweepLiveTailSegments(); } catch {}',
    'state.timestampBaselineElements = new WeakSet();',
    'first observed live output mutation locally',
    'if (!hasRecentLiveUsage()) return;',
    'sweepOutputSegments(false)'
)) {
    if (-not $ObserverText.Contains($Marker)) { throw "r89 timestamp observer invariant missing: $Marker" }
}
Write-Host 'R89_LIVE_TAIL_TIMESTAMP_CONTRACT_PASS' -ForegroundColor Green

# Truth contract: exact pane snapshots are isolated from native/global Usage,
# pane tok/s never borrows that global number, and unavailable timing is shown
# explicitly rather than guessed from unrelated wall time.
foreach ($Marker in @(
    'R89_TELEMETRY_TRUTH_JS',
    'R89_EXTERNAL_INGEST_BLOCK_START',
    'state.metrics.externalExact = exact;',
    'externalExactFingerprint',
    'CAS-R89-NO-GLOBAL-SPEED-AS-PANE-TPS',
    'function paneTelemetryOwnership(threadId) {',
    'function paneIsLiveForStatus(bar) {',
    'function paneSpeedPresentation(ownership, live) {',
    "text: '-- tok/s'",
    "source: 'timing-unavailable'",
    'native/global tok/s is intentionally not attributed to this pane',
    'data-cas-confidence=',
    'data-cas-pane-live-state='
)) {
    if (-not $TelemetryTruthText.Contains($Marker)) { throw "r89 telemetry-truth invariant missing: $Marker" }
}
foreach ($Forbidden in @(
    'return Number.isFinite(m.nativeSpeed) ? m.nativeSpeed : m.outputSpeed;',
    'estimated average from pane-owned output-token deltas'
)) {
    if ($TelemetryTruthText.Contains($Forbidden)) { throw "r89 telemetry-truth contains forbidden ambiguous-speed behavior: $Forbidden" }
}
Write-Host 'R89_TELEMETRY_TRUTH_CONTRACT_PASS' -ForegroundColor Green

foreach ($Marker in @(
    'R89_PANE_RUNTIME_GENERATION_PATCH_V4',
    'R89_PANE_RUNTIME_PATCH',
    'r89-pane-runtime.js',
    'r89-telemetry-truth.js',
    'r89 canonical pane status mounting',
    'r89 isolate global/native speed from custom pane telemetry',
    'r89 pane-owned exact telemetry presentation',
    'r89 exact external JSONL snapshot ingest',
    'r89 cleanup all legacy and pane status bars',
    "Write-Host 'R89_PANE_RUNTIME_R75_SOURCE_PASS'"
)) {
    if (-not $PanePatchText.Contains($Marker)) { throw "r89 pane patch invariant missing: $Marker" }
}
Write-Host 'R89_PANE_OWNER_LAYER_CONTRACT_PASS' -ForegroundColor Green
Assert-PowerShellParses $PanePatchText 'r89 pane generation include'
Write-Host 'R89_PANE_PATCH_PS_PARSE_PASS' -ForegroundColor Green

try {
    Write-Utf8NoBom $TempObserverCheck ("function __r89ObserverSyntaxOnly(){`n" + $ObserverText + "`n}`n")
    node --check $TempObserverCheck
    if ($LASTEXITCODE -ne 0) { throw 'r89 timestamp observer JavaScript syntax check failed' }
    Write-Host 'R89_TIMESTAMP_OBSERVER_JS_PREFLIGHT_PASS' -ForegroundColor Green

    node --check $R89PaneJs
    if ($LASTEXITCODE -ne 0) { throw 'r89 pane runtime JavaScript syntax check failed' }
    Write-Host 'R89_PANE_RUNTIME_JS_PREFLIGHT_PASS' -ForegroundColor Green

    node --check $R89TelemetryTruthJs
    if ($LASTEXITCODE -ne 0) { throw 'r89 telemetry truth JavaScript syntax check failed' }
    Write-Host 'R89_TELEMETRY_TRUTH_JS_PREFLIGHT_PASS' -ForegroundColor Green

    # The r88 builder already survived Windows full-build validation. Retarget
    # that exact generator instead of reconstructing its nested r87/r86 chain.
    $R89 = $OriginalR88.Replace('r88','r89').Replace('R88','R89').Replace('+88','+89')

    foreach ($Marker in @(
        "`$R89Observer = Join-Path `$PSScriptRoot 'r89-timestamp-observer.js'",
        "`$R89PaneJs = Join-Path `$PSScriptRoot 'r89-pane-runtime.js'",
        "`$R89PanePatch = Join-Path `$PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'",
        'R89_GENERATED_HELPER_ISOLATION_PASS',
        'R89_INNER_HELPER_BINDING_PASS',
        'R89_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS',
        'R89_PANE_RUNTIME_UI_FIX_PASS',
        'visible/package identity is r89 / 2.4.5+89'
    )) {
        if (-not $R89.Contains($Marker)) { throw "r89 retargeted r88 builder invariant missing: $Marker" }
    }

    foreach ($Forbidden in @(
        "Join-Path `$PSScriptRoot 'r88-timestamp-observer.js'",
        "Join-Path `$PSScriptRoot 'r88-pane-runtime.js'",
        "Join-Path `$PSScriptRoot 'r88-r75-pane-runtime-patch-v4.inc.ps1'",
        'visible/package identity is r88 / 2.4.5+88'
    )) {
        if ($R89.Contains($Forbidden)) { throw "r89 retargeted builder retained r88 runtime identity: $Forbidden" }
    }

    Assert-PowerShellParses $R89 'generated r89 wrapper'
    Write-Host 'R89_GENERATED_WRAPPER_PARSE_PASS' -ForegroundColor Green

    Write-Utf8NoBom $TempBuilder $R89
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r89 inherited r88 build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r89 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r89 nested build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R89_RUNTIME_CORRECTNESS_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - one canonical visible editor maps to one composer/status bar'
        Write-Host '  - status bar stays inline in the composer shell directly before the canonical input component'
        Write-Host '  - legacy/orphan and duplicate pane bars are removed before mounting'
        Write-Host '  - full sid/tid/agent values are rendered and click-copyable; no short-id truncation remains'
        Write-Host '  - sid never falls back to thread id; unknown session remains sid --'
        Write-Host '  - pane counts use pane-owned exact local-session JSONL snapshots, isolated from native/global Usage'
        Write-Host '  - pane tok/s never borrows native/global speed; without matched model-response timing it is -- tok/s'
        Write-Host '  - LIVE/IDLE/UNOWNED is explicit so an exact snapshot cannot be mistaken for current activity'
        Write-Host '  - live-tail timestamps accept busy UI, Thinking/Step tail text, or fresh token telemetry'
        Write-Host '  - pure user turns are excluded and live-tail geometry may outrank an older assistant turn'
        Write-Host '  - historical baseline/remount protection and user-message exclusion remain intact'
    } else {
        Write-Host ''
        Write-Host 'R89_RUNTIME_CORRECTNESS_PASS' -ForegroundColor Green
        Write-Host '  - duplicate status-bar regression removed'
        Write-Host '  - status bar remains inline inside the composer shell'
        Write-Host '  - full copyable pane identities exposed'
        Write-Host '  - pane metrics distinguish exact snapshot ownership from live state'
        Write-Host '  - global/native tok/s is never relabeled as pane-local model speed'
        Write-Host '  - live output timestamps restored with pane-tail safety gates'
        Write-Host '  - visible/package identity is r89 / 2.4.5+89'
    }
}
finally {
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TempObserverCheck -Force -ErrorAction SilentlyContinue
    Write-Host '[r89] removed temporary generated wrapper; tracked worktree stays pull-friendly'
}
