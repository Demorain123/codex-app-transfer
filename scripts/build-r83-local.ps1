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

function Assert-Contains([string]$Text,[string]$Needle,[string]$Label) {
    if (-not $Text.Contains($Needle)) { throw "r83 preflight invariant missing: $Label" }
}

function Assert-NotContains([string]$Text,[string]$Needle,[string]$Label) {
    if ($Text.Contains($Needle)) { throw "r83 preflight forbidden text present: $Label" }
}

# ---------------------------------------------------------------------------
# PRE-BUILD STATIC PIPELINE PREFLIGHT
# ---------------------------------------------------------------------------
# Do this BEFORE replaying r43-r65 so exact-string drift in the observability
# builder chain fails immediately, rather than after several minutes of work.

# Patch the actual r76 collector source layer. r77/r78 generate from this file;
# patching build-r77 itself was the source-layer mistake that broke r82.
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

# r78 is the last known-good composition layer for timestamp/action-row logic.
# Generate r83 directly from r78; do not wrap r80/r82 and do not rewrite an
# already-generated builder. This keeps source/target roles unambiguous.
$R83BuilderText = $OriginalR78.Replace('r78','r83').Replace('R78','R83').Replace('+78','+83')

# Validate the exact inner needles that the generated r83 script will consume.
foreach ($Check in @(
    @("`$R77OutputText = `$OriginalR76Output.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')",'r77 output identity source'),
    @("`$R77EntryText = `$OriginalR76Local.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')",'r77 entry identity source'),
    @("Replace('r75', 'r77')",'r77 timestamp identity source'),
    @('R77_EXACT_TOKEN_TELEMETRY_PASS','r77 exact telemetry marker'),
    @('R77_LOCAL_ENTRYPOINT_PASS','r77 entry marker'),
    @('state.ingestExternalUsage = ingestExternalUsage;','r77 external usage bridge'),
    @('data-above-composer-conversation-id','r77 active-thread resolver')
)) {
    Assert-Contains $OriginalR77 $Check[0] $Check[1]
}

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
    @("Replace('r76', 'r83').Replace('R76', 'R83').Replace('+76', '+83')",'r83 output/entry identity'),
    @("Replace('r75', 'r83')",'r83 timestamp identity'),
    @('R83_EXACT_TOKEN_TELEMETRY_PASS','r83 exact telemetry marker'),
    @('R83_LOCAL_ENTRYPOINT_PASS','r83 entrypoint marker'),
    @('R83_TIMESTAMP_ACTIONROW_V4_PASS','r83 timestamp action-row marker')
)) {
    Assert-Contains $R83BuilderText $Check[0] $Check[1]
}

# Guard against repeating the r82 design bug: r83 must not depend on build-r80
# nor contain the failed nested label from that wrapper.
Assert-NotContains $R83BuilderText 'do not reject valid Codex renderers solely because URL is not app://' 'r80 nested source-layer label'
Assert-NotContains $R83BuilderText 'r82 generated output and entry identity' 'r82 nested identity label'

# The selective carry-forward driver must remain non-recursive.
$SelectiveText = [System.IO.File]::ReadAllText($Selective)
if ([regex]::IsMatch($SelectiveText, 'run\(\s*["'']scripts/apply_r\d+_unified\.py')) {
    throw 'r83 selective materializer must not execute historical recursive apply_rXX_unified.py drivers'
}

Write-Host 'R83_STATIC_PIPELINE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - package chain resolved directly as r78 -> r83'
Write-Host '  - exact telemetry patch targets the real r76 collector source layer'
Write-Host '  - every known r77/r76/r75 exact-string dependency is present before materialization'
Write-Host '  - failed r80/r82 nested-builder labels are absent'
Write-Host '  - r43-r65 selective driver contains no recursive unified-driver execution'

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

    # Only after the materialization gate succeeds, place the preflighted
    # observability sources into the working tree for the package build.
    [System.IO.File]::WriteAllText($R76Output,$PatchedR76Output,$Utf8NoBom)
    [System.IO.File]::WriteAllText($TempR83Builder,$R83BuilderText,$Utf8NoBom)

    Write-Host '[r83 3/4] Building r83 exact telemetry + per-output timestamps + carry-forward package...' -ForegroundColor Cyan
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR83Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r83 package build failed with exit code $LASTEXITCODE" }

    Write-Host 'R83_EXACT_TELEMETRY_TARGETING_PASS' -ForegroundColor Green
    Write-Host '  - renderer eligibility is thread-DOM gated, not app:// gated'
    Write-Host '  - bounded turn_context model survives the safe envelope'

    Write-Host '[r83 4/4] Package completed; tracked source restoration will run in finally.' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'R83_LOCAL_BUILD_PASS' -ForegroundColor Green
    Write-Host 'R83_R43_R65_CARRY_FORWARD_PACKAGE_PASS' -ForegroundColor Green
    Write-Host '  - r43-r65 selective carry-forward retained'
    Write-Host '  - r66-r69 Hook A/B experiments remain excluded'
    Write-Host '  - r70 masked-history repair remains protected by the selective materializer'
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
