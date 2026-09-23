param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Inner = Join-Path $PSScriptRoot 'build-r94-local.ps1'
$CargoToml = Join-Path $RepoRoot 'src-tauri\Cargo.toml'
$CargoLock = Join-Path $RepoRoot 'Cargo.lock'
$DebugBanner = Join-Path $RepoRoot 'frontend\src\components\codex\RuntimeDebugBanner.vue'
$ThemeInjector = Join-Path $RepoRoot 'src-tauri\src\codex_theme_injector.rs'
$OutputUiBuilder = Join-Path $PSScriptRoot 'build-r74-output-ui-local.ps1'
$RetryForward = Join-Path $RepoRoot 'crates\proxy\src\forward.rs'
$RetryServer = Join-Path $RepoRoot 'crates\proxy\src\server.rs'
$RetrySettings = Join-Path $RepoRoot 'src-tauri\src\admin\handlers\settings.rs'
$RetrySettingsPage = Join-Path $RepoRoot 'frontend\src\pages\SettingsPage.vue'
$RetryNoMicro = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\no_micro.rs'
$RetryLauncher = Join-Path $RepoRoot 'src-tauri\resources\codex_no_micro_launcher.mjs'

foreach ($Path in @($Inner,$CargoToml,$CargoLock,$DebugBanner,$ThemeInjector,$OutputUiBuilder,$RetryForward,$RetryServer,$RetrySettings,$RetrySettingsPage,$RetryNoMicro,$RetryLauncher)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "r94.1 required source missing: $Path"
    }
}

$CargoText = [System.IO.File]::ReadAllText($CargoToml)
$LockText = [System.IO.File]::ReadAllText($CargoLock)
$DebugText = [System.IO.File]::ReadAllText($DebugBanner)
$ThemeText = [System.IO.File]::ReadAllText($ThemeInjector)
$OutputUiText = [System.IO.File]::ReadAllText($OutputUiBuilder)
$RetryForwardText = [System.IO.File]::ReadAllText($RetryForward)
$RetryServerText = [System.IO.File]::ReadAllText($RetryServer)
$RetrySettingsText = [System.IO.File]::ReadAllText($RetrySettings)
$RetrySettingsPageText = [System.IO.File]::ReadAllText($RetrySettingsPage)
$RetryNoMicroText = [System.IO.File]::ReadAllText($RetryNoMicro)
$RetryLauncherText = [System.IO.File]::ReadAllText($RetryLauncher)

foreach ($Check in @(
    @{ Text = $CargoText; Marker = 'version = "2.4.5+94.1"' },
    @{ Text = $LockText; Marker = 'version = "2.4.5+94.1"' },
    @{ Text = $DebugText; Marker = "EXPECTED_TRANSFER_REVISION = 'r94.1'" },
    @{ Text = $DebugText; Marker = "EXPECTED_TRANSFER_VERSION = '2.4.5+94.1'" },
    @{ Text = $DebugText; Marker = 'DBG94.1-1' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_TRANSFER_REVISION: &str = "r94.1"' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_TRANSFER_VERSION: &str = "2.4.5+94.1"' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_PROTOCOL: &str = "DBG94.1-1"' },
    @{ Text = $OutputUiText; Marker = 'CAS-VISIBLE-IDENTITY-OVERRIDE' },
    @{ Text = $OutputUiText; Marker = 'CAS_TRANSFER_VISIBLE_REVISION' },
    @{ Text = $OutputUiText; Marker = 'R74_VISIBLE_IDENTITY_OVERRIDE_PASS' }
)) {
    if (-not $Check.Text.Contains($Check.Marker)) {
        throw "r94.1 preview identity guard missing: $($Check.Marker)"
    }
}

Write-Host 'R94_1_PREVIEW_WRAPPER_IDENTITY_PASS' -ForegroundColor Green

foreach ($Check in @(
    @{ Text = $RetryForwardText; Marker = 'CAS-R94-1-TRANSFER-UPSTREAM-CONNECT-RETRY' },
    @{ Text = $RetryForwardText; Marker = 'error.is_connect()' },
    @{ Text = $RetryForwardText; Marker = 'set_upstream_connect_retry_policy' },
    @{ Text = $RetryForwardText; Marker = 'transfer-upstream-retry-time-limit' },
    @{ Text = $RetryForwardText; Marker = 'mode=infinite' },
    @{ Text = $RetryServerText; Marker = '/_cas/transfer-retry-status' },
    @{ Text = $RetryServerText; Marker = '"maxDurationMs"' },
    @{ Text = $RetryServerText; Marker = 'transfer_retry_status_options_handler' },
    @{ Text = $RetryServerText; Marker = 'access-control-allow-private-network' },
    @{ Text = $RetrySettingsText; Marker = 'upstreamConnectRetryInfinite' },
    @{ Text = $RetrySettingsText; Marker = 'upstreamConnectRetryMaxHours' },
    @{ Text = $RetrySettingsPageText; Marker = "persist({ upstreamConnectRetries: value })" },
    @{ Text = $RetrySettingsPageText; Marker = 'upstreamConnectRetryInfinite' },
    @{ Text = $RetrySettingsPageText; Marker = 'upstreamConnectRetryMaxHours' },
    @{ Text = $RetryNoMicroText; Marker = 'CAS_TRANSFER_PROXY_PORT' },
    @{ Text = $RetryLauncherText; Marker = 'CAS-R94-1-TRANSFER-RETRY-CODEX-OVERLAY' },
    @{ Text = $RetryLauncherText; Marker = 'TRANSFER RETRY ' },
    @{ Text = $RetryLauncherText; Marker = "retry && retry.infinite ? '∞'" },
    @{ Text = $RetryLauncherText; Marker = 'retry.maxDurationMs' },
    @{ Text = $RetryLauncherText; Marker = 'retryRemainingMs' },
    @{ Text = $RetryLauncherText; Marker = 'statusAvailable' },
    @{ Text = $RetryLauncherText; Marker = 'CAS-R94-1-TRANSFER-RETRY-MAIN-BRIDGE' },
    @{ Text = $RetryLauncherText; Marker = 'process.getBuiltinModule("http")' },
    @{ Text = $RetryLauncherText; Marker = '__casTransferRetryBridge' },
    @{ Text = $RetryLauncherText; Marker = 'applyRetrySnapshot' },
    @{ Text = $RetryLauncherText; Marker = 'main-process-loopback' },
    @{ Text = $OutputUiText; Marker = 'CAS-R94-1-TRANSFER-RETRY-GENERATED-CARRY' },
    @{ Text = $OutputUiText; Marker = "retry && retry.infinite ? '∞'" },
    @{ Text = $OutputUiText; Marker = 'retry.maxDurationMs' },
    @{ Text = $OutputUiText; Marker = 'retryRemainingMs' },
    @{ Text = $OutputUiText; Marker = 'statusAvailable' },
    @{ Text = $OutputUiText; Marker = '__casTransferRetryBridge' },
    @{ Text = $OutputUiText; Marker = 'applyRetrySnapshot' },
    @{ Text = $OutputUiText; Marker = 'main-process-loopback' },
    @{ Text = $OutputUiText; Marker = 'R74_TRANSFER_RETRY_GENERATED_CARRY_PASS' },
    @{ Text = $OutputUiText; Marker = 'function outputTelemetryRuntimeSource(proxyPort)' },
    @{ Text = $ThemeText; Marker = 'retryBridgeError' },
    @{ Text = $ThemeText; Marker = 'retryTransport' }
)) {
    if (-not $Check.Text.Contains($Check.Marker)) {
        throw "r94.1 Transfer retry contract missing: $($Check.Marker)"
    }
}
foreach ($Forbidden in @(
    'codex-r94.1-runtime',
    'CAS_R94_1_CODEX_RUNTIME_EXE',
    'CAS_R94_1_OPENAI_POLICY_OVERLAY'
)) {
    if ($RetryLauncherText.Contains($Forbidden) -or $RetryNoMicroText.Contains($Forbidden)) {
        throw "r94.1 Transfer-only retry contract violated: $Forbidden"
    }
}
foreach ($StaleRetryCap in @(
    'MAX_TRANSFER_UPSTREAM_CONNECT_RETRIES',
    'between 0 and 15',
    'max="15"',
    '1–15'
)) {
    if (
        $RetryForwardText.Contains($StaleRetryCap) -or
        $RetrySettingsText.Contains($StaleRetryCap) -or
        $RetrySettingsPageText.Contains($StaleRetryCap)
    ) {
        throw "r94.1 stale retry cap reintroduced: $StaleRetryCap"
    }
}
Write-Host 'R94_1_NO_STALE_RETRY_CAP_PASS' -ForegroundColor Green

foreach ($MisleadingIdleRetryUi in @(
    'TRANSFER RETRY READY ',
    'Transfer connect-stage retry policy is armed'
)) {
    if ($RetryLauncherText.Contains($MisleadingIdleRetryUi) -or $OutputUiText.Contains($MisleadingIdleRetryUi)) {
        throw "r94.1 misleading idle retry UI reintroduced: $MisleadingIdleRetryUi"
    }
}
Write-Host 'R94_1_RETRY_INCIDENT_ONLY_UI_PASS' -ForegroundColor Green

if ($RetryForwardText.Contains('tokio::time::timeout')) {
    throw 'r94.1 retry safety contract violated: request attempts must not be hard-cancelled by the retry window'
}
Write-Host 'R94_1_RETRY_NO_HARD_CANCEL_PASS' -ForegroundColor Green

Write-Host 'R94_1_TRANSFER_RETRY_CONTRACT_PASS' -ForegroundColor Green

& node --check $RetryLauncher
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 No Lagging retry overlay JavaScript syntax failed: $LASTEXITCODE"
}
Write-Host 'R94_1_TRANSFER_RETRY_JS_SYNTAX_PASS' -ForegroundColor Green

$R74Start = $RetryLauncherText.IndexOf('function outputTelemetryRuntimeSource')
if ($R74Start -lt 0) {
    throw 'r94.1 r74 launcher-boundary preflight could not locate telemetry function start'
}
$R74End = $RetryLauncherText.IndexOf('function stubExpression(', $R74Start)
if ($R74End -le $R74Start) {
    throw 'r94.1 r74 launcher-boundary preflight could not locate telemetry function end'
}
Write-Host 'R94_1_R74_LAUNCHER_BOUNDARY_PREFLIGHT_PASS' -ForegroundColor Green

$WorkspaceCargo = Join-Path $RepoRoot 'Cargo.toml'
& cargo test --manifest-path $WorkspaceCargo -p codex-app-transfer-codex-integration --lib r94_1_
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 Transfer-only provider/config focused tests failed with exit code $LASTEXITCODE"
}
Write-Host 'R94_1_TRANSFER_ONLY_PROVIDER_CONFIG_FOCUSED_TESTS_PASS' -ForegroundColor Green

& cargo test --manifest-path $WorkspaceCargo -p codex-app-transfer-proxy r94_1_transfer_retry_ -- --test-threads=1
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 Transfer retry focused tests failed with exit code $LASTEXITCODE"
}
Write-Host 'R94_1_TRANSFER_RETRY_FOCUSED_TESTS_PASS' -ForegroundColor Green

$Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Inner)
if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
if ($PreflightOnly) { $Args += '-PreflightOnly' }

$OldVisibleRevision = $env:CAS_TRANSFER_VISIBLE_REVISION
$OldVisibleVersion = $env:CAS_TRANSFER_VISIBLE_VERSION
try {
    $env:CAS_TRANSFER_VISIBLE_REVISION = 'r94.1'
    $env:CAS_TRANSFER_VISIBLE_VERSION = '2.4.5+94.1'

    & pwsh @Args
    if ($LASTEXITCODE -ne 0) {
        throw "r94.1 delegated Transfer build failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -eq $OldVisibleRevision) {
        Remove-Item Env:CAS_TRANSFER_VISIBLE_REVISION -ErrorAction SilentlyContinue
    } else {
        $env:CAS_TRANSFER_VISIBLE_REVISION = $OldVisibleRevision
    }
    if ($null -eq $OldVisibleVersion) {
        Remove-Item Env:CAS_TRANSFER_VISIBLE_VERSION -ErrorAction SilentlyContinue
    } else {
        $env:CAS_TRANSFER_VISIBLE_VERSION = $OldVisibleVersion
    }
}

if ($PreflightOnly) {
    Write-Host 'R94_1_PREVIEW_WRAPPER_PREFLIGHT_PASS' -ForegroundColor Green
    Write-Host '  - focused r94.1 Transfer-only tests + inherited r94 generated-chain preflight completed; release build was not started'
    Write-Host '  - uncapped finite + timed infinite Transfer retry setting/logging/Codex status overlay contracts passed'
} else {
    Write-Host 'R94_1_PREVIEW_WRAPPER_RUNTIME_PASS' -ForegroundColor Green
    Write-Host '  - visible/package identity is r94.1 / 2.4.5+94.1'
    Write-Host '  - Windows title, in-app badge and nested base-builder identity are forced through the visible-identity override hook'
    Write-Host '  - Transfer does not build, patch, replace or launch a private Codex runtime'
    Write-Host '  - Transfer finite retry counts have no artificial 15 cap; timed infinite mode is available'
    Write-Host '  - No Lagging shows TRANSFER RETRY x/N or x/∞ with elapsed/max time inside Codex'
}
