param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R87Builder = Join-Path $PSScriptRoot 'build-r87-local.ps1'
$R88Observer = Join-Path $PSScriptRoot 'r88-timestamp-observer.js'
$R88PaneJs = Join-Path $PSScriptRoot 'r88-pane-runtime.js'
$R88PanePatch = Join-Path $PSScriptRoot 'r88-r75-pane-runtime-patch-v4.inc.ps1'
$TempBuilder = Join-Path $PSScriptRoot '.build-r88-from-r87.generated.ps1'
$TempObserverCheck = Join-Path $PSScriptRoot '.r88-observer-syntax.generated.mjs'

foreach ($Path in @($R87Builder,$R88Observer,$R88PaneJs,$R88PanePatch)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r88 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR87 = [System.IO.File]::ReadAllText($R87Builder)
$ObserverText = [System.IO.File]::ReadAllText($R88Observer)
$PaneJsText = [System.IO.File]::ReadAllText($R88PaneJs)
$PanePatchText = [System.IO.File]::ReadAllText($R88PanePatch)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r88 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r88 PowerShell parse failed: $Label :: $Summary"
    }
}

$Head = (git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'r88 git rev-parse failed' }
$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r88 git status failed' }
if ($Dirty.Count -gt 0) { throw "r88 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

foreach ($Marker in @(
    'function activeGenerationUiPresentFor(node) {',
    'function latestConversationTurnFor(node) {',
    'function hasRecentLiveUsageFor(node) {',
    'function liveSemanticRootFor(node) {',
    'state.timestampBaselineElements = new WeakSet();',
    'first observed live output mutation locally',
    'if (!hasRecentLiveUsage()) return;',
    'sweepOutputSegments(false)'
)) {
    if (-not $ObserverText.Contains($Marker)) { throw "r88 observer invariant missing: $Marker" }
}
foreach ($Marker in @(
    'R88_PANE_RUNTIME_JS',
    'R88_COMPOSER_BLOCK_START',
    'R88_COMPOSER_BLOCK_END',
    'R88_REFRESH_BLOCK_START',
    'R88_REFRESH_BLOCK_END',
    'function findComposerRoots() {',
    'function paneForNode(node) {',
    'function normalizePaneThreadId(value) {',
    'function paneSessionId(pane, composer) {',
    'function paneThreadId(pane, composer) {',
    'function paneAgentId(pane) {',
    'function ensureStatusBars() {',
    'function statusHtmlForPane(sessionId, threadId, agentId) {',
    'margin:0 0 22px 0'
)) {
    if (-not $PaneJsText.Contains($Marker)) { throw "r88 pane JS invariant missing: $Marker" }
}
foreach ($Marker in @(
    'R88_PANE_RUNTIME_GENERATION_PATCH_V4',
    'R88_PANE_RUNTIME_PATCH',
    "const PANE_SESSION_ATTR = 'data-cas-pane-session-id';",
    'r88-pane-runtime.js',
    'Get-R88PaneJsBlock',
    'r88 pane-scoped composer/status mounting',
    'r88 pane status refresh'
)) {
    if (-not $PanePatchText.Contains($Marker)) { throw "r88 pane patch invariant missing: $Marker" }
}
Assert-PowerShellParses $PanePatchText 'r88 pane generation include'
Write-Host 'R88_PANE_PATCH_PS_PARSE_PASS' -ForegroundColor Green

try {
    Write-Utf8NoBom $TempObserverCheck ("function __r88ObserverSyntaxOnly(){`n" + $ObserverText + "`n}`n")
    node --check $TempObserverCheck
    if ($LASTEXITCODE -ne 0) { throw 'r88 timestamp observer JavaScript syntax check failed' }
    Write-Host 'R88_TIMESTAMP_OBSERVER_JS_PREFLIGHT_PASS' -ForegroundColor Green

    node --check $R88PaneJs
    if ($LASTEXITCODE -ne 0) { throw 'r88 pane runtime JavaScript syntax check failed' }
    Write-Host 'R88_PANE_RUNTIME_JS_PREFLIGHT_PASS' -ForegroundColor Green

    $R88 = $OriginalR87

    $R88 = Replace-Required $R88 `
        "`$R86Observer = Join-Path `$PSScriptRoot 'r86-timestamp-observer.js'" `
        "`$R86Observer = Join-Path `$PSScriptRoot 'r88-timestamp-observer.js'" `
        'use r88 timestamp observer'

    $R88 = Replace-Required $R88 `
        "    return `$Text.Replace('r86','r87').Replace('R86','R87').Replace('+86','+87')" `
        "    return `$Text.Replace('r86','r88').Replace('R86','R88').Replace('+86','+88')" `
        'retarget inherited r86 package to r88'

    # All helper files written and removed by the inherited r87 wrapper must use
    # dedicated generated names. Never let a cleanup path alias a tracked r88
    # source file: the first r88 preflight exposed exactly that collision.
    foreach ($Pair in @(
        @('.build-r87-from-r86.generated.ps1', '.build-r88-from-r86.generated.ps1'),
        @('r87-timestamp-stamp.js', '.r88-timestamp-stamp.generated.js'),
        @('r87-timestamp-observer.js', '.r88-timestamp-observer.generated.js'),
        @('r87-r78-observer-patch.inc.ps1', '.r88-r78-observer-patch.generated.inc.ps1')
    )) {
        $R88 = Replace-Required $R88 $Pair[0] $Pair[1] "retarget generated helper $($Pair[0])"
    }

    foreach ($ForbiddenCollision in @(
        "`$TempStamp = Join-Path `$PSScriptRoot 'r88-timestamp-stamp.js'",
        "`$TempObserver = Join-Path `$PSScriptRoot 'r88-timestamp-observer.js'",
        "`$TempObserverPatch = Join-Path `$PSScriptRoot 'r88-r78-observer-patch.inc.ps1'"
    )) {
        if ($R88.Contains($ForbiddenCollision)) {
            throw "r88 tracked-source/temp-helper collision detected: $ForbiddenCollision"
        }
    }
    foreach ($ExpectedTemp in @(
        "`$TempStamp = Join-Path `$PSScriptRoot '.r88-timestamp-stamp.generated.js'",
        "`$TempObserver = Join-Path `$PSScriptRoot '.r88-timestamp-observer.generated.js'",
        "`$TempObserverPatch = Join-Path `$PSScriptRoot '.r88-r78-observer-patch.generated.inc.ps1'"
    )) {
        if (-not $R88.Contains($ExpectedTemp)) {
            throw "r88 generated-helper isolation invariant missing: $ExpectedTemp"
        }
    }
    Write-Host 'R88_GENERATED_HELPER_ISOLATION_PASS' -ForegroundColor Green

    $PaneDeclNeedle = "`$R86ObserverPatch = Join-Path `$PSScriptRoot 'r86-r78-observer-patch.inc.ps1'"
    $PaneDeclReplacement = @'
$R86ObserverPatch = Join-Path $PSScriptRoot 'r86-r78-observer-patch.inc.ps1'
$R88PanePatchInclude = Join-Path $PSScriptRoot 'r88-r75-pane-runtime-patch-v4.inc.ps1'
if (-not (Test-Path -LiteralPath $R88PanePatchInclude)) { throw "r88 pane runtime patch missing: $R88PanePatchInclude" }
'@
    $R88 = Replace-Required $R88 $PaneDeclNeedle $PaneDeclReplacement 'declare r88 pane patch include'

    $BuilderNeedle = '$R87BuilderText = Retarget-R86Text $OriginalR86'
    $BuilderInsertion = @'
$R87BuilderText = Retarget-R86Text $OriginalR86
foreach ($Pair in @(
    @('r88-timestamp-stamp.js', '.r88-timestamp-stamp.generated.js'),
    @('r88-timestamp-observer.js', '.r88-timestamp-observer.generated.js'),
    @('r88-r78-observer-patch.inc.ps1', '.r88-r78-observer-patch.generated.inc.ps1')
)) {
    if (-not $R87BuilderText.Contains($Pair[0])) {
        throw "r88 inner generated-helper source path missing: $($Pair[0])"
    }
    $R87BuilderText = $R87BuilderText.Replace($Pair[0],$Pair[1])
}
foreach ($ExpectedInner in @(
    ".r88-timestamp-stamp.generated.js",
    ".r88-timestamp-observer.generated.js",
    ".r88-r78-observer-patch.generated.inc.ps1"
)) {
    if (-not $R87BuilderText.Contains($ExpectedInner)) {
        throw "r88 inner generated-helper binding missing: $ExpectedInner"
    }
}
Write-Host 'R88_INNER_HELPER_BINDING_PASS' -ForegroundColor Green
$R88PanePatchText = [System.IO.File]::ReadAllText($R88PanePatchInclude)
$R88PaneInsertNeedle = '$NormalizedPatchedR75ForR77 ='
if (-not $R87BuilderText.Contains($R88PaneInsertNeedle)) {
    throw 'r88 could not locate nested r86/r75 pane-runtime insertion point'
}
$R87BuilderText = $R87BuilderText.Replace(
    $R88PaneInsertNeedle,
    $R88PanePatchText + "`r`n`r`n" + $R88PaneInsertNeedle
)
'@
    $R88 = Replace-Required $R88 $BuilderNeedle $BuilderInsertion 'inject pane runtime into nested r75 source'

    $OldCoreVerify = @'
    "`$R87Core = `$OriginalR83.Replace('r83','r87').Replace('R83','R87').Replace('+83','+87')",
'@
    $OldCoreVerify = $OldCoreVerify.Replace('\"','"')
    $NewCoreVerify = @'
    "`$R88Core = `$OriginalR83.Replace('r83','r88').Replace('R83','R88').Replace('+83','+88')",
'@
    $NewCoreVerify = $NewCoreVerify.Replace('\"','"')
    $R88 = Replace-Required $R88 $OldCoreVerify $NewCoreVerify 'retarget inner core verification marker'

    foreach ($Pair in @(
        @("'R87_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS'", "'R88_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS'"),
        @("'R87_R77_COMPAT_PREFLIGHT_PASS'", "'R88_R77_COMPAT_PREFLIGHT_PASS'"),
        @("'R87_TIMESTAMP_CORRECTNESS_PASS'", "'R88_TIMESTAMP_CORRECTNESS_PASS'")
    )) {
        $R88 = Replace-Required $R88 $Pair[0] $Pair[1] "retarget inner verification $($Pair[0])"
    }

    $R88 = $R88.Replace('visible/package identity is r87 / 2.4.5+87','visible/package identity is r88 / 2.4.5+88')
    $R88 = $R88.Replace('R87_SUB2API_COMPAT_GUARD_PREFLIGHT_PASS','R88_SUB2API_COMPAT_GUARD_PREFLIGHT_PASS')
    $R88 = $R88.Replace('R87_SUB2API_COMPAT_GUARD_READONLY_PASS','R88_SUB2API_COMPAT_GUARD_READONLY_PASS')
    $R88 = $R88.Replace('R87_COMPAT_GUARD_PREFLIGHT_ONLY_PASS','R88_COMPAT_GUARD_PREFLIGHT_ONLY_PASS')

    Assert-PowerShellParses $R88 'generated r88 wrapper'
    Write-Host 'R88_GENERATED_WRAPPER_PARSE_PASS' -ForegroundColor Green

    Write-Utf8NoBom $TempBuilder $R88
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r88 nested build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r88 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r88 nested build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R88_PANE_RUNTIME_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - main and split/agent composer panes are enumerated independently'
        Write-Host '  - session id, child thread id and UI agent id are kept as distinct identities'
        Write-Host '  - generated helper cleanup paths are isolated from tracked r88 sources'
        Write-Host '  - inner r86 source paths are bound to the same generated helper filenames'
        Write-Host '  - mismatched telemetry fails closed to -- instead of borrowing another pane''s metrics'
        Write-Host '  - status bars reserve 22px below-bar space so native Step pills do not overlap'
        Write-Host '  - live timestamp fallback is pane-scoped and still blocks baseline/remounted history'
    } else {
        Write-Host ''
        Write-Host 'R88_PANE_RUNTIME_UI_FIX_PASS' -ForegroundColor Green
        Write-Host '  - pane-aware live timestamps restored without weakening historical-baseline protection'
        Write-Host '  - one status bar per visible conversation/agent pane'
        Write-Host '  - pane-local sid/tid visible; agent handle is not misreported as session/thread id'
        Write-Host '  - non-owned telemetry is never borrowed from another pane'
        Write-Host '  - visible/package identity is r88 / 2.4.5+88'
    }
}
finally {
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TempObserverCheck -Force -ErrorAction SilentlyContinue
    Write-Host '[r88] removed temporary generated wrappers; tracked worktree stays pull-friendly'
}
