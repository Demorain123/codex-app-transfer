# R91_INTERACTION_SAFE_TIMESTAMP_PATCH
# This include executes in the outer generated r86/r89 pane-patch layer where
# $PatchedR75 exists. It must NOT touch $Original directly: $Original is owned
# by the generated r75 builder and only exists when that inner builder runs.
# Inject the real interaction-safety patch into that r75 owner layer instead.

$R91R75InjectionPoint = '# r75 is deliberately a tiny local finalizer layered on r74.'
if (-not $PatchedR75.Contains($R91R75InjectionPoint)) {
    throw 'r91 could not locate r75 interaction-safe injection point'
}

$R91R75RuntimePatch = @'
# R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PATCH
# Never insert timestamp DOM into native clickable/collapsible controls. Doing
# so can perturb React-managed children and interfere with expanding historical
# tool/progress rows. Exact/estimated timestamps fail closed on unsafe hosts.
$R91InteractiveGuardOld = @"
  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
"@

$R91InteractiveGuardNew = @"
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
"@

$Original = Replace-Required $Original $R91InteractiveGuardOld $R91InteractiveGuardNew 'r91 interactive timestamp host guard'
$Original = Replace-Required $Original 'white-space:nowrap;pointer-events:auto;user-select:text;opacity:.72;' 'white-space:nowrap;pointer-events:none;user-select:none;opacity:.72;' 'r91 timestamp badge click-through'

foreach ($Marker in @(
    'function timestampWouldTouchNativeControl(segment) {',
    'if (timestampWouldTouchNativeControl(segment)) return;',
    'pointer-events:none;user-select:none;opacity:.72;'
)) {
    if (-not $Original.Contains($Marker)) { throw "r91 interaction-safe runtime invariant missing: $Marker" }
}
Write-Host 'R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PASS' -ForegroundColor Green
'@

$PatchedR75 = $PatchedR75.Replace(
    $R91R75InjectionPoint,
    $R91R75RuntimePatch + "`r`n`r`n" + $R91R75InjectionPoint
)

foreach ($Marker in @(
    'R91_INTERACTION_SAFE_TIMESTAMP_OWNER_PATCH',
    'function timestampWouldTouchNativeControl(segment) {',
    'r91 interactive timestamp host guard',
    'r91 timestamp badge click-through'
)) {
    if (-not $PatchedR75.Contains($Marker)) {
        throw "r91 generated r75 interaction-safe source missing marker: $Marker"
    }
}
Write-Host 'R91_INTERACTION_SAFE_R75_SOURCE_PASS' -ForegroundColor Green
