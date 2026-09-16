param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R77Builder = Join-Path $PSScriptRoot 'build-r77-local.ps1'
$R78Builder = Join-Path $PSScriptRoot 'build-r78-local.ps1'
$TempR80Builder = Join-Path $PSScriptRoot '.build-r80-from-r78.generated.ps1'

foreach ($Path in @($R77Builder, $R78Builder)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r80 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR77 = [System.IO.File]::ReadAllText($R77Builder)
$OriginalR78 = [System.IO.File]::ReadAllText($R78Builder)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r80 expected text missing: $Label" }
    return $Text.Replace($Old, $New)
}

# r76/r77 limited the collector to app:// renderers. Current Codex Desktop can
# host the same thread DOM under other renderer URLs, and the active-thread DOM
# probe is already a stronger eligibility test. Keep only explicit non-app
# tooling exclusions and let the stable thread-id probe decide eligibility.
$PatchedR77 = Replace-Required `
    $OriginalR77 `
    "        if (url && !url.startsWith('app://')) continue;" `
    "        if (url && /^(devtools:|chrome-extension:|chrome:)/i.test(url)) continue;" `
    'do not reject valid Codex renderers solely because URL is not app://'

# r77 began discovering the latest turn_context model, but r76's safe envelope
# dropped it before executeJavaScript(). Preserve the model while still sending
# no prompt/response text or provider credentials to the renderer.
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
$PatchedR77 = Replace-Required $PatchedR77 $OldSafeEnvelope $NewSafeEnvelope 'forward bounded turn_context model'

foreach ($Marker in @(
    "/^(devtools:|chrome-extension:|chrome:)/i.test(url)",
    "model: typeof envelope.model === 'string' ? envelope.model : null,",
    'state.ingestExternalUsage = ingestExternalUsage;',
    'data-above-composer-conversation-id'
)) {
    if (-not $PatchedR77.Contains($Marker)) { throw "r80 telemetry source verification failed: $Marker" }
}

# Make the r78 timestamp/action-row builder generate r80 identity while keeping
# the complete r77 exact-usage recovery and r78 timestamp behavior.
$PatchedR78 = $OriginalR78
$PatchedR78 = Replace-Required $PatchedR78 `
    "Replace('r76', 'r78').Replace('R76', 'R78').Replace('+76', '+78')" `
    "Replace('r76', 'r80').Replace('R76', 'R80').Replace('+76', '+80')" `
    'r80 generated output and entry identity'
$PatchedR78 = Replace-Required $PatchedR78 "Replace('r75', 'r78')" "Replace('r75', 'r80')" 'r80 timestamp generated-source marker'
$PatchedR78 = $PatchedR78.Replace('R78_EXACT_TOKEN_TELEMETRY_PASS', 'R80_EXACT_TOKEN_TELEMETRY_PASS')
$PatchedR78 = $PatchedR78.Replace('R78_LOCAL_ENTRYPOINT_PASS', 'R80_LOCAL_ENTRYPOINT_PASS')
$PatchedR78 = $PatchedR78.Replace('R78_TIMESTAMP_TELEMETRY_BASE_PASS', 'R80_TIMESTAMP_TELEMETRY_BASE_PASS')
$PatchedR78 = $PatchedR78.Replace('R78_TIMESTAMP_ACTIONROW_V4_PASS', 'R80_TIMESTAMP_ACTIONROW_V4_PASS')

foreach ($Marker in @(
    "Replace('r76', 'r80').Replace('R76', 'R80').Replace('+76', '+80')",
    "Replace('r75', 'r80')",
    'R80_EXACT_TOKEN_TELEMETRY_PASS',
    'R80_TIMESTAMP_ACTIONROW_V4_PASS'
)) {
    if (-not $PatchedR78.Contains($Marker)) { throw "r80 generated builder verification failed: $Marker" }
}

try {
    Write-Utf8NoBom $R77Builder $PatchedR77
    Write-Utf8NoBom $TempR80Builder $PatchedR78

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempR80Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r80 local build failed with exit code $LASTEXITCODE" }

    Write-Host ''
    Write-Host 'R80_EXACT_TELEMETRY_TARGETING_PASS' -ForegroundColor Green
    Write-Host '  - exact JSONL collector no longer assumes the Codex renderer URL is app://'
    Write-Host '  - renderer eligibility remains gated by an active thread id from the Codex DOM'
    Write-Host '  - bounded turn_context model now survives the main-process safe envelope'
    Write-Host '  - r78 per-output timestamp action-row strategy is retained'
}
finally {
    Write-Utf8NoBom $R77Builder $OriginalR77
    Remove-Item -LiteralPath $TempR80Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r80] restored temporary source patches; worktree remains pull-friendly'
}
