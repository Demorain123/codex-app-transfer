# R91_INTERACTION_SAFE_TIMESTAMP_PATCH
# This include executes in the outer generated r86/r89 pane-patch layer where
# $PatchedR75 is the actual r75 builder source. r75 later replaces stampSegment
# wholesale from its $NewStamp here-string, so interaction safety must patch
# that source-of-truth rather than transient $Original/r74 content.

function Replace-R91NormalizedRequired([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $TextN = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $OldN = $Old.Replace("`r`n","`n").Replace("`r","`n")
    $NewN = $New.Replace("`r`n","`n").Replace("`r","`n")
    if (-not $TextN.Contains($OldN)) { throw "r91 normalized expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}

$R91NewStampOld = @'
  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
'@

$R91NewStampNew = @'
  function timestampWouldTouchNativeControl(segment) {
    if (!(segment instanceof Element)) return false;
    const interactive = 'button,[role="button"],a[href],summary,details,[aria-expanded],[aria-controls]';
    if (segment.matches(interactive)) return true;
    if (segment.closest(interactive)) return true;
    try {
      if (segment.querySelector(':scope > button,:scope > [role="button"],:scope > a[href],:scope > summary,:scope > details,:scope > [aria-expanded],:scope > [aria-controls]')) return true;
    } catch {}
    return false;
  }

  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
    if (timestampWouldTouchNativeControl(segment)) return;
'@

$PatchedR75 = Replace-R91NormalizedRequired $PatchedR75 $R91NewStampOld $R91NewStampNew 'r91 r75 NewStamp interaction guard'

$R91BadgeCssOld = 'white-space:nowrap;pointer-events:auto;user-select:text;opacity:.72;'
$R91BadgeCssNew = 'white-space:nowrap;pointer-events:none;user-select:none;opacity:.72;'
if ($PatchedR75.Contains($R91BadgeCssOld)) {
    $PatchedR75 = $PatchedR75.Replace($R91BadgeCssOld,$R91BadgeCssNew)
} elseif (-not $PatchedR75.Contains($R91BadgeCssNew)) {
    throw 'r91 r75 NewStamp badge pointer-event source missing'
}

# Insert a post-materialization assertion immediately after r75 applies $NewStamp
# to its generated builder. This runs in BOTH -PreflightOnly and full build, so
# the short preflight now proves the exact final stampSegment source that the
# package build will consume.
$R91StampApplyLine = @'
    $Patched = Replace-BlockRequired $Patched '  function stampSegment(segment, root, epoch, source) {' '  function baselineExistingDom() {' $NewStamp 'visible in-flow timestamp rail'
'@

$R91StampApplyVerified = @'
    $Patched = Replace-BlockRequired $Patched '  function stampSegment(segment, root, epoch, source) {' '  function baselineExistingDom() {' $NewStamp 'visible in-flow timestamp rail'
    foreach ($Marker in @(
        'function timestampWouldTouchNativeControl(segment) {',
        'if (timestampWouldTouchNativeControl(segment)) return;',
        'pointer-events:none;user-select:none;opacity:.72;'
    )) {
        if (-not $Patched.Contains($Marker)) {
            throw "r91 final r75 timestamp materialization invariant missing: $Marker"
        }
    }
    Write-Host 'R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PASS' -ForegroundColor Green
'@

$PatchedR75 = Replace-R91NormalizedRequired $PatchedR75 $R91StampApplyLine $R91StampApplyVerified 'r91 final r75 materialization assertion'

foreach ($Marker in @(
    'function timestampWouldTouchNativeControl(segment) {',
    'if (timestampWouldTouchNativeControl(segment)) return;',
    'pointer-events:none;user-select:none;opacity:.72;',
    'R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PASS'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r91 generated r75 interaction-safe source missing marker: $Marker"
    }
}
Write-Host 'R91_INTERACTION_SAFE_R75_SOURCE_PASS' -ForegroundColor Green

# Probe ONLY the final $NewStamp source. Do not execute the whole patched r75
# builder here: its r89/r91 pane-runtime patches intentionally depend on later
# r76 owner-layer content and cannot be validated in isolation.
$R91NewStampMatch = [regex]::Match(
    $PatchedR75,
    '(?s)\$NewStamp\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@'
)
if (-not $R91NewStampMatch.Success) {
    throw 'r91 could not extract final NewStamp source for materialization probe'
}
$R91FinalNewStamp = $R91NewStampMatch.Groups['body'].Value.Replace("`r`n","`n").Replace("`r","`n")

foreach ($Marker in @(
    'function timestampWouldTouchNativeControl(segment) {',
    'if (timestampWouldTouchNativeControl(segment)) return;',
    'pointer-events:none;user-select:none;opacity:.72;'
)) {
    if (-not $R91FinalNewStamp.Contains($Marker)) {
        throw "r91 final NewStamp source invariant missing: $Marker"
    }
}

# Simulate the exact r75 block materialization against a minimal owner-layer
# fixture. This exercises the same start/end markers without invoking unrelated
# telemetry/provider generation layers.
$R91ProbeBase = @'
  function stampSegment(segment, root, epoch, source) {
    legacyStamp();
  }

  function baselineExistingDom() {
    legacyBaseline();
  }
'@
$R91ProbeBase = $R91ProbeBase.Replace("`r`n","`n").Replace("`r","`n")
$R91ProbeStartMarker = '  function stampSegment(segment, root, epoch, source) {'
$R91ProbeEndMarker = '  function baselineExistingDom() {'
$R91ProbeStart = $R91ProbeBase.IndexOf($R91ProbeStartMarker)
$R91ProbeEnd = $R91ProbeBase.IndexOf($R91ProbeEndMarker,$R91ProbeStart + $R91ProbeStartMarker.Length)
if ($R91ProbeStart -lt 0 -or $R91ProbeEnd -le $R91ProbeStart) {
    throw 'r91 minimal NewStamp probe fixture is invalid'
}
$R91Materialized = $R91ProbeBase.Substring(0,$R91ProbeStart) + $R91FinalNewStamp + "`n`n" + $R91ProbeBase.Substring($R91ProbeEnd)

foreach ($Marker in @(
    'function timestampWouldTouchNativeControl(segment) {',
    'if (timestampWouldTouchNativeControl(segment)) return;',
    'pointer-events:none;user-select:none;opacity:.72;',
    'function baselineExistingDom() {'
)) {
    if (-not $R91Materialized.Contains($Marker)) {
        throw "r91 final NewStamp materialization invariant missing: $Marker"
    }
}

Write-Host 'R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PASS' -ForegroundColor Green
Write-Host 'R91_FINAL_NEWSTAMP_MATERIALIZATION_PREFLIGHT_PASS' -ForegroundColor Green
