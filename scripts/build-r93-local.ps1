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
$R92FinalObserverPatch = Join-Path $PSScriptRoot 'r92-r78-exact-overlay-patch.inc.ps1'
$R92OverlayJs = Join-Path $PSScriptRoot 'r92-exact-timestamp-overlay.js'
$R92DisabledStampJs = Join-Path $PSScriptRoot 'r92-timestamp-stamp-disabled.js'
$R93StatusFinalizer = Join-Path $PSScriptRoot 'r93-status-finalizer.ps1'

$TempBuilder = Join-Path $PSScriptRoot '.build-r93-from-r90.generated.ps1'
$TempPanePatch = Join-Path $PSScriptRoot '.r93-r89-pane-runtime-patch.generated.inc.ps1'
$TempOverlayCheck = Join-Path $PSScriptRoot '.r93-overlay-syntax.generated.mjs'
$TempStampCheck = Join-Path $PSScriptRoot '.r93-stamp-syntax.generated.mjs'

foreach ($Path in @(
    $R90Source,
    $R89PanePatch,
    $R92ExactOverlayPatch,
    $R92FinalObserverPatch,
    $R92OverlayJs,
    $R92DisabledStampJs,
    $R93StatusFinalizer
)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r93 required source missing: $Path" }
}
foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
    if (Test-Path -LiteralPath $Path) { throw "r93 refuses pre-existing temp path: $Path" }
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
$FinalObserverPatch = Normalize-Eol ([System.IO.File]::ReadAllText($R92FinalObserverPatch))
$OverlayJs = Normalize-Eol ([System.IO.File]::ReadAllText($R92OverlayJs))
$DisabledStampJs = Normalize-Eol ([System.IO.File]::ReadAllText($R92DisabledStampJs))
$StatusFinalizer = Normalize-Eol ([System.IO.File]::ReadAllText($R93StatusFinalizer))

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
    'R92_R86_STRICT_TIMESTAMP_VERIFIER_SUPERSEDED_PASS',
    'R92_FINAL_R78_OBSERVER_PATCH_INSTALLED_PASS',
    'R92_R78_EXACT_OVERLAY_FINAL_OWNER_PASS',
    'R92_R77_TIMESTAMP_ROOT_COMPAT_SUPERSEDED_PASS',
    'R92_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS',
    'R92_R77_TELEMETRY_PRESERVED_TIMESTAMP_SUPERSEDED_PASS',
    "'.r92-timestamp-observer.generated.js'",
    'R92_FINAL_TIMESTAMP_MATERIALIZATION_PREFLIGHT_PASS',
    'R92_NATIVE_REACT_DOM_READONLY_PASS'
)) {
    if (-not $ExactOverlayPatch.Contains($Marker)) { throw "r92 owner patch contract missing: $Marker" }
}
if (-not $DisabledStampJs.Contains('R92_LEGACY_TIMESTAMP_STAMP_DISABLED')) {
    throw 'r92 disabled stamp marker missing'
}
foreach ($Marker in @(
    'R92_R78_EXACT_OVERLAY_FINAL_OWNER',
    'R92_R78_EXACT_OVERLAY_FINAL_OWNER_PASS',
    'r92 exact-only timestamp overlay final owner'
)) {
    if (-not $FinalObserverPatch.Contains($Marker)) { throw "r92 final observer patch contract missing: $Marker" }
}
Assert-PowerShellParses $FinalObserverPatch 'r92 final r78 observer patch include'
Write-Host 'R92_FINAL_R78_OBSERVER_PATCH_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R92_EXACT_OVERLAY_PREFLIGHT_CONTRACT_PASS' -ForegroundColor Green
foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_FINALIZER',
    'R93_COMPOSER_STATUS_FINAL_OWNER_PASS',
    'R93_NATIVE_USAGE_ISOLATION_PASS',
    'R93_STATUS_RENDER_FINGERPRINT_PASS'
)) {
    if (-not $StatusFinalizer.Contains($Marker)) { throw "r93 status finalizer contract missing: $Marker" }
}
Assert-PowerShellParses $StatusFinalizer 'r93 status finalizer'
Write-Host 'R93_STATUS_FINALIZER_PREFLIGHT_PASS' -ForegroundColor Green


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
    $Builder = $Builder.Replace('R90','R93').Replace('r90','r93').Replace('+90','+93')

    $OldPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'"
    $NewPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot '.r93-r89-pane-runtime-patch.generated.inc.ps1'"
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
        "`$TempObserver = Join-Path `$PSScriptRoot 'r93-timestamp-observer.js'",
        "`$TempPaneJs = Join-Path `$PSScriptRoot 'r93-pane-runtime.js'",
        "`$TempTruthJs = Join-Path `$PSScriptRoot 'r93-telemetry-truth.js'",
        'R93_SEMANTIC_RUNTIME_CORRECTNESS_PASS',
        'visible/package identity is r93 / 2.4.5+93',
        '.r93-r89-pane-runtime-patch.generated.inc.ps1'
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
    if ($LASTEXITCODE -ne 0) { throw "r93 delegated build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r92 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r93 delegated build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R93_COMPOSER_STATUS_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - r90 pane ownership / WAITING / truth-first telemetry remains inherited'
        Write-Host '  - legacy per-segment timestamp stamping is disabled at the final r86/r78 owner'
        Write-Host '  - final timestamps are exact-only and sourced from Codex native sent-time metadata in this first r92 cut'
        Write-Host '  - native Codex turn/action-row DOM is read-only; labels live in a Transfer-owned overlay root'
        Write-Host '  - mutation observation is childList-only; visible-turn work is IntersectionObserver bounded'
        Write-Host '  - no Date.now historical estimate, characterData stream observer, or periodic timestamp sweep survives'
        Write-Host '  - status bar mounts inside the composer surface and skips unchanged DOM rewrites'
        Write-Host '  - native/global Usage polling cannot overwrite pane/local status counters or tok/s'
    } else {
        Write-Host ''
        Write-Host 'R93_COMPOSER_STATUS_RUNTIME_PASS' -ForegroundColor Green
        Write-Host '  - exact one-per-turn timestamp overlay is installed without native turn child mutation'
        Write-Host '  - legacy r74-r90 stamp path is inert'
        Write-Host '  - composer status is integrated inside the native input surface and native/global speed is isolated'
        Write-Host '  - visible/package identity is r93 / 2.4.5+93'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r93] removed generated helpers; r92/r90/r89 tracked baselines remain untouched'
}
