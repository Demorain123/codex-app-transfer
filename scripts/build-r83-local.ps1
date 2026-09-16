param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Selective = Join-Path $PSScriptRoot 'apply_r43_r65_selective_modern.py'
$R76Output = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$R76Local = Join-Path $PSScriptRoot 'build-r76-local.ps1'
$R77Builder = Join-Path $PSScriptRoot 'build-r77-local.ps1'
$R78Builder = Join-Path $PSScriptRoot 'build-r78-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$TempR83Builder = Join-Path $PSScriptRoot '.build-r83-from-r78.generated.ps1'

foreach ($Path in @($Selective,$R76Output,$R76Local,$R77Builder,$R78Builder,$R75Builder)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r83 required file missing: $Path" }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'r83 requires python on PATH' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'r83 requires git on PATH' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'r83 requires node on PATH' }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR76Output = [System.IO.File]::ReadAllText($R76Output)
$OriginalR76Local = [System.IO.File]::ReadAllText($R76Local)
$OriginalR77 = [System.IO.File]::ReadAllText($R77Builder)
$OriginalR78 = [System.IO.File]::ReadAllText($R78Builder)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)

function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r83 preflight expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}

function Replace-BlockRequired([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Replacement,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r83 preflight block start missing: $Label" }
    $End = $Text.IndexOf($EndMarker,$Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r83 preflight block end missing: $Label" }
    return $Text.Substring(0,$Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

function Assert-Contains([string]$Text,[string]$Needle,[string]$Label) {
    if (-not $Text.Contains($Needle)) { throw "r83 preflight invariant missing: $Label" }
}

function Assert-NotContains([string]$Text,[string]$Needle,[string]$Label) {
    if ($Text.Contains($Needle)) { throw "r83 preflight forbidden text present: $Label" }
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r83 preflight PowerShell parse failed: $Label :: $Summary"
    }
}

# ---------------------------------------------------------------------------
# PRE-BUILD STATIC PIPELINE PREFLIGHT
# ---------------------------------------------------------------------------
# This phase runs before r43-r65 materialization. Exact-string drift therefore
# fails in seconds, instead of after the expensive carry-forward chain.

# Patch the real collector source layer. r77 reads this r76 file and generates
# the target-version output builder from it.
$PatchedR76Output = Replace-Required $OriginalR76Output `
    "        if (url && !url.startsWith('app://')) continue;" `
    "        if (url && /^(devtools:|chrome-extension:|chrome:)/i.test(url)) continue;" `
    'r76 collector renderer eligibility'

$OldSafeEnvelope = @'
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
    };
'@
$NewSafeEnvelope = @'
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      model: typeof envelope.model === 'string' ? envelope.model : null,
      info: envelope.info,
    };
'@
$PatchedR76Output = Replace-Required $PatchedR76Output $OldSafeEnvelope $NewSafeEnvelope 'r76 collector safe model envelope'

# r78 contains the reviewed timestamp-v4/action-row layer. Its historical
# r77->r78 conversion changed only selected version strings, which leaves inner
# generated path literals at r77. For r83, replace that conversion block with a
# complete r77->r83 retarget so variables, generated filenames, expected paths,
# PASS markers and diagnostics all agree on one target version.
$R83CoreBlock = @'
$PatchedR77 = $OriginalR77.Replace('r77', 'r83').Replace('R77', 'R83').Replace('+77', '+83')
foreach ($Marker in @(
    'build-r83-output-ui-local.ps1',
    '.build-r83-output.generated.ps1',
    'R83_EXACT_TOKEN_TELEMETRY_PASS',
    'R83_LOCAL_ENTRYPOINT_PASS',
    'state.ingestExternalUsage = ingestExternalUsage;',
    'data-above-composer-conversation-id'
)) {
    if (-not $PatchedR77.Contains($Marker)) { throw "r83 retargeted r77 source verification failed: $Marker" }
}
'@

$R83BuilderText = Replace-BlockRequired `
    $OriginalR78 `
    '$PatchedR77 = $OriginalR77' `
    'try {' `
    $R83CoreBlock `
    'replace r78 selective r77 retarget block'
$R83BuilderText = $R83BuilderText.Replace('r78','r83').Replace('R78','R83').Replace('+78','+83')

# Simulate the entire r77 source retarget, including generated path literals.
$SimulatedR83Core = $OriginalR77.Replace('r77','r83').Replace('R77','R83').Replace('+77','+83')
foreach ($Check in @(
    @("`$R83OutputText = `$OriginalR76Output.Replace('r76', 'r83').Replace('R76', 'R83').Replace('+76', '+83')",'r83 output identity source'),
    @("`$R83EntryText = `$OriginalR76Local.Replace('r76', 'r83').Replace('R76', 'R83').Replace('+76', '+83')",'r83 entry identity source'),
    @('build-r83-output-ui-local.ps1','r83 generated output source path'),
    @('.build-r83-output.generated.ps1','r83 generated output temp path'),
    @('R83_EXACT_TOKEN_TELEMETRY_PASS','r83 exact telemetry marker'),
    @('R83_LOCAL_ENTRYPOINT_PASS','r83 entry marker'),
    @('state.ingestExternalUsage = ingestExternalUsage;','r83 external usage bridge'),
    @('data-above-composer-conversation-id','r83 active-thread resolver')
)) {
    Assert-Contains $SimulatedR83Core $Check[0] $Check[1]
}

# Simulate the generated r83 entrypoint's collision-avoidance path rewrite too.
$SimulatedR83Entry = $OriginalR76Local.Replace('r76','r83').Replace('R76','R83').Replace('+76','+83')
$SimulatedR83Entry = Replace-Required $SimulatedR83Entry `
    "`$Source = Join-Path `$PSScriptRoot 'build-r83-output-ui-local.ps1'" `
    "`$Source = Join-Path `$PSScriptRoot '.build-r83-output.generated.ps1'" `
    'r83 generated entry output source path'

# Validate every exact r76/r75 needle consumed by the retargeted core.
foreach ($Check in @(
    @('state.metrics.externalUpdatedAt = Number(envelope.updatedAt) || Date.now();','r76 ingest tail'),
    @('const activeThreadExpression = "(() => {" +','r76 active-thread expression'),
    @('if (!info || !info.last_token_usage || !info.total_token_usage) continue;','r76 last/total usage gate'),
    @('CAS-R76-EXACT-TOKEN-TELEMETRY','r76 exact telemetry marker'),
    @("if (url && /^(devtools:|chrome-extension:|chrome:)/i.test(url)) continue;",'r83 patched renderer eligibility'),
    @("model: typeof envelope.model === 'string' ? envelope.model : null,",'r83 patched safe model envelope')
)) {
    Assert-Contains $PatchedR76Output $Check[0] $Check[1]
}

foreach ($Check in @(
    @("`$NewStamp = @'",'r75 stamp block'),
    @("`$NewObserver = @'",'r75 observer block'),
    @('function assistantRootsNow() {','r75 assistant root block'),
    @('const native = nativeTime(segment) || nativeTime(root);','r75 native-time source line')
)) {
    Assert-Contains $OriginalR75 $Check[0] $Check[1]
}

foreach ($Check in @(
    @('R83_TIMESTAMP_ACTIONROW_V4_PASS','r83 timestamp action-row marker'),
    @('data-cas-timestamp-confidence','r83 timestamp confidence metadata'),
    @("actionRow.insertAdjacentElement('afterend', badge);",'r83 action-row timestamp placement'),
    @('const native = nativeTimeForSegment(segment, root);','r83 segment-native-time isolation')
)) {
    Assert-Contains $R83BuilderText $Check[0] $Check[1]
}

# Parse every generated PowerShell layer with the real PowerShell parser before
# materialization. This catches quoting/here-string/version-retarget syntax bugs
# on the user's actual pwsh runtime without touching tracked source.
Assert-PowerShellParses $PatchedR76Output 'patched r76 collector builder'
Assert-PowerShellParses $SimulatedR83Core 'retargeted r83 core builder'
Assert-PowerShellParses $SimulatedR83Entry 'generated r83 entry builder'
Assert-PowerShellParses $R83BuilderText 'generated r83 timestamp wrapper'

# Guard against the two already-observed nested-wrapper failure modes.
Assert-NotContains $R83BuilderText 'do not reject valid Codex renderers solely because URL is not app://' 'old r80 source-layer label'
Assert-NotContains $R83BuilderText 'r82 generated output and entry identity' 'old r82 nested identity label'

$SelectiveText = [System.IO.File]::ReadAllText($Selective)
if ([regex]::IsMatch($SelectiveText, 'run\(\s*["'']scripts/apply_r\d+_unified\.py')) {
    throw 'r83 selective materializer must not execute historical recursive apply_rXX_unified.py drivers'
}

Write-Host 'R83_STATIC_PIPELINE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - exact telemetry patch is applied at the real r76 collector source layer'
Write-Host '  - r78 timestamp-v4 is retained without the incomplete historical r77->r78 path retarget'
Write-Host '  - the complete nested r77 builder was simulated as r83, including generated file paths'
Write-Host '  - generated r76/r83 PowerShell layers parse successfully before carry-forward starts'
Write-Host '  - historical recursive r24-r41 unified drivers remain excluded'

if ($PreflightOnly) {
    Write-Host 'R83_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    exit 0
}

$TrackedBefore = @(& git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r83 git status preflight failed' }
if ($TrackedBefore.Count -gt 0) {
    throw "r83 requires a clean tracked worktree. Use the dedicated build worktree.`n$($TrackedBefore -join "`n")"
}

try {
    Write-Host '[r83 1/4] Selectively materializing r43-r65 onto the current r70+ tree...' -ForegroundColor Cyan
    & python $Selective
    if ($LASTEXITCODE -ne 0) { throw "r83 selective materializer failed with exit code $LASTEXITCODE" }

    Write-Host '[r83 2/4] Verifying carry-forward changed runtime state without touching the r70 repair...' -ForegroundColor Cyan
    $ChangedAfterCarry = @(& git -C $RepoRoot diff --name-only --diff-filter=ACMRTUXB)
    if ($LASTEXITCODE -ne 0) { throw 'r83 could not enumerate carry-forward changes' }
    if ($ChangedAfterCarry.Count -eq 0) { throw 'r83 carry-forward produced no tracked runtime changes' }
    Write-Host ("  carry-forward tracked paths: {0}" -f $ChangedAfterCarry.Count)

    [System.IO.File]::WriteAllText($R76Output,$PatchedR76Output,$Utf8NoBom)
    [System.IO.File]::WriteAllText($TempR83Builder,$R83BuilderText,$Utf8NoBom)

    Write-Host '[r83 3/4] Building r83 exact telemetry + per-output timestamps + carry-forward package...' -ForegroundColor Cyan
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR83Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r83 package build failed with exit code $LASTEXITCODE" }

    Write-Host 'R83_EXACT_TELEMETRY_TARGETING_PASS' -ForegroundColor Green
    Write-Host '  - renderer eligibility is active-thread-DOM gated, not app:// gated'
    Write-Host '  - bounded turn_context model survives the renderer-safe envelope'

    Write-Host '[r83 4/4] Package completed; tracked source restoration will run in finally.' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'R83_LOCAL_BUILD_PASS' -ForegroundColor Green
    Write-Host 'R83_R43_R65_CARRY_FORWARD_PACKAGE_PASS' -ForegroundColor Green
    Write-Host '  - r43-r65 selective carry-forward retained'
    Write-Host '  - r66-r69 Hook A/B experiments remain excluded'
    Write-Host '  - r70 masked-history repair remains hash-protected by the selective materializer'
    Write-Host '  - r78 action-row timestamps and exact local JSONL usage telemetry are included'
    Write-Host '  - visible/package identity is r83 / 2.4.5+83'
}
finally {
    Remove-Item -LiteralPath $TempR83Builder -Force -ErrorAction SilentlyContinue
    & git -C $RepoRoot restore --source=HEAD --staged --worktree -- . 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'r83 could not fully restore tracked sources; inspect git status before another build.'
    }
    $After = @(& git -C $RepoRoot status --porcelain --untracked-files=no 2>$null)
    if ($After.Count -eq 0) {
        Write-Host '[r83] tracked worktree restored clean; generated package artifacts are retained.'
    } else {
        Write-Warning ("r83 tracked worktree is not clean after restore:`n" + ($After -join "`n"))
    }
}
