param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R90Source = Join-Path $PSScriptRoot 'build-r90-local.ps1'
$R89PanePatch = Join-Path $PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'
$R92ExactOverlayPatch = Join-Path $PSScriptRoot 'r92-r75-exact-overlay-patch.inc.ps1'
$R92OverlayJs = Join-Path $PSScriptRoot 'r92-exact-timestamp-overlay.js'
$R92DisabledStampJs = Join-Path $PSScriptRoot 'r92-timestamp-stamp-disabled.js'

$TempBuilder = Join-Path $PSScriptRoot '.build-r92-from-r90.generated.ps1'
$TempPanePatch = Join-Path $PSScriptRoot '.r92-r89-pane-runtime-patch.generated.inc.ps1'
$TempOverlayCheck = Join-Path $PSScriptRoot '.r92-overlay-syntax.generated.mjs'
$TempStampCheck = Join-Path $PSScriptRoot '.r92-stamp-syntax.generated.mjs'

foreach ($Path in @(
    $R90Source,
    $R89PanePatch,
    $R92ExactOverlayPatch,
    $R92OverlayJs,
    $R92DisabledStampJs
)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r92 required source missing: $Path" }
}
foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
    if (Test-Path -LiteralPath $Path) { throw "r92 refuses pre-existing temp path: $Path" }
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
    if (-not $TextN.Contains($OldN)) { throw "r92 expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r92 PowerShell parse failed: $Label :: $Summary"
    }
}

$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r92 git status failed' }
if ($Dirty.Count -gt 0) { throw "r92 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

$Builder = Normalize-Eol ([System.IO.File]::ReadAllText($R90Source))
$PanePatch = Normalize-Eol ([System.IO.File]::ReadAllText($R89PanePatch))
$ExactOverlayPatch = Normalize-Eol ([System.IO.File]::ReadAllText($R92ExactOverlayPatch))
$OverlayJs = Normalize-Eol ([System.IO.File]::ReadAllText($R92OverlayJs))
$DisabledStampJs = Normalize-Eol ([System.IO.File]::ReadAllText($R92DisabledStampJs))

foreach ($Marker in @(
    'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'function r92CreateCapability() {',
    'function r92NativeExactForTurn(turn) {',
    'new IntersectionObserver(function(entries) {',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r92Cleanup };'
)) {
    if (-not $OverlayJs.Contains($Marker)) { throw "r92 overlay contract missing: $Marker" }
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
    if ($OverlayJs.Contains($Forbidden)) { throw "r92 overlay retained forbidden hot path: $Forbidden" }
}
foreach ($Marker in @(
    'R92_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH',
    'R92_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS',
    'R92_FINAL_TIMESTAMP_MATERIALIZATION_PREFLIGHT_PASS',
    'R92_NATIVE_REACT_DOM_READONLY_PASS'
)) {
    if (-not $ExactOverlayPatch.Contains($Marker)) { throw "r92 owner patch contract missing: $Marker" }
}
if (-not $DisabledStampJs.Contains('R92_LEGACY_TIMESTAMP_STAMP_DISABLED')) {
    throw 'r92 disabled stamp marker missing'
}
Write-Host 'R92_EXACT_OVERLAY_PREFLIGHT_CONTRACT_PASS' -ForegroundColor Green

try {
    Write-Utf8NoBom $TempOverlayCheck ("function __r92OverlaySyntaxOnly(){`n" + $OverlayJs + "`n}`n")
    & node --check $TempOverlayCheck
    if ($LASTEXITCODE -ne 0) { throw 'r92 exact overlay JavaScript syntax check failed' }

    Write-Utf8NoBom $TempStampCheck ("function __r92StampSyntaxOnly(){`n" + $DisabledStampJs + "`n}`n")
    & node --check $TempStampCheck
    if ($LASTEXITCODE -ne 0) { throw 'r92 disabled stamp JavaScript syntax check failed' }
    Write-Host 'R92_EXACT_OVERLAY_JS_SYNTAX_PASS' -ForegroundColor Green

    # Start from the frozen r90 generator so pane ownership/WAITING/truth-first
    # telemetry stay inherited. r92 only replaces the final timestamp owner.
    $Builder = $Builder.Replace('R90','R92').Replace('r90','r92').Replace('+90','+92')

    $OldPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'"
    $NewPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot '.r92-r89-pane-runtime-patch.generated.inc.ps1'"
    $Builder = Replace-Required $Builder $OldPaneSource $NewPaneSource 'temporary exact-overlay pane include path'

    # The frozen r90 source predates our strict EOL discipline. Normalize its
    # generated replacement helpers so the exact owner patch is Windows-safe.
    $OldReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r92 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
'@
    $NewReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedOld = $Old.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedNew = $New.Replace("`r`n","`n").Replace("`r","`n")
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r92 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld,$NormalizedNew)
}
'@
    $Builder = Replace-Required $Builder $OldReplaceRequired $NewReplaceRequired 'EOL-safe generated Replace-Required'

    $OldReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $StartIndex = $Text.IndexOf($Start)
    if ($StartIndex -lt 0) { throw "r92 block start missing: $Label" }
    $EndIndex = $Text.IndexOf($End,$StartIndex + $Start.Length)
    if ($EndIndex -le $StartIndex) { throw "r92 block end missing: $Label" }
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
    if ($StartIndex -lt 0) { throw "r92 block start missing: $Label" }
    $EndIndex = $NormalizedText.IndexOf($NormalizedEnd,$StartIndex + $NormalizedStart.Length)
    if ($EndIndex -le $StartIndex) { throw "r92 block end missing: $Label" }
    return $NormalizedText.Substring(0,$StartIndex) + $NormalizedReplacement + "`n`n" + $NormalizedText.Substring($EndIndex)
}
'@
    $Builder = Replace-Required $Builder $OldReplaceBlock $NewReplaceBlock 'EOL-safe generated Replace-BlockRequired'

    # Keep the stable pane/status owner patch, then replace only the timestamp
    # generation owner at that same nested layer.
    $PanePatch = $PanePatch + "`n`n" + $ExactOverlayPatch

    foreach ($Marker in @(
        "`$TempObserver = Join-Path `$PSScriptRoot 'r92-timestamp-observer.js'",
        "`$TempPaneJs = Join-Path `$PSScriptRoot 'r92-pane-runtime.js'",
        "`$TempTruthJs = Join-Path `$PSScriptRoot 'r92-telemetry-truth.js'",
        'R92_SEMANTIC_RUNTIME_CORRECTNESS_PASS',
        'visible/package identity is r92 / 2.4.5+92',
        '.r92-r89-pane-runtime-patch.generated.inc.ps1'
    )) {
        if (-not $Builder.Contains($Marker)) { throw "r92 retargeted builder invariant missing: $Marker" }
    }

    foreach ($Marker in @(
        'R89_PANE_RUNTIME_GENERATION_PATCH_V4',
        'R92_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH',
        'R92_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS'
    )) {
        if (-not $PanePatch.Contains($Marker)) { throw "r92 generated pane include missing marker: $Marker" }
    }

    Assert-PowerShellParses $ExactOverlayPatch 'r92 exact timestamp owner patch'
    Assert-PowerShellParses $PanePatch 'r92 generated pane include'
    Assert-PowerShellParses $Builder 'r92 retargeted r90 builder'
    Write-Host 'R92_GENERATED_POWERSHELL_PARSE_PASS' -ForegroundColor Green

    Write-Utf8NoBom $TempPanePatch $PanePatch
    Write-Utf8NoBom $TempBuilder $Builder

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }

    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r92 delegated build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r92 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r92 delegated build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R92_EXACT_TIMESTAMP_OVERLAY_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - r90 pane ownership / WAITING / truth-first telemetry remains inherited'
        Write-Host '  - legacy per-segment timestamp stamping is disabled at the final r86/r78 owner'
        Write-Host '  - final timestamps are exact-only and sourced from Codex native sent-time metadata in this first r92 cut'
        Write-Host '  - native Codex turn/action-row DOM is read-only; labels live in a Transfer-owned overlay root'
        Write-Host '  - mutation observation is childList-only; visible-turn work is IntersectionObserver bounded'
        Write-Host '  - no Date.now historical estimate, characterData stream observer, or periodic timestamp sweep survives'
    } else {
        Write-Host ''
        Write-Host 'R92_EXACT_TIMESTAMP_OVERLAY_RUNTIME_PASS' -ForegroundColor Green
        Write-Host '  - exact one-per-turn timestamp overlay is installed without native turn child mutation'
        Write-Host '  - legacy r74-r90 stamp path is inert'
        Write-Host '  - visible/package identity is r92 / 2.4.5+92'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r92] removed generated exact-overlay helpers; r90/r89 tracked baselines remain untouched'
}
