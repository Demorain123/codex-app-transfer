param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R83Builder = Join-Path $PSScriptRoot 'build-r83-local.ps1'
$R85Builder = Join-Path $PSScriptRoot 'build-r85-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$StampSource = Join-Path $PSScriptRoot 'r86-timestamp-stamp.js'
$ObserverSource = Join-Path $PSScriptRoot 'r86-timestamp-observer.js'
$TempR86Builder = Join-Path $PSScriptRoot '.build-r86-from-r83.generated.ps1'

foreach ($Path in @($R83Builder,$R85Builder,$R75Builder,$StampSource,$ObserverSource)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r86 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR83 = [System.IO.File]::ReadAllText($R83Builder)
$OriginalR85 = [System.IO.File]::ReadAllText($R85Builder)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)
$StampBody = [System.IO.File]::ReadAllText($StampSource)
$ObserverBody = [System.IO.File]::ReadAllText($ObserverSource)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r86 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}

function Replace-BlockRequired([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Replacement,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r86 block start missing: $Label" }
    $End = $Text.IndexOf($EndMarker,$Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r86 block end missing: $Label" }
    return $Text.Substring(0,$Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

function Insert-AfterRequired([string]$Text,[string]$Needle,[string]$Insertion,[string]$Label) {
    $Index = $Text.IndexOf($Needle)
    if ($Index -lt 0) { throw "r86 insertion point missing: $Label" }
    $End = $Index + $Needle.Length
    return $Text.Substring(0,$End) + $Insertion + $Text.Substring($End)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r86 PowerShell parse failed: $Label :: $Summary"
    }
}

# ---------------------------------------------------------------------------
# 1) Reuse r85's reviewed prose grouping, then tighten ownership so user/native
# metadata never becomes an assistant-output timestamp surface.
# ---------------------------------------------------------------------------
$SegMatch = [regex]::Match(
    $OriginalR85,
    '(?s)\$SegmentationBody\s*=\s*@''\r?\n(?<body>.*?)\r?\n''@\r?\n\$NewSegmentation\s*='
)
if (-not $SegMatch.Success) { throw 'r86 could not extract r85 segmentation body' }
$SegmentationBody = $SegMatch.Groups['body'].Value

$SemanticNeedle = @'
  function isSemanticOutputSurface(node) {
    return isStrongSemanticOutputSurface(node);
  }
'@
$SemanticExtra = @'

  function isUserAuthoredSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-message-author-role="user"],[data-message-author="user"]')) return true;
    const directUser = node.closest('[data-message-author-role="user"],[data-message-author="user"]');
    if (directUser) return true;
    const userDesc = node.querySelector('[data-message-author-role="user"],[data-message-author="user"]');
    const assistantDesc = node.querySelector('[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[data-content-search-assistant-turn-key]');
    return !!userDesc && !assistantDesc;
  }

  function isNativeMetadataSurface(node) {
    if (!(node instanceof Element)) return false;
    return node.matches('[data-assistant-message-sent-time],time[datetime]');
  }
'@
$SegmentationBody = Replace-Required $SegmentationBody $SemanticNeedle ($SemanticNeedle + $SemanticExtra) 'user/native ownership helpers'
$SegmentationBody = Replace-Required $SegmentationBody `
    "    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node)) return [];" `
    "    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node) || isUserAuthoredSurface(node) || isNativeMetadataSurface(node)) return [];" `
    'segmentation root guard'
$SegmentationBody = Replace-Required $SegmentationBody `
    "      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate)) continue;" `
    "      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate) || isUserAuthoredSurface(candidate) || isNativeMetadataSurface(candidate)) continue;" `
    'candidate ownership guard'
$SegmentationBody = Replace-Required $SegmentationBody `
    "    if (!element || insideComposer(element) || insideOwnUi(element)) return null;" `
    "    if (!element || insideComposer(element) || insideOwnUi(element) || isUserAuthoredSurface(element)) return null;" `
    'mutation ownership guard'

$BeforeVerticalSplit = @'
    // Horizontal icon/label/action rows stay atomic.
    if (verticalRowCount(children) < 2) return [node];
'@
$SemanticGrouping = @'
    // A semantic tool/agent/status row plus its expanded prose is one event.
    const semanticChildren = children.filter(function(child) { return isStrongSemanticOutputSurface(child); });
    if (semanticChildren.length === 1) {
      const rest = children.filter(function(child) { return child !== semanticChildren[0]; });
      if (rest.length && rest.every(function(child) { return isPureProseSubtree(child, 0); }) && maxVerticalGap(children) <= 48) {
        return [node];
      }
    }

    // Horizontal icon/label/action rows stay atomic.
    if (verticalRowCount(children) < 2) return [node];
'@
$SegmentationBody = Replace-Required $SegmentationBody $BeforeVerticalSplit $SemanticGrouping 'semantic row + expanded detail grouping'

$NewSegmentation = '$NewSegmentation = @''' + "`r`n" + $SegmentationBody + "`r`n'@"
$PatchedR75 = Replace-BlockRequired `
    $OriginalR75 `
    '$NewSegmentation = @''' `
    '$NewStamp = @''' `
    $NewSegmentation `
    'install r86 segmentation into r75 source'

# ---------------------------------------------------------------------------
# 2) Start from the already preflighted r83 package/carry-forward chain. Patch
# the generated r78 timestamp layer itself, because r78 owns/overwrites stamp
# logic after r75 is loaded. This avoids the broken r85->r84 insertion point and
# ensures the strict stamp/observer actually survives to the packaged runtime.
# ---------------------------------------------------------------------------
$R86Core = $OriginalR83.Replace('r83','r86').Replace('R83','R86').Replace('+83','+86')
$StampB64 = [Convert]::ToBase64String($Utf8NoBom.GetBytes($StampBody))
$ObserverB64 = [Convert]::ToBase64String($Utf8NoBom.GetBytes($ObserverBody))

$GeneratedR78PatchTemplate = @'

# R86_TIMESTAMP_R78_GENERATION_PATCH
$R86StampBody = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__STAMP_B64__'))
$StampStart = $R86BuilderText.IndexOf('$NewStampBody = @''')
$StampEnd = if ($StampStart -ge 0) { $R86BuilderText.IndexOf('$NewStamp = ', $StampStart) } else { -1 }
if ($StampStart -lt 0 -or $StampEnd -le $StampStart) { throw 'r86 could not locate generated r78 stamp body' }
$StampAssignment = '$NewStampBody = @''' + "`r`n" + $R86StampBody + "`r`n'@`r`n"
$R86BuilderText = $R86BuilderText.Substring(0,$StampStart) + $StampAssignment + $R86BuilderText.Substring($StampEnd)

$LeakLabelIndex = $R86BuilderText.IndexOf('do not leak final reply native time into progress segments')
$ObserverPatchStart = if ($LeakLabelIndex -ge 0) { $R86BuilderText.LastIndexOf('$PatchedR75 = Replace-Required',$LeakLabelIndex) } else { -1 }
$ObserverPatchEnd = if ($LeakLabelIndex -ge 0) { $R86BuilderText.IndexOf('foreach ($Marker in @(',$LeakLabelIndex) } else { -1 }
if ($ObserverPatchStart -lt 0 -or $ObserverPatchEnd -le $ObserverPatchStart) { throw 'r86 could not locate generated r78 observer patch block' }
$ObserverPatchCode = @'
$R86ObserverBody = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__OBSERVER_B64__'))
$R86ObserverWrapped = '$NewObserver = @''' + "`r`n" + $R86ObserverBody + "`r`n'@"
$R86ObserverReplacement = $R86ObserverWrapped + "`r`n`r`ntry {`r`n"
$PatchedR75 = Replace-BlockRequired $PatchedR75 '$NewObserver = @''' '    # Build r75 from the already-reviewed r74 local builder without copying its' $R86ObserverReplacement 'r86 live-only timestamp observer'
$PatchedR75 = $PatchedR75.Replace('try { sweepOutputSegments(true); } catch {}','try { sweepOutputSegments(false); } catch {}')
'@
$R86BuilderText = $R86BuilderText.Substring(0,$ObserverPatchStart) + $ObserverPatchCode + "`r`n`r`n" + $R86BuilderText.Substring($ObserverPatchEnd)

foreach ($Marker in @(
    'function isFinalAssistantSurface(segment) {',
    'r86 live-only timestamp observer',
    'data-cas-timestamp-confidence',
    'R86_TIMESTAMP_ACTIONROW_V4_PASS'
)) {
    if (-not $R86BuilderText.Contains($Marker)) { throw "r86 generated r78 timestamp patch verification failed: $Marker" }
}
'@
$GeneratedR78Patch = $GeneratedR78PatchTemplate.Replace('__STAMP_B64__',$StampB64).Replace('__OBSERVER_B64__',$ObserverB64)

$R78RetargetNeedle = '$R86BuilderText = $R86BuilderText.Replace(''r78'',''r86'').Replace(''R78'',''R86'').Replace(''+78'',''+86'')'
$R86Core = Insert-AfterRequired $R86Core $R78RetargetNeedle $GeneratedR78Patch 'patch generated r78 timestamp layer'

# Install the r86 segmentation source only after r83/r86's clean-worktree gate.
$PatchedR75Bytes = $Utf8NoBom.GetBytes($PatchedR75)
$PatchedR75B64 = [Convert]::ToBase64String($PatchedR75Bytes)
$Sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $PatchedR75Sha256 = ([BitConverter]::ToString($Sha.ComputeHash($PatchedR75Bytes))).Replace('-','').ToLowerInvariant()
} finally {
    $Sha.Dispose()
}

$InstallNeedle = @'
try {
    Write-Host '[r86 1/4] Selectively materializing r43-r65 onto the current r70+ tree...' -ForegroundColor Cyan
'@
$InstallBlock = @'
try {
    $R86TimestampSourceBase64 = '__R86_TIMESTAMP_BASE64__'
    $R86TimestampSourceText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($R86TimestampSourceBase64))
    [System.IO.File]::WriteAllText($R75Builder,$R86TimestampSourceText,[System.Text.UTF8Encoding]::new($false))
    $R86TimestampSourceHash = (Get-FileHash -LiteralPath $R75Builder -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($R86TimestampSourceHash -ne '__R86_TIMESTAMP_SHA256__') {
        throw "r86 temporary timestamp source hash mismatch: $R86TimestampSourceHash"
    }
    Write-Host 'R86_TEMP_TIMESTAMP_SOURCE_INSTALLED' -ForegroundColor Green
    Write-Host '[r86 1/4] Selectively materializing r43-r65 onto the current r70+ tree...' -ForegroundColor Cyan
'@
$InstallBlock = $InstallBlock.Replace('__R86_TIMESTAMP_BASE64__',$PatchedR75B64).Replace('__R86_TIMESTAMP_SHA256__',$PatchedR75Sha256)
$R86Core = Replace-Required $R86Core $InstallNeedle $InstallBlock 'install r86 segmentation after clean-worktree gate'

foreach ($Marker in @(
    'R86_TIMESTAMP_R78_GENERATION_PATCH',
    'R86_TEMP_TIMESTAMP_SOURCE_INSTALLED',
    'R86_STATIC_PIPELINE_PREFLIGHT_PASS',
    'R86_EXACT_TOKEN_TELEMETRY_PASS',
    'R86_R43_R65_CARRY_FORWARD_PACKAGE_PASS',
    'visible/package identity is r86 / 2.4.5+86'
)) {
    if (-not $R86Core.Contains($Marker)) { throw "r86 generated core verification failed: $Marker" }
}
foreach ($Marker in @(
    'function isUserAuthoredSurface(node) {',
    'function shouldKeepAsProseGroup(node, children) {',
    'semantic tool/agent/status row plus its expanded prose is one event'
)) {
    if (-not $PatchedR75.Contains($Marker)) { throw "r86 segmentation verification failed: $Marker" }
}
foreach ($Marker in @(
    'function isFinalAssistantSurface(segment) {',
    'state.timestampBaselineElements = new WeakSet();',
    'if (!hasRecentLiveUsage()) return;',
    'sweepOutputSegments(false)'
)) {
    if (-not (($StampBody + "`n" + $ObserverBody).Contains($Marker))) { throw "r86 strict timestamp source verification failed: $Marker" }
}

Assert-PowerShellParses $PatchedR75 'r86 patched r75 timestamp source'
Assert-PowerShellParses $R86Core 'r86 generated r83 package wrapper'

Write-Host 'R86_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - r85 prose grouping is reused without the broken r85->r84 insertion assumption'
Write-Host '  - user-authored bubbles/native metadata are excluded from timestamp surfaces'
Write-Host '  - strict stamp/observer patches are applied at the r78 generation layer that actually owns them'
Write-Host '  - generic assistant wrappers are identity only, not automatically final replies'
Write-Host '  - historical baseline/remount DOM never receives Date.now()'
Write-Host '  - periodic/scheduled sweeps are exact-only'
Write-Host '  - stale r74-r85 structural timestamp cache is cleared at runtime'
Write-Host '  - telemetry/provider/r43-r65 carry-forward remain inherited from r83'

try {
    Write-Utf8NoBom $TempR86Builder $R86Core
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR86Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r86 nested builder failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R86_WRAPPER_PREFLIGHT_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R86_TIMESTAMP_CORRECTNESS_PASS' -ForegroundColor Green
        Write-Host '  - false current-time stamps on historical/remounted output are suppressed'
        Write-Host '  - user-message timestamp contamination is blocked'
        Write-Host '  - broad turn-root sent-time inheritance is blocked'
        Write-Host '  - semantic row + expanded detail stays one timestamp event'
    }
}
finally {
    Remove-Item -LiteralPath $TempR86Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r86] removed temporary generated wrapper; tracked worktree stays pull-friendly'
}
