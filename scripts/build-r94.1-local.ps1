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

foreach ($Path in @($Inner,$CargoToml,$CargoLock,$DebugBanner,$ThemeInjector,$OutputUiBuilder)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "r94.1 required source missing: $Path"
    }
}

$CargoText = [System.IO.File]::ReadAllText($CargoToml)
$LockText = [System.IO.File]::ReadAllText($CargoLock)
$DebugText = [System.IO.File]::ReadAllText($DebugBanner)
$ThemeText = [System.IO.File]::ReadAllText($ThemeInjector)
$OutputUiText = [System.IO.File]::ReadAllText($OutputUiBuilder)

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

$WorkspaceCargo = Join-Path $RepoRoot 'Cargo.toml'
& cargo test --manifest-path $WorkspaceCargo -p codex-app-transfer-codex-integration --lib r94_1_
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 provider policy semantic carry-forward focused tests failed with exit code $LASTEXITCODE"
}
Write-Host 'R94_1_PROVIDER_POLICY_CARRY_FORWARD_FOCUSED_TESTS_PASS' -ForegroundColor Green

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
        throw "r94.1 delegated build failed with exit code $LASTEXITCODE"
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
    Write-Host '  - focused r94.1 Rust tests + inherited r94 generated-chain preflight completed; release build was not started'
} else {
    Write-Host 'R94_1_PREVIEW_WRAPPER_RUNTIME_PASS' -ForegroundColor Green
    Write-Host '  - visible/package identity is r94.1 / 2.4.5+94.1'
    Write-Host '  - Windows title, in-app badge and nested base-builder identity are forced through the visible-identity override hook'
}
