param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R86Builder = Join-Path $PSScriptRoot 'build-r86-local.ps1'
$GuardSource = Join-Path $RepoRoot 'frontend/src/components/provider/Sub2ApiGrokCompatControls.vue'
$R86Stamp = Join-Path $PSScriptRoot 'r86-timestamp-stamp.js'
$R86Observer = Join-Path $PSScriptRoot 'r86-timestamp-observer.js'
$R86ObserverPatch = Join-Path $PSScriptRoot 'r86-r78-observer-patch.inc.ps1'

$TempBuilder = Join-Path $PSScriptRoot '.build-r87-from-r86.generated.ps1'
$TempStamp = Join-Path $PSScriptRoot 'r87-timestamp-stamp.js'
$TempObserver = Join-Path $PSScriptRoot 'r87-timestamp-observer.js'
$TempObserverPatch = Join-Path $PSScriptRoot 'r87-r78-observer-patch.inc.ps1'

foreach ($Path in @($R86Builder,$GuardSource,$R86Stamp,$R86Observer,$R86ObserverPatch)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r87 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r87 PowerShell parse failed: $Label :: $Summary"
    }
}

function Retarget-R86Text([string]$Text) {
    return $Text.Replace('r86','r87').Replace('R86','R87').Replace('+86','+87')
}

$GuardText = [System.IO.File]::ReadAllText($GuardSource)
foreach ($Marker in @(
    'CAS-R87-SUB2API-COMPAT-GUARD-READONLY',
    'data-cas-r87-compat-guard="readonly"',
    'zero active probes',
    'Sub2API-owned · not probed',
    'Transfer-owned · armed',
    'Unknown · no passive signal'
)) {
    if (-not $GuardText.Contains($Marker)) { throw "r87 guard invariant missing: $Marker" }
}

# The compatibility guard itself must stay passive. These call shapes are
# forbidden inside the component so a future UI edit cannot silently turn the
# read-only status card into an active provider probe or retry path.
foreach ($Forbidden in @('fetch(', 'providersApi.', 'invoke(', 'axios.', '$http.', 'retryRequest(')) {
    if ($GuardText.Contains($Forbidden)) { throw "r87 guard contains forbidden active-call shape: $Forbidden" }
}

$OriginalR86 = [System.IO.File]::ReadAllText($R86Builder)
$R87BuilderText = Retarget-R86Text $OriginalR86
$R87StampText = Retarget-R86Text ([System.IO.File]::ReadAllText($R86Stamp))
$R87ObserverText = Retarget-R86Text ([System.IO.File]::ReadAllText($R86Observer))
$R87ObserverPatchText = Retarget-R86Text ([System.IO.File]::ReadAllText($R86ObserverPatch))

# r86 preflight verified the legacy r77 assistantRootsNow source before the
# strict observer replacement. During a real nested build, however, r78 installs
# the r86+ observer first, so the generated r77 telemetry builder no longer sees
# the legacy assistant-root block and used to fail before telemetry generation.
# Treat the strict/live-only observer as the authoritative replacement for those
# two legacy r77 timestamp edits, while keeping every non-timestamp r77 failure
# strict. Also relax the generated-source verification to the assistantRootsNow
# function shared by both the legacy fallback and strict observer implementations.
$OldR77MissingGuard = @'
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r77 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld, $NormalizedNew)
'@
$NewR77MissingGuard = @'
    if (-not $NormalizedText.Contains($NormalizedOld)) {
        if (($Label -eq 'timestamp fallback assistant roots' -or $Label -eq 'timestamp mutation fallback root') -and
            $NormalizedText.Contains('function strictAssistantRootFor(node) {') -and
            $NormalizedText.Contains('state.timestampBaselineElements = new WeakSet();')) {
            Write-Host 'R77_TIMESTAMP_ROOT_RECOVERY_SUPERSEDED_PASS' -ForegroundColor Green
            return $NormalizedText
        }
        throw "r77 expected text missing: $Label"
    }
    return $NormalizedText.Replace($NormalizedOld, $NormalizedNew)
'@
if (-not $R87BuilderText.Contains($OldR77MissingGuard)) {
    throw 'r87 could not locate the EOL-safe r77 missing-source guard'
}
$R87BuilderText = $R87BuilderText.Replace($OldR77MissingGuard,$NewR77MissingGuard)

$R77CreateNeedle = @'
$PatchedR77 = Replace-Required $OriginalR77 $OldR77ReplaceRequired $NewR77ReplaceRequired 'make r77 multiline replacements EOL-safe'
'@
$R77CreateReplacement = @'
$PatchedR77 = Replace-Required $OriginalR77 $OldR77ReplaceRequired $NewR77ReplaceRequired 'make r77 multiline replacements EOL-safe'
$R77LegacyVerifyMarker = "    'assistantRootForAny(node)',"
$R77CommonVerifyMarker = "    'function assistantRootsNow() {',"
if (-not $PatchedR77.Contains($R77LegacyVerifyMarker)) {
    throw 'r87 could not locate the r77 legacy assistant-root verification marker'
}
$PatchedR77 = $PatchedR77.Replace($R77LegacyVerifyMarker,$R77CommonVerifyMarker)
'@
if (-not $R87BuilderText.Contains($R77CreateNeedle)) {
    throw 'r87 could not locate r77 compatibility materialization point'
}
$R87BuilderText = $R87BuilderText.Replace($R77CreateNeedle,$R77CreateReplacement)

foreach ($Marker in @(
    "`$R87Core = `$OriginalR83.Replace('r83','r87').Replace('R83','R87').Replace('+83','+87')",
    'r87-timestamp-stamp.js',
    'r87-timestamp-observer.js',
    'r87-r78-observer-patch.inc.ps1',
    'R87_TIMESTAMP_CORRECTNESS_PREFLIGHT_PASS',
    'R87_R77_COMPAT_PREFLIGHT_PASS',
    'R87_TIMESTAMP_CORRECTNESS_PASS',
    'R77_TIMESTAMP_ROOT_RECOVERY_SUPERSEDED_PASS',
    '$R77CommonVerifyMarker'
)) {
    if (-not $R87BuilderText.Contains($Marker)) { throw "r87 retargeted r86 builder invariant missing: $Marker" }
}

Assert-PowerShellParses $R87BuilderText 'retargeted r87 wrapper'

# Keep the already-proven r43-r65/r70/r86 pipeline intact. r87 only adds a
# tracked read-only UI guard plus a version retarget. The generated timestamp
# helpers are untracked build inputs and are removed in finally.
Write-Host 'R87_SUB2API_COMPAT_GUARD_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - Compatibility Guard is read-only and contains no active provider calls'
Write-Host '  - no /health, /models, /responses probe is issued by the guard'
Write-Host '  - generic 502/503/timeout turn replay is not added'
Write-Host '  - transport fallback remains explicitly Sub2API-owned / not probed'
Write-Host '  - r86 timestamp correctness pipeline is inherited and retargeted, not rewritten'
Write-Host '  - r77 legacy timestamp-root recovery safely yields to the r86+ strict observer during full builds'
Write-Host '  - r43-r65 selective carry-forward and r66-r69 negative guards remain inherited'

try {
    Write-Utf8NoBom $TempBuilder $R87BuilderText
    Write-Utf8NoBom $TempStamp $R87StampText
    Write-Utf8NoBom $TempObserver $R87ObserverText
    Write-Utf8NoBom $TempObserverPatch $R87ObserverPatchText

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r87 inherited r86 pipeline failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R87_COMPAT_GUARD_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R87_SUB2API_COMPAT_GUARD_READONLY_PASS' -ForegroundColor Green
        Write-Host '  - provider UI reports configured/armed/unknown ownership without generating probe traffic'
        Write-Host '  - unknown Sub2API version/capabilities remain unknown instead of being guessed from release numbers'
        Write-Host '  - visible/package identity is r87 / 2.4.5+87'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempStamp,$TempObserver,$TempObserverPatch)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r87] removed temporary generated wrappers/helpers; tracked worktree stays pull-friendly'
}
