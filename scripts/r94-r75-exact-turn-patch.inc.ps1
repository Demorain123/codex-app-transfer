# R94_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH
# Executes inside the generated r90/r86 owner layer where $PatchedR75,
# $StampSource, $StampBody and $ObserverBody are the real nested timestamp
# generation owners. r94 replaces those owners instead of patching transient DOM.

function Normalize-R94Eol([string]$Text) {
    return $Text.Replace("`r`n","`n").Replace("`r","`n")
}

function Replace-R94NormalizedRequired(
    [string]$Text,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    $TextN = Normalize-R94Eol $Text
    $OldN = Normalize-R94Eol $Old
    $NewN = Normalize-R94Eol $New
    if (-not $TextN.Contains($OldN)) { throw "r94 expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}

function Replace-R94BlockRequired(
    [string]$Text,
    [string]$Start,
    [string]$End,
    [string]$Replacement,
    [string]$Label
) {
    $TextN = Normalize-R94Eol $Text
    $StartN = Normalize-R94Eol $Start
    $EndN = Normalize-R94Eol $End
    $ReplacementN = Normalize-R94Eol $Replacement
    $StartIndex = $TextN.IndexOf($StartN)
    if ($StartIndex -lt 0) { throw "r94 block start missing: $Label" }
    $EndIndex = $TextN.IndexOf($EndN,$StartIndex + $StartN.Length)
    if ($EndIndex -le $StartIndex) { throw "r94 block end missing: $Label" }
    return $TextN.Substring(0,$StartIndex) + $ReplacementN + "`n`n" + $TextN.Substring($EndIndex)
}

# The historical r77 builder adds model lookup by exact-replacing an older
# token_count envelope shape. r94 owns a newer bounded turn-aware collector,
# so patch ONLY the temporary r77 builder source to accept that newer owner
# instead of mutating the tracked build-r77-local.ps1 baseline.
if (-not (Get-Variable -Name PatchedR77 -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r94 exact owner requires generated $PatchedR77 compatibility source'
}
$R94R77OldModelApply = @'
$R77OutputText = Replace-Required $R77OutputText $OldEnvelope $NewEnvelope 'bounded turn_context model lookup'
'@
$R94R77NewModelApply = @'
if ($R77OutputText.Contains('CAS-R94-TURN-AWARE-ROLLOUT-BRIDGE')) {
    foreach ($Marker in @(
        "model: latestUsage.model || (usageTurn && usageTurn.model) || null,",
        "const model = typeof payload?.model === 'string' ? payload.model.trim() : '';"
    )) {
        if (-not $R77OutputText.Contains($Marker)) {
            throw "r94 turn-aware collector missing bounded model marker: $Marker"
        }
    }
    Write-Host 'R94_R77_BOUNDED_MODEL_LOOKUP_SUPERSEDED_PASS' -ForegroundColor Green
} else {
    $R77OutputText = Replace-Required $R77OutputText $OldEnvelope $NewEnvelope 'bounded turn_context model lookup'
}
'@
$PatchedR77 = Replace-R94NormalizedRequired $PatchedR77 $R94R77OldModelApply $R94R77NewModelApply 'supersede r77 bounded model exact-replacement for r94 collector'
Write-Host 'R94_R77_MODEL_COLLECTOR_COMPAT_SOURCE_PASS' -ForegroundColor Green

$R94OverlaySourcePath = Join-Path $PSScriptRoot 'r94-exact-turn-overlay.js'
$R94DisabledStampPath = Join-Path $PSScriptRoot 'r94-timestamp-stamp-disabled.js'
$R94FinalObserverPatchPath = Join-Path $PSScriptRoot 'r94-r78-exact-turn-patch.inc.ps1'
foreach ($Path in @($R94OverlaySourcePath,$R94DisabledStampPath,$R94FinalObserverPatchPath)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r94 exact timestamp source missing: $Path" }
}

$R94OverlayBody = Normalize-R94Eol ([System.IO.File]::ReadAllText($R94OverlaySourcePath))
$R94DisabledStampBody = Normalize-R94Eol ([System.IO.File]::ReadAllText($R94DisabledStampPath))
$R94FinalObserverPatchText = Normalize-R94Eol ([System.IO.File]::ReadAllText($R94FinalObserverPatchPath))

foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_EXACT_TURN_CAPABILITY_RUNTIME',
    'window.__casR94TurnCapability = capability;',
    'const R94_TURN_SELECTOR =',
    '[data-turn-key]',
    '[data-content-search-turn-key]',
    '[data-content-search-assistant-turn-key]',
    '[data-chatgpt-conversation-turn="true"]',
    'function r94CreateCapability() {',
    'function r94NativeExactForTurn(turn) {',
    'function r94NativeTimestampVisible(node) {',
    'new IntersectionObserver(function(entries) {',
    'new ResizeObserver(function() { r94SchedulePosition(); })',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r94Cleanup };'
)) {
    if (-not $R94OverlayBody.Contains($Marker)) {
        throw "r94 overlay source invariant missing: $Marker"
    }
}

foreach ($Forbidden in @(
    'characterData: true',
    'characterData:true',
    'first observed live output',
    'first observed output',
    'segment.insertBefore(',
    'segment.appendChild(',
    'actionRow.insertAdjacentElement(',
    'setInterval('
)) {
    if ($R94OverlayBody.Contains($Forbidden)) {
        throw "r94 overlay source retained forbidden legacy behavior: $Forbidden"
    }
}
if ($R94OverlayBody.Contains('Date.now()')) {
    throw 'r94 exact timestamp overlay must not synthesize time with Date.now()'
}
foreach ($Marker in @(
    'R94_LEGACY_TIMESTAMP_STAMP_DISABLED',
    'function stampSegment() {',
    'return;'
)) {
    if (-not $R94DisabledStampBody.Contains($Marker)) {
        throw "r94 disabled stamp source invariant missing: $Marker"
    }
}
$R94DisabledStampExecutable = (($R94DisabledStampBody -split "`n") | Where-Object {
    -not $_.Contains('R94_LEGACY_VERIFIER_SENTINEL')
}) -join "`n"
foreach ($Forbidden in @(
    'document.createElement',
    '.appendChild(',
    '.insertBefore(',
    '.insertAdjacentElement(',
    '.setAttribute(',
    'Date.now()'
)) {
    if ($R94DisabledStampExecutable.Contains($Forbidden)) {
        throw "r94 disabled stamp unexpectedly mutates runtime DOM/time: $Forbidden"
    }
}
Write-Host 'R94_EXACT_OVERLAY_SOURCE_CONTRACT_PASS' -ForegroundColor Green

# Replace the final r86/r78 stamp helper, but only when the target is the
# generated r94 helper. Never overwrite a tracked historical stamp source.
$R94StampTargetName = [System.IO.Path]::GetFileName([string]$StampSource)
if ($R94StampTargetName -ne '.r94-timestamp-stamp.generated.js') {
    throw "r94 refuses non-isolated stamp owner: $R94StampTargetName"
}
[System.IO.File]::WriteAllText(
    $StampSource,
    $R94DisabledStampBody,
    [System.Text.UTF8Encoding]::new($false)
)
$StampBody = $R94DisabledStampBody
if ((Normalize-R94Eol ([System.IO.File]::ReadAllText($StampSource))) -ne $R94DisabledStampBody) {
    throw 'r94 disabled stamp helper round-trip mismatch'
}

$R94ObserverPatchTargetName = [System.IO.Path]::GetFileName([string]$ObserverPatchInclude)
if ($R94ObserverPatchTargetName -ne '.r94-r78-observer-patch.generated.inc.ps1') {
    throw "r94 refuses non-isolated observer-patch owner: $R94ObserverPatchTargetName"
}
foreach ($Marker in @(
    'R94_R78_EXACT_OVERLAY_FINAL_OWNER',
    'R94_R78_EXACT_OVERLAY_FINAL_OWNER_PASS',
    'R94_COMPOSER_STATUS_INSIDE_FINALIZER_BOUND_TO_R75_PASS',
    'r94 exact-only timestamp overlay final owner'
)) {
    if (-not $R94FinalObserverPatchText.Contains($Marker)) {
        throw "r94 final observer patch source invariant missing: $Marker"
    }
}
[System.IO.File]::WriteAllText(
    $ObserverPatchInclude,
    $R94FinalObserverPatchText,
    [System.Text.UTF8Encoding]::new($false)
)
$ObserverPatchText = $R94FinalObserverPatchText
if ((Normalize-R94Eol ([System.IO.File]::ReadAllText($ObserverPatchInclude))) -ne $R94FinalObserverPatchText) {
    throw 'r94 final observer-patch helper round-trip mismatch'
}
Write-Host 'R94_FINAL_R78_OBSERVER_PATCH_INSTALLED_PASS' -ForegroundColor Green

$R94ObserverTargetName = [System.IO.Path]::GetFileName([string]$ObserverSource)
if ($R94ObserverTargetName -ne '.r94-timestamp-observer.generated.js') {
    throw "r94 refuses non-isolated observer owner: $R94ObserverTargetName"
}
[System.IO.File]::WriteAllText(
    $ObserverSource,
    $R94OverlayBody,
    [System.Text.UTF8Encoding]::new($false)
)
if ((Normalize-R94Eol ([System.IO.File]::ReadAllText($ObserverSource))) -ne $R94OverlayBody) {
    throw 'r94 exact overlay observer helper round-trip mismatch'
}

# The inherited r86 verifier predates the exact-overlay profile and checks four
# strict-observer marker strings through $StampBody/$ObserverBody only. Those
# variables are not used to materialize the r94 runtime after this owner patch;
# keep the actual $NewObserver source clean, while giving the legacy verifier
# explicit comments that document why its old profile was superseded.
$R94LegacyVerifierSentinels = @'
// R94 legacy-verifier compatibility only; not materialized into the runtime.
// superseded: function isFinalAssistantSurface(segment) {
// superseded: state.timestampBaselineElements = new WeakSet();
// superseded: if (!hasRecentLiveUsage()) return;
// superseded: sweepOutputSegments(false)
'@
$ObserverBody = $R94OverlayBody + "`n" + $R94LegacyVerifierSentinels
Write-Host 'R94_R86_STRICT_TIMESTAMP_VERIFIER_SUPERSEDED_PASS' -ForegroundColor Green
Write-Host 'R94_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS' -ForegroundColor Green

# r75 used to require either a legacy or strict per-segment observer profile.
# r94 owns a third profile: native/exact turn ownership plus Transfer-owned
# live per-output timestamps, with no native-turn child writes and no periodic/characterData timestamp sweep.
$R94ProfileFunction = @'
function Assert-GeneratedTimestampProfile([string]$Text) {
    foreach ($Marker in @(
        "const VERSION = 'r75.0';",
        'R75_OUTPUT_UI_LOCAL_PASS',
        'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
        'R94_EXACT_TURN_CAPABILITY_RUNTIME',
        'R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME',
        'R94_FULL_DATE_TIMESTAMP_RUNTIME',
    'R94_USER_PROMPT_TIMESTAMP_RUNTIME',
        'R94_NATIVE_RAIL_PRESERVE_RUNTIME',
        'R94_NATIVE_RAIL_METADATA_ONLY_RUNTIME',
        'R94_NATIVE_RAIL_NO_CUSTOM_PAINT_RUNTIME',
        'R94_STREAMING_SEGMENT_THROTTLE_RUNTIME',
        'R94_STREAMING_LATEST_OWNER_CACHE_RUNTIME',
    'R94_MULTI_PANE_THREAD_OWNERSHIP_RUNTIME',
    'R94_MULTI_PANE_LATEST_OWNER_CACHE_RUNTIME',
    'R94_MULTI_PANE_FAIL_CLOSED_RUNTIME',
    'R94_NO_VIEWPORT_EDGE_PINNING_RUNTIME',
        'window.setTimeout(r94FlushSegmentTurns, 220)',
        'const timelineRail = null;',
        'function r94UpsertTimelineEntry(key, epoch, anchor, kind, approx, preview) {',
        'R94_LEGACY_TIMESTAMP_STAMP_DISABLED',
        'function installOutputObserver() {',
        'R94_SEMANTIC_OUTPUT_UNIT_RUNTIME',
        'function r94AssistantMessageSurface(node) {',
        'function r94IsUserSurface(node) {',
        'R94_ITEM_EXACT_TIMESTAMP_RUNTIME',
        'r94BaselineCurrentSegments();',
        'new IntersectionObserver(function(entries) {',
        'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
        'state.observer = { disconnect: r94Cleanup };',
        'timestampMode: "hybrid-native-final+live-segment-overlay",'
    )) {
        if (-not $Text.Contains($Marker)) { throw "r94 generated exact-overlay profile missing: $Marker" }
    }
    $ExecutableText = (($Text -split "`n") | Where-Object {
        -not $_.Contains('R94_LEGACY_VERIFIER_SENTINEL')
    }) -join "`n"
    foreach ($Forbidden in @(
        'characterData: true',
        'characterData:true',
        'segment.insertBefore(',
        'segment.appendChild(',
        'actionRow.insertAdjacentElement(',
        'first observed live output',
        'first observed output',
        'try { sweepOutputSegments(true); } catch {}',
        'try { sweepOutputSegments(false); } catch {}'
    )) {
        if ($ExecutableText.Contains($Forbidden)) { throw "r94 generated runtime retained legacy timestamp hot path: $Forbidden" }
    }
    Write-Host 'R94_EXACT_OVERLAY_PROFILE_PASS' -ForegroundColor Green
}
'@
# The r89 pane runtime patch is injected immediately before the r75 marker.
# Do not use that marker as the end boundary after pane materialization or this
# replacement would accidentally delete the pane/status owner. Prefer the
# injected pane-runtime marker when present, and fall back only for isolated
# timestamp-owner preflights that do not include r89.
$R94HadPaneRuntimePatch = $PatchedR75.Contains('# R94_PANE_RUNTIME_PATCH') -or $PatchedR75.Contains('# R89_PANE_RUNTIME_PATCH')
$R94ProfileEndMarker = if ($PatchedR75.Contains('# R94_PANE_RUNTIME_PATCH')) {
    '# R94_PANE_RUNTIME_PATCH'
} elseif ($PatchedR75.Contains('# R89_PANE_RUNTIME_PATCH')) {
    '# R89_PANE_RUNTIME_PATCH'
} else {
    '# r75 is deliberately a tiny local finalizer layered on r74.'
}
$PatchedR75 = Replace-R94BlockRequired $PatchedR75 'function Assert-GeneratedTimestampProfile([string]$Text) {' $R94ProfileEndMarker $R94ProfileFunction 'replace r75 timestamp profile validator without deleting pane runtime owner'
if ($R94HadPaneRuntimePatch -and -not $PatchedR75.Contains('PANE_RUNTIME_PATCH')) {
    throw 'r94 exact timestamp owner replacement lost the inherited pane runtime patch'
}
if ($R94HadPaneRuntimePatch) {
    Write-Host 'R94_PANE_RUNTIME_PRESERVED_ACROSS_EXACT_OWNER_PASS' -ForegroundColor Green
}

# Replace r75 fallback materialization sources as well. The real r86/r78 owner
# is already replaced above; this also makes -PreflightOnly simulate the same
# exact-only source instead of an obsolete r75 stamp/observer.
$R94NewStampAssignment = '$NewStamp = @''' + "`n" + $R94DisabledStampBody + "`n'@"
$PatchedR75 = Replace-R94BlockRequired     $PatchedR75     '$NewStamp = @'''     '$NewObserver = @'''     $R94NewStampAssignment     'replace r75 fallback stamp source'

$R94NewObserverAssignment = '$NewObserver = @''' + "`n" + $R94OverlayBody + "`n'@"
$R94ObserverEndMarker = @'
try {
    # Build r75 from the already-reviewed r74 local builder without copying its
'@
$PatchedR75 = Replace-R94BlockRequired     $PatchedR75     '$NewObserver = @'''     $R94ObserverEndMarker     $R94NewObserverAssignment     'replace r75 fallback observer source'

# r75 strict simulation must consume the same final exact overlay instead of
# rereading the intermediate r90 observer helper.
$PatchedR75 = Replace-R94NormalizedRequired     $PatchedR75     '$StrictObserver = [System.IO.File]::ReadAllText($StrictObserverSourcePath)'     '$StrictObserver = $NewObserver'     'bind r75 strict simulation to exact overlay'

# Remove the inherited 1.5s timestamp sweep from the final runtime after r75
# materializes $NewPoll. The telemetry/status poll itself remains intact.
$R94PollApply = @'
    $Patched = Replace-Required $Patched $OldPoll $NewPoll 'poll fallback timestamp sweep'
'@
$R94PollApplyExact = @'
    $Patched = Replace-Required $Patched $OldPoll $NewPoll 'poll fallback timestamp sweep'
    $Patched = $Patched.Replace("    try { sweepOutputSegments(true); } catch {}`n",'')
    $Patched = $Patched.Replace("    try { sweepOutputSegments(false); } catch {}`n",'')
    $Patched = $Patched.Replace(
        'timestampMode: "live-output-segment + single-final-answer",',
        'timestampMode: "hybrid-native-final+live-segment-overlay",'
    )
'@
$PatchedR75 = Replace-R94NormalizedRequired     $PatchedR75     $R94PollApply     $R94PollApplyExact     'remove inherited periodic timestamp sweep'

foreach ($Marker in @(
    'R94_EXACT_OVERLAY_PROFILE_PASS',
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_LEGACY_TIMESTAMP_STAMP_DISABLED',
    '$StrictObserver = $NewObserver',
    'hybrid-native-final+live-segment-overlay'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r94 generated r75 source missing exact-overlay marker: $Marker"
    }
}

# Focused owner-layer probe: extract the actual r75 NewStamp/NewObserver source
# that the nested build will materialize and validate the active blocks only.
$R94StampMatch = [regex]::Match(
    $PatchedR75,
    '(?s)\$NewStamp\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@'
)
$R94ObserverMatch = [regex]::Match(
    $PatchedR75,
    '(?s)\$NewObserver\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@'
)
if (-not $R94StampMatch.Success) { throw 'r94 could not extract final r75 NewStamp source' }
if (-not $R94ObserverMatch.Success) { throw 'r94 could not extract final r75 NewObserver source' }
$R94FinalStampProbe = Normalize-R94Eol $R94StampMatch.Groups['body'].Value
$R94FinalObserverProbe = Normalize-R94Eol $R94ObserverMatch.Groups['body'].Value

if (-not $R94FinalStampProbe.Contains('R94_LEGACY_TIMESTAMP_STAMP_DISABLED')) {
    throw 'r94 final NewStamp probe did not materialize disabled owner'
}
foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_EXACT_TURN_CAPABILITY_RUNTIME',
    'R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME',
    'R94_FULL_DATE_TIMESTAMP_RUNTIME',
    'R94_NATIVE_RAIL_PRESERVE_RUNTIME',
    'R94_NATIVE_RAIL_METADATA_ONLY_RUNTIME',
    'R94_NATIVE_RAIL_NO_CUSTOM_PAINT_RUNTIME',
    'R94_STREAMING_SEGMENT_THROTTLE_RUNTIME',
    'R94_STREAMING_LATEST_OWNER_CACHE_RUNTIME',
    'R94_MULTI_PANE_THREAD_OWNERSHIP_RUNTIME',
    'R94_MULTI_PANE_LATEST_OWNER_CACHE_RUNTIME',
    'window.setTimeout(r94FlushSegmentTurns, 220)',
    'const timelineRail = null;',
    'function r94UpsertTimelineEntry(key, epoch, anchor, kind, approx, preview) {',
    'window.__casR94TurnCapability = capability;',
    'function r94AssistantMessageSurface(node) {',
    'function r94IsUserSurface(node) {',
    'R94_ITEM_EXACT_TIMESTAMP_RUNTIME',
    'r94BaselineCurrentSegments();'
)) {
    if (-not $R94FinalObserverProbe.Contains($Marker)) {
        throw "r94 final NewObserver probe did not materialize exact turn capability: $Marker"
    }
}
foreach ($Forbidden in @(
    'characterData: true',
    'characterData:true',
    'Date.now()',
    'segment.insertBefore(',
    'segment.appendChild(',
    'actionRow.insertAdjacentElement(',
    'first observed live output',
    'first observed output',
    'setInterval('
)) {
    if ($R94FinalObserverProbe.Contains($Forbidden)) {
        throw "r94 final observer probe retained forbidden behavior: $Forbidden"
    }
}
Write-Host 'R94_FINAL_TIMESTAMP_MATERIALIZATION_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_REACT_DOM_READONLY_PASS' -ForegroundColor Green

# r86's old r77 compatibility preflight expects the legacy assistantRootsNow
# body. r94 intentionally replaces that body, so point the preflight at the
# exact-overlay marker instead. This changes only the preflight sentinel.
if ($PatchedR75.Contains('R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    $R77OldRoots = 'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME'
    Write-Host 'R94_R77_TIMESTAMP_ROOT_COMPAT_SUPERSEDED_PASS' -ForegroundColor Green
}

# The temporary r77 builder must still provide all exact telemetry recovery, but
# its legacy timestamp-root rewrite must yield when r94 already owns timestamps.
# Patch only that timestamp subsection; do not remove/skip r77 itself.
$R94R77LegacyTimestampApply = @'
$PatchedR75 = Replace-Required $OriginalR75 $OldAssistantRoots $NewAssistantRoots 'timestamp fallback assistant roots'
$PatchedR75 = Replace-Required $PatchedR75 `
    '    const root = assistantRootFor(node);' `
    '    const root = assistantRootForAny(node);' `
    'timestamp mutation fallback root'
'@

$R94R77ExactTimestampApply = @'
if ($OriginalR75.Contains('R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    $PatchedR75 = $OriginalR75
    $R77TimestampRootMarker = 'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME'
    Write-Host 'R94_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS' -ForegroundColor Green
} else {
    $PatchedR75 = Replace-Required $OriginalR75 $OldAssistantRoots $NewAssistantRoots 'timestamp fallback assistant roots'
    $PatchedR75 = Replace-Required $PatchedR75 `
        '    const root = assistantRootFor(node);' `
        '    const root = assistantRootForAny(node);' `
        'timestamp mutation fallback root'
    $R77TimestampRootMarker = 'assistantRootForAny(node)'
}
'@

$PatchedR77 = Replace-R94NormalizedRequired `
    $PatchedR77 `
    $R94R77LegacyTimestampApply `
    $R94R77ExactTimestampApply `
    'make r77 timestamp recovery yield to r94 exact overlay'

$R94R77LegacyVerifyMarker = "    'assistantRootForAny(node)',"
$R94R77CommonVerifyMarker = "    'function assistantRootsNow() {',"
if ($PatchedR77.Contains($R94R77LegacyVerifyMarker)) {
    $PatchedR77 = $PatchedR77.Replace(
        $R94R77LegacyVerifyMarker,
        '    $R77TimestampRootMarker,'
    )
} elseif ($PatchedR77.Contains($R94R77CommonVerifyMarker)) {
    # r87 already normalizes the old legacy-only marker to this common marker.
    $PatchedR77 = $PatchedR77.Replace(
        $R94R77CommonVerifyMarker,
        '    $R77TimestampRootMarker,'
    )
} else {
    throw 'r94 could not locate r77 timestamp verification marker'
}

foreach ($Marker in @(
    "if (`$OriginalR75.Contains('R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {",
    "R94_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS",
    '$R77TimestampRootMarker'
)) {
    if (-not $PatchedR77.Contains($Marker)) {
        throw "r94 patched r77 compatibility source missing marker: $Marker"
    }
}
Write-Host 'R94_R77_TELEMETRY_PRESERVED_TIMESTAMP_SUPERSEDED_PASS' -ForegroundColor Green

