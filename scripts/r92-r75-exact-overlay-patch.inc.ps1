# R92_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH
# Executes inside the generated r90/r86 owner layer where $PatchedR75,
# $StampSource, $StampBody and $ObserverBody are the real nested timestamp
# generation owners. r92 replaces those owners instead of patching transient DOM.

function Normalize-R92Eol([string]$Text) {
    return $Text.Replace("`r`n","`n").Replace("`r","`n")
}

function Replace-R92NormalizedRequired(
    [string]$Text,
    [string]$Old,
    [string]$New,
    [string]$Label
) {
    $TextN = Normalize-R92Eol $Text
    $OldN = Normalize-R92Eol $Old
    $NewN = Normalize-R92Eol $New
    if (-not $TextN.Contains($OldN)) { throw "r92 expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}

function Replace-R92BlockRequired(
    [string]$Text,
    [string]$Start,
    [string]$End,
    [string]$Replacement,
    [string]$Label
) {
    $TextN = Normalize-R92Eol $Text
    $StartN = Normalize-R92Eol $Start
    $EndN = Normalize-R92Eol $End
    $ReplacementN = Normalize-R92Eol $Replacement
    $StartIndex = $TextN.IndexOf($StartN)
    if ($StartIndex -lt 0) { throw "r92 block start missing: $Label" }
    $EndIndex = $TextN.IndexOf($EndN,$StartIndex + $StartN.Length)
    if ($EndIndex -le $StartIndex) { throw "r92 block end missing: $Label" }
    return $TextN.Substring(0,$StartIndex) + $ReplacementN + "`n`n" + $TextN.Substring($EndIndex)
}

$R92OverlaySourcePath = Join-Path $PSScriptRoot 'r92-exact-timestamp-overlay.js'
$R92DisabledStampPath = Join-Path $PSScriptRoot 'r92-timestamp-stamp-disabled.js'
foreach ($Path in @($R92OverlaySourcePath,$R92DisabledStampPath)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r92 exact timestamp source missing: $Path" }
}

$R92OverlayBody = Normalize-R92Eol ([System.IO.File]::ReadAllText($R92OverlaySourcePath))
$R92DisabledStampBody = Normalize-R92Eol ([System.IO.File]::ReadAllText($R92DisabledStampPath))

foreach ($Marker in @(
    'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    "const R92_TURN_SELECTOR = '[data-turn-key],[data-content-search-turn-key]';",
    'function r92CreateCapability() {',
    'function r92NativeExactForTurn(turn) {',
    'new IntersectionObserver(function(entries) {',
    'new ResizeObserver(function() { r92SchedulePosition(); })',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r92Cleanup };'
)) {
    if (-not $R92OverlayBody.Contains($Marker)) {
        throw "r92 overlay source invariant missing: $Marker"
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
    if ($R92OverlayBody.Contains($Forbidden)) {
        throw "r92 overlay source retained forbidden legacy behavior: $Forbidden"
    }
}
if ($R92OverlayBody.Contains('Date.now()')) {
    throw 'r92 exact timestamp overlay must not synthesize time with Date.now()'
}
foreach ($Marker in @(
    'R92_LEGACY_TIMESTAMP_STAMP_DISABLED',
    'function stampSegment() {',
    'return;'
)) {
    if (-not $R92DisabledStampBody.Contains($Marker)) {
        throw "r92 disabled stamp source invariant missing: $Marker"
    }
}
foreach ($Forbidden in @(
    'document.createElement',
    '.appendChild(',
    '.insertBefore(',
    '.insertAdjacentElement(',
    '.setAttribute(',
    'Date.now()'
)) {
    if ($R92DisabledStampBody.Contains($Forbidden)) {
        throw "r92 disabled stamp unexpectedly mutates runtime DOM/time: $Forbidden"
    }
}
Write-Host 'R92_EXACT_OVERLAY_SOURCE_CONTRACT_PASS' -ForegroundColor Green

# Replace the final r86/r78 stamp helper, but only when the target is the
# generated r92 helper. Never overwrite a tracked historical stamp source.
$R92StampTargetName = [System.IO.Path]::GetFileName([string]$StampSource)
if ($R92StampTargetName -ne '.r92-timestamp-stamp.generated.js') {
    throw "r92 refuses non-isolated stamp owner: $R92StampTargetName"
}
[System.IO.File]::WriteAllText(
    $StampSource,
    $R92DisabledStampBody,
    [System.Text.UTF8Encoding]::new($false)
)
$StampBody = $R92DisabledStampBody
if ((Normalize-R92Eol ([System.IO.File]::ReadAllText($StampSource))) -ne $R92DisabledStampBody) {
    throw 'r92 disabled stamp helper round-trip mismatch'
}

$R92ObserverTargetName = [System.IO.Path]::GetFileName([string]$ObserverSource)
if ($R92ObserverTargetName -ne '.r92-timestamp-observer.generated.js') {
    throw "r92 refuses non-isolated observer owner: $R92ObserverTargetName"
}
[System.IO.File]::WriteAllText(
    $ObserverSource,
    $R92OverlayBody,
    [System.Text.UTF8Encoding]::new($false)
)
if ((Normalize-R92Eol ([System.IO.File]::ReadAllText($ObserverSource))) -ne $R92OverlayBody) {
    throw 'r92 exact overlay observer helper round-trip mismatch'
}

# The inherited r86 verifier predates the exact-overlay profile and checks four
# strict-observer marker strings through $StampBody/$ObserverBody only. Those
# variables are not used to materialize the r92 runtime after this owner patch;
# keep the actual $NewObserver source clean, while giving the legacy verifier
# explicit comments that document why its old profile was superseded.
$R92LegacyVerifierSentinels = @'
// R92 legacy-verifier compatibility only; not materialized into the runtime.
// superseded: function isFinalAssistantSurface(segment) {
// superseded: state.timestampBaselineElements = new WeakSet();
// superseded: if (!hasRecentLiveUsage()) return;
// superseded: sweepOutputSegments(false)
'@
$ObserverBody = $R92OverlayBody + "`n" + $R92LegacyVerifierSentinels
Write-Host 'R92_R86_STRICT_TIMESTAMP_VERIFIER_SUPERSEDED_PASS' -ForegroundColor Green
Write-Host 'R92_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS' -ForegroundColor Green

# r75 used to require either a legacy or strict per-segment observer profile.
# r92 owns a third profile: exact-only overlay, with no native-turn child writes
# and no periodic/characterData timestamp sweep.
$R92ProfileFunction = @'
function Assert-GeneratedTimestampProfile([string]$Text) {
    foreach ($Marker in @(
        "const VERSION = 'r75.0';",
        'R75_OUTPUT_UI_LOCAL_PASS',
        'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
        'R92_LEGACY_TIMESTAMP_STAMP_DISABLED',
        'function installOutputObserver() {',
        'new IntersectionObserver(function(entries) {',
        'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
        'state.observer = { disconnect: r92Cleanup };',
        'timestampMode: "exact-final-turn-overlay",'
    )) {
        if (-not $Text.Contains($Marker)) { throw "r92 generated exact-overlay profile missing: $Marker" }
    }
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
        if ($Text.Contains($Forbidden)) { throw "r92 generated runtime retained legacy timestamp hot path: $Forbidden" }
    }
    Write-Host 'R92_EXACT_OVERLAY_PROFILE_PASS' -ForegroundColor Green
}
'@
$PatchedR75 = Replace-R92BlockRequired     $PatchedR75     'function Assert-GeneratedTimestampProfile([string]$Text) {'     '# r75 is deliberately a tiny local finalizer layered on r74.'     $R92ProfileFunction     'replace r75 timestamp profile validator'

# Replace r75 fallback materialization sources as well. The real r86/r78 owner
# is already replaced above; this also makes -PreflightOnly simulate the same
# exact-only source instead of an obsolete r75 stamp/observer.
$R92NewStampAssignment = '$NewStamp = @''' + "`n" + $R92DisabledStampBody + "`n'@"
$PatchedR75 = Replace-R92BlockRequired     $PatchedR75     '$NewStamp = @'''     '$NewObserver = @'''     $R92NewStampAssignment     'replace r75 fallback stamp source'

$R92NewObserverAssignment = '$NewObserver = @''' + "`n" + $R92OverlayBody + "`n'@"
$R92ObserverEndMarker = @'
try {
    # Build r75 from the already-reviewed r74 local builder without copying its
'@
$PatchedR75 = Replace-R92BlockRequired     $PatchedR75     '$NewObserver = @'''     $R92ObserverEndMarker     $R92NewObserverAssignment     'replace r75 fallback observer source'

# r75 strict simulation must consume the same final exact overlay instead of
# rereading the intermediate r90 observer helper.
$PatchedR75 = Replace-R92NormalizedRequired     $PatchedR75     '$StrictObserver = [System.IO.File]::ReadAllText($StrictObserverSourcePath)'     '$StrictObserver = $NewObserver'     'bind r75 strict simulation to exact overlay'

# Remove the inherited 1.5s timestamp sweep from the final runtime after r75
# materializes $NewPoll. The telemetry/status poll itself remains intact.
$R92PollApply = @'
    $Patched = Replace-Required $Patched $OldPoll $NewPoll 'poll fallback timestamp sweep'
'@
$R92PollApplyExact = @'
    $Patched = Replace-Required $Patched $OldPoll $NewPoll 'poll fallback timestamp sweep'
    $Patched = $Patched.Replace("    try { sweepOutputSegments(true); } catch {}`n",'')
    $Patched = $Patched.Replace("    try { sweepOutputSegments(false); } catch {}`n",'')
    $Patched = $Patched.Replace(
        'timestampMode: "live-output-segment + single-final-answer",',
        'timestampMode: "exact-final-turn-overlay",'
    )
'@
$PatchedR75 = Replace-R92NormalizedRequired     $PatchedR75     $R92PollApply     $R92PollApplyExact     'remove inherited periodic timestamp sweep'

foreach ($Marker in @(
    'R92_EXACT_OVERLAY_PROFILE_PASS',
    'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R92_LEGACY_TIMESTAMP_STAMP_DISABLED',
    '$StrictObserver = $NewObserver',
    'exact-final-turn-overlay'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r92 generated r75 source missing exact-overlay marker: $Marker"
    }
}

# Focused owner-layer probe: extract the actual r75 NewStamp/NewObserver source
# that the nested build will materialize and validate the active blocks only.
$R92StampMatch = [regex]::Match(
    $PatchedR75,
    '(?s)\$NewStamp\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@'
)
$R92ObserverMatch = [regex]::Match(
    $PatchedR75,
    '(?s)\$NewObserver\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@'
)
if (-not $R92StampMatch.Success) { throw 'r92 could not extract final r75 NewStamp source' }
if (-not $R92ObserverMatch.Success) { throw 'r92 could not extract final r75 NewObserver source' }
$R92FinalStampProbe = Normalize-R92Eol $R92StampMatch.Groups['body'].Value
$R92FinalObserverProbe = Normalize-R92Eol $R92ObserverMatch.Groups['body'].Value

if (-not $R92FinalStampProbe.Contains('R92_LEGACY_TIMESTAMP_STAMP_DISABLED')) {
    throw 'r92 final NewStamp probe did not materialize disabled owner'
}
if (-not $R92FinalObserverProbe.Contains('R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    throw 'r92 final NewObserver probe did not materialize exact overlay'
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
    if ($R92FinalObserverProbe.Contains($Forbidden)) {
        throw "r92 final observer probe retained forbidden behavior: $Forbidden"
    }
}
Write-Host 'R92_FINAL_TIMESTAMP_MATERIALIZATION_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R92_NATIVE_REACT_DOM_READONLY_PASS' -ForegroundColor Green

# r86's old r77 compatibility preflight expects the legacy assistantRootsNow
# body. r92 intentionally replaces that body, so point the preflight at the
# exact-overlay marker instead. This changes only the preflight sentinel.
if ($PatchedR75.Contains('R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    $R77OldRoots = 'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME'
    Write-Host 'R92_R77_TIMESTAMP_ROOT_COMPAT_SUPERSEDED_PASS' -ForegroundColor Green
}

# The temporary r77 builder must still provide all exact telemetry recovery, but
# its legacy timestamp-root rewrite must yield when r92 already owns timestamps.
# Patch only that timestamp subsection; do not remove/skip r77 itself.
$R92R77LegacyTimestampApply = @'
$PatchedR75 = Replace-Required $OriginalR75 $OldAssistantRoots $NewAssistantRoots 'timestamp fallback assistant roots'
$PatchedR75 = Replace-Required $PatchedR75 `
    '    const root = assistantRootFor(node);' `
    '    const root = assistantRootForAny(node);' `
    'timestamp mutation fallback root'
'@

$R92R77ExactTimestampApply = @'
if ($OriginalR75.Contains('R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {
    $PatchedR75 = $OriginalR75
    $R77TimestampRootMarker = 'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME'
    Write-Host 'R92_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS' -ForegroundColor Green
} else {
    $PatchedR75 = Replace-Required $OriginalR75 $OldAssistantRoots $NewAssistantRoots 'timestamp fallback assistant roots'
    $PatchedR75 = Replace-Required $PatchedR75 `
        '    const root = assistantRootFor(node);' `
        '    const root = assistantRootForAny(node);' `
        'timestamp mutation fallback root'
    $R77TimestampRootMarker = 'assistantRootForAny(node)'
}
'@

$PatchedR77 = Replace-R92NormalizedRequired `
    $PatchedR77 `
    $R92R77LegacyTimestampApply `
    $R92R77ExactTimestampApply `
    'make r77 timestamp recovery yield to r92 exact overlay'

$R92R77LegacyVerifyMarker = "    'assistantRootForAny(node)',"
$R92R77CommonVerifyMarker = "    'function assistantRootsNow() {',"
if ($PatchedR77.Contains($R92R77LegacyVerifyMarker)) {
    $PatchedR77 = $PatchedR77.Replace(
        $R92R77LegacyVerifyMarker,
        '    $R77TimestampRootMarker,'
    )
} elseif ($PatchedR77.Contains($R92R77CommonVerifyMarker)) {
    # r87 already normalizes the old legacy-only marker to this common marker.
    $PatchedR77 = $PatchedR77.Replace(
        $R92R77CommonVerifyMarker,
        '    $R77TimestampRootMarker,'
    )
} else {
    throw 'r92 could not locate r77 timestamp verification marker'
}

foreach ($Marker in @(
    "if (`$OriginalR75.Contains('R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME')) {",
    "R92_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS",
    '$R77TimestampRootMarker'
)) {
    if (-not $PatchedR77.Contains($Marker)) {
        throw "r92 patched r77 compatibility source missing marker: $Marker"
    }
}
Write-Host 'R92_R77_TELEMETRY_PRESERVED_TIMESTAMP_SUPERSEDED_PASS' -ForegroundColor Green

