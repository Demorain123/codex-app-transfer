# R91_INTERACTION_SAFE_TIMESTAMP_PATCH
# Executes inside the generated r91/r89 pane owner-layer include after the
# existing r89/r90 runtime wiring has patched $Original.
#
# Never insert timestamp DOM into native clickable/collapsible controls. Doing
# so can perturb React-managed children and interfere with expanding historical
# tool/progress rows. Exact/estimated timestamps fail closed on unsafe hosts.

$R91InteractiveGuardOld = @'
  function stampSegment(segment, root, epoch, source) {
    if (!(segment instanceof Element) || insideComposer(segment) || insideOwnUi(segment)) return;
'@

$R91InteractiveGuardNew = @'
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
