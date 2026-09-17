param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R90Source = Join-Path $PSScriptRoot 'build-r90-local.ps1'
$R89PanePatch = Join-Path $PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'
$TempBuilder = Join-Path $PSScriptRoot '.build-r91-from-r90.generated.ps1'
$TempPanePatch = Join-Path $PSScriptRoot '.r91-r89-pane-runtime-patch.generated.inc.ps1'

foreach ($Path in @($R90Source,$R89PanePatch)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r91 required source missing: $Path" }
}
foreach ($Path in @($TempBuilder,$TempPanePatch)) {
    if (Test-Path -LiteralPath $Path) { throw "r91 refuses pre-existing temp path: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
function Normalize-Eol([string]$Text) {
    return $Text.Replace("`r`n","`n").Replace("`r","`n")
}
function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $TextN = Normalize-Eol $Text
    $OldN = Normalize-Eol $Old
    $NewN = Normalize-Eol $New
    if (-not $TextN.Contains($OldN)) { throw "r91 expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}
function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r91 PowerShell parse failed: $Label :: $Summary"
    }
}

$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r91 git status failed' }
if ($Dirty.Count -gt 0) { throw "r91 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

$Builder = Normalize-Eol ([System.IO.File]::ReadAllText($R90Source))
$PanePatch = Normalize-Eol ([System.IO.File]::ReadAllText($R89PanePatch))

# Keep the already-proven r90 semantic/ownership pipeline, but generate r91
# identity and point its pane owner-layer include at our temporary interaction-
# safe copy. The r89/r90 tracked baselines remain untouched.
$Builder = $Builder.Replace('R90','R91').Replace('r90','r91').Replace('+90','+91')
$OldPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'"
$NewPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot '.r91-r89-pane-runtime-patch.generated.inc.ps1'"
$Builder = Replace-Required $Builder $OldPaneSource $NewPaneSource 'temporary interaction-safe pane include path'

# r90's original helper matching predated the Windows EOL lesson. Make the
# generated r91 wrapper EOL-agnostic before it consumes any source snippets.
$OldReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r91 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
'@
$NewReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedOld = $Old.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedNew = $New.Replace("`r`n","`n").Replace("`r","`n")
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r91 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld,$NormalizedNew)
}
'@
$Builder = Replace-Required $Builder $OldReplaceRequired $NewReplaceRequired 'EOL-safe Replace-Required'

$OldReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $StartIndex = $Text.IndexOf($Start)
    if ($StartIndex -lt 0) { throw "r91 block start missing: $Label" }
    $EndIndex = $Text.IndexOf($End,$StartIndex + $Start.Length)
    if ($EndIndex -le $StartIndex) { throw "r91 block end missing: $Label" }
    return $Text.Substring(0,$StartIndex) + $Replacement + "`n`n" + $Text.Substring($EndIndex)
}
'@
$NewReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedStart = $Start.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedEnd = $End.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedReplacement = $Replacement.Replace("`r`n","`n").Replace("`r","`n")
    $StartIndex = $NormalizedText.IndexOf($NormalizedStart)
    if ($StartIndex -lt 0) { throw "r91 block start missing: $Label" }
    $EndIndex = $NormalizedText.IndexOf($NormalizedEnd,$StartIndex + $NormalizedStart.Length)
    if ($EndIndex -le $StartIndex) { throw "r91 block end missing: $Label" }
    return $NormalizedText.Substring(0,$StartIndex) + $NormalizedReplacement + "`n`n" + $NormalizedText.Substring($EndIndex)
}
'@
$Builder = Replace-Required $Builder $OldReplaceBlock $NewReplaceBlock 'EOL-safe Replace-BlockRequired'

$InteractionPatch = @'

# R91_INTERACTION_SAFE_TIMESTAMP_PATCH
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
'@

$PanePatch = $PanePatch + $InteractionPatch

foreach ($Marker in @(
    'R91_INTERACTION_SAFE_TIMESTAMP_PATCH',
    'function timestampWouldTouchNativeControl(segment) {',
    'r91 interactive timestamp host guard',
    'r91 timestamp badge click-through'
)) {
    if (-not $PanePatch.Contains($Marker)) { throw "r91 pane patch invariant missing: $Marker" }
}
foreach ($Marker in @(
    "visible/package identity is r91 / 2.4.5+91",
    'R91_SEMANTIC_RUNTIME_CORRECTNESS_PASS',
    '.r91-r89-pane-runtime-patch.generated.inc.ps1'
)) {
    if (-not $Builder.Contains($Marker)) { throw "r91 generated builder invariant missing: $Marker" }
}

Assert-PowerShellParses $PanePatch 'interaction-safe pane include'
Assert-PowerShellParses $Builder 'retargeted r91 builder'
Write-Host 'R91_INTERACTION_SAFE_PREFLIGHT_CONTRACT_PASS' -ForegroundColor Green

try {
    Write-Utf8NoBom $TempPanePatch $PanePatch
    Write-Utf8NoBom $TempBuilder $Builder

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r91 delegated build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r91 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r91 delegated build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R91_INTERACTION_SAFE_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - native button/role=button/summary/details/aria-expanded/aria-controls hosts are never structurally stamped'
        Write-Host '  - timestamp badges are click-through and cannot consume native pointer events'
        Write-Host '  - r90 semantic grouping, remount protection, WAITING ownership and truth-first telemetry are inherited'
    } else {
        Write-Host ''
        Write-Host 'R91_INTERACTION_SAFE_RUNTIME_PASS' -ForegroundColor Green
        Write-Host '  - historical expandable rows retain native React child structure and click handling'
        Write-Host '  - unsafe interactive rows fail closed instead of receiving an estimated timestamp'
        Write-Host '  - visible/package identity is r91 / 2.4.5+91'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempPanePatch)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r91] removed generated interaction-safe helpers; r90/r89 baselines remain untouched'
}
