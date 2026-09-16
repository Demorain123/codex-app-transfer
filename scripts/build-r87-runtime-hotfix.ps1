param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BaseBuilder = Join-Path $PSScriptRoot 'build-r87-local.ps1'
$PanePatch = Join-Path $PSScriptRoot 'r87-pane-status-patch.inc.ps1'
$PaneRuntime = Join-Path $PSScriptRoot 'r87-pane-status-runtime.js'
$ExternalIngest = Join-Path $PSScriptRoot 'r87-external-usage-ingest.js'
$MainCollector = Join-Path $PSScriptRoot 'r87-main-usage-collector.js'
$TimestampObserver = Join-Path $PSScriptRoot 'r86-timestamp-observer.js'
$TempBuilder = Join-Path $PSScriptRoot '.build-r87-runtime-hotfix.generated.ps1'

foreach ($Path in @($BaseBuilder,$PanePatch,$PaneRuntime,$ExternalIngest,$MainCollector,$TimestampObserver)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r87 runtime hotfix required file missing: $Path" }
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'r87 runtime hotfix requires node on PATH' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'r87 runtime hotfix requires git on PATH' }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 10 | ForEach-Object { $_.Message }) -join ' | '
        throw "r87 runtime hotfix PowerShell parse failed: $Label :: $Summary"
    }
}

function Assert-TextContains([string]$Text,[string]$Needle,[string]$Label) {
    if (-not $Text.Contains($Needle)) { throw "r87 runtime hotfix invariant missing ($Label): $Needle" }
}

$TrackedBefore = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r87 runtime hotfix git status preflight failed' }
if ($TrackedBefore.Count -gt 0) {
    throw "r87 runtime hotfix requires a clean tracked worktree.`n$($TrackedBefore -join "`n")"
}

foreach ($Js in @($TimestampObserver,$PaneRuntime,$ExternalIngest,$MainCollector)) {
    & node --check $Js
    if ($LASTEXITCODE -ne 0) { throw "r87 runtime hotfix JavaScript syntax failed: $Js" }
}
Write-Host 'R87_RUNTIME_HOTFIX_JS_PREFLIGHT_PASS' -ForegroundColor Green

$TimestampText = [System.IO.File]::ReadAllText($TimestampObserver)
$PaneRuntimeText = [System.IO.File]::ReadAllText($PaneRuntime)
$ExternalIngestText = [System.IO.File]::ReadAllText($ExternalIngest)
$MainCollectorText = [System.IO.File]::ReadAllText($MainCollector)

foreach ($Check in @(
    @('function timestampPaneScopeFor(node) {','pane-local timestamp scope'),
    @('function latestConversationTurnFor(node) {','pane-local latest turn'),
    @('const composers = timestampComposerRoots();','multi-composer live signal'),
    @('state.timestampBaselineElements.has(segment) || state.timestampBaselineKeys.has(key)','historical baseline guard'),
    @('if (!isLatestTurnSurface(segment)) return;','latest-turn estimated timestamp guard')
)) { Assert-TextContains $TimestampText $Check[0] $Check[1] }

foreach ($Check in @(
    @('function findComposerRoots() {','multi-pane composer resolver'),
    @('function findComposerRoot() {','legacy composer compatibility facade'),
    @('function ensureStatusBars() {','per-pane statusbar renderer'),
    @('function placeStatusHost(host, composer) {','statusbar collision relocation'),
    @('data-cas-status-placement-depth','statusbar placement evidence'),
    @('data-cas-session-id','exact session identity attribute'),
    @('sid ','session id surface'),
    @('tid ','subagent thread id surface')
)) { Assert-TextContains $PaneRuntimeText $Check[0] $Check[1] }

foreach ($Check in @(
    @('state.externalUsageByThread = new Map()','per-thread renderer usage map'),
    @('sessionId: typeof envelope.sessionId ===','session id ingestion'),
    @('parentThreadId: typeof envelope.parentThreadId ===','parent thread ingestion')
)) { Assert-TextContains $ExternalIngestText $Check[0] $Check[1] }

foreach ($Check in @(
    @('CAS-R87-MULTI-PANE-EXACT-TOKEN-TELEMETRY','multi-pane collector marker'),
    @('const visibleThreadExpression = "(() => {" +','visible pane thread resolver'),
    @('const readUsageIdentity = async (filePath, fallbackThreadId) => {','session_meta identity reader'),
    @("line.includes('session_meta')",'session_meta bounded scan'),
    @('sessionId: identity && typeof identity.sessionId ===','session id forwarding'),
    @('parentThreadId: identity && typeof identity.parentThreadId ===','parent id forwarding')
)) { Assert-TextContains $MainCollectorText $Check[0] $Check[1] }
Write-Host 'R87_RUNTIME_HOTFIX_UI_INVARIANTS_PASS' -ForegroundColor Green

$BaseText = [System.IO.File]::ReadAllText($BaseBuilder)
$PanePatchText = [System.IO.File]::ReadAllText($PanePatch)
Assert-PowerShellParses $BaseText 'base r87 builder'
Assert-PowerShellParses $PanePatchText 'pane/status overlay include'

$Needle = @'
$R87ObserverPatchText = Retarget-R86Text ([System.IO.File]::ReadAllText($R86ObserverPatch))
'@
$Injection = @'
$R87ObserverPatchText = Retarget-R86Text ([System.IO.File]::ReadAllText($R86ObserverPatch))

# R87_RUNTIME_HOTFIX_GENERATOR_INJECTION
$R87PanePatchPath = Join-Path $PSScriptRoot 'r87-pane-status-patch.inc.ps1'
if (-not (Test-Path -LiteralPath $R87PanePatchPath)) { throw "r87 pane overlay include missing: $R87PanePatchPath" }
$R87PanePatchText = [System.IO.File]::ReadAllText($R87PanePatchPath)
$R87CoreNeedle = '$R87Core = $OriginalR83.Replace(''r83'',''r87'').Replace(''R83'',''R87'').Replace(''+83'',''+87'')'
if (-not $R87BuilderText.Contains($R87CoreNeedle)) {
    throw 'r87 runtime hotfix could not locate generated r87 core materialization point'
}
$R87BuilderText = $R87BuilderText.Replace($R87CoreNeedle,$R87CoreNeedle + "`r`n`r`n" + $R87PanePatchText)
foreach ($R87HotfixMarker in @(
    'R87_MULTI_PANE_STATUS_OVERLAY',
    'R87_MULTI_PANE_STATUS_RUNTIME_PATCH',
    'R87_MULTI_PANE_COLLECTOR_PATCH',
    'r87-pane-status-runtime.js',
    'r87-external-usage-ingest.js',
    'r87-main-usage-collector.js'
)) {
    if (-not $R87BuilderText.Contains($R87HotfixMarker)) { throw "r87 runtime hotfix generated marker missing: $R87HotfixMarker" }
}
Assert-PowerShellParses $R87BuilderText 'r87 builder with runtime hotfix overlay'
Write-Host 'R87_RUNTIME_HOTFIX_GENERATOR_PREFLIGHT_PASS' -ForegroundColor Green
'@
if (-not $BaseText.Contains($Needle)) {
    throw 'r87 runtime hotfix could not locate base builder observer materialization point'
}
$Generated = $BaseText.Replace($Needle,$Injection)
Assert-PowerShellParses $Generated 'generated runtime-hotfix top-level builder'

foreach ($Marker in @(
    'R87_RUNTIME_HOTFIX_GENERATOR_INJECTION',
    'R87_TIMESTAMP_LIVE_SIGNAL_PREFLIGHT_PASS',
    'R87_MULTI_PANE_STATUS_OVERLAY_PREFLIGHT_PASS'
)) {
    if (-not ($Generated.Contains($Marker) -or $PanePatchText.Contains($Marker))) {
        throw "r87 runtime hotfix static invariant missing: $Marker"
    }
}
Write-Host 'R87_RUNTIME_HOTFIX_STATIC_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - r87 successful package chain remains the unchanged base builder'
Write-Host '  - timestamp live signal stays bounded by pane-local latest-turn/baseline protections'
Write-Host '  - each visible composer can receive an independent status bar'
Write-Host '  - status hosts relocate outward when native composer layout would overlap them'
Write-Host '  - local JSONL session_meta supplies session/thread/parent identity read-only'
Write-Host '  - no provider/Sub2API probe or generic request retry is added'

try {
    [System.IO.File]::WriteAllText($TempBuilder,$Generated,$Utf8NoBom)
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r87 runtime hotfix nested builder failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R87_RUNTIME_HOTFIX_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R87_RUNTIME_HOTFIX_BUILD_PASS' -ForegroundColor Green
        Write-Host '  - visible/package identity remains r87 / 2.4.5+87'
        Write-Host '  - live timestamps + multi-pane status bars + session/thread identity included'
    }
}
finally {
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
    $TrackedAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no 2>$null)
    if ($TrackedAfter.Count -eq 0) {
        Write-Host '[r87-hotfix] tracked worktree remains clean.'
    } else {
        Write-Warning ("r87 runtime hotfix left tracked changes:`n" + ($TrackedAfter -join "`n"))
    }
}
