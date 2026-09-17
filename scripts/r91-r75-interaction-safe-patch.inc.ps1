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

# Execute the exact patched r75 source once in -PreflightOnly mode before any
# expensive carry-forward/package build. This closes the previous blind spot
# where the source contained the r91 patch but final $NewStamp materialization
# was not actually exercised until the full build.
$R91R75ProbePath = Join-Path $PSScriptRoot '.r91-r75-materialization-preflight.generated.ps1'
if (Test-Path -LiteralPath $R91R75ProbePath) {
    throw "r91 refuses pre-existing r75 materialization probe: $R91R75ProbePath"
}
try {
    [System.IO.File]::WriteAllText($R91R75ProbePath,$PatchedR75,[System.Text.UTF8Encoding]::new($false))
    $R91ProbeOutput = @(& pwsh -NoProfile -ExecutionPolicy Bypass -File $R91R75ProbePath -PreflightOnly 2>&1)
    $R91ProbeExit = $LASTEXITCODE
    foreach ($Line in $R91ProbeOutput) { Write-Host ([string]$Line) }
    if ($R91ProbeExit -ne 0) {
        throw "r91 final r75 materialization probe failed with exit code $R91ProbeExit"
    }
    $R91ProbeText = ($R91ProbeOutput | ForEach-Object { [string]$_ }) -join "`n"
    if (-not $R91ProbeText.Contains('R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PASS')) {
        throw 'r91 final r75 materialization probe did not execute interaction-safe owner assertion'
    }
    Write-Host 'R91_FINAL_NEWSTAMP_MATERIALIZATION_PREFLIGHT_PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $R91R75ProbePath -Force -ErrorAction SilentlyContinue
}
