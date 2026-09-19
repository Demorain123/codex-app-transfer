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

foreach ($Path in @($Inner,$CargoToml,$CargoLock,$DebugBanner,$ThemeInjector)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "r94.1 required source missing: $Path"
    }
}

$CargoText = [System.IO.File]::ReadAllText($CargoToml)
$LockText = [System.IO.File]::ReadAllText($CargoLock)
$DebugText = [System.IO.File]::ReadAllText($DebugBanner)
$ThemeText = [System.IO.File]::ReadAllText($ThemeInjector)

foreach ($Check in @(
    @{ Text = $CargoText; Marker = 'version = "2.4.5+94.1"' },
    @{ Text = $LockText; Marker = 'version = "2.4.5+94.1"' },
    @{ Text = $DebugText; Marker = "EXPECTED_TRANSFER_REVISION = 'r94.1'" },
    @{ Text = $DebugText; Marker = "EXPECTED_TRANSFER_VERSION = '2.4.5+94.1'" },
    @{ Text = $DebugText; Marker = 'DBG94.1-1' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_TRANSFER_REVISION: &str = "r94.1"' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_TRANSFER_VERSION: &str = "2.4.5+94.1"' },
    @{ Text = $ThemeText; Marker = 'RUNTIME_DEBUG_PROTOCOL: &str = "DBG94.1-1"' }
)) {
    if (-not $Check.Text.Contains($Check.Marker)) {
        throw "r94.1 preview identity guard missing: $($Check.Marker)"
    }
}

Write-Host 'R94_1_PREVIEW_WRAPPER_IDENTITY_PASS' -ForegroundColor Green

if (-not $PreflightOnly) {
    $WorkspaceCargo = Join-Path $RepoRoot 'Cargo.toml'
    & cargo test --manifest-path $WorkspaceCargo -p codex-app-transfer-codex-integration --lib r94_1_
    if ($LASTEXITCODE -ne 0) {
        throw "r94.1 provider policy semantic carry-forward focused tests failed with exit code $LASTEXITCODE"
    }
    Write-Host 'R94_1_PROVIDER_POLICY_CARRY_FORWARD_FOCUSED_TESTS_PASS' -ForegroundColor Green
}

$Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Inner)
if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
if ($PreflightOnly) { $Args += '-PreflightOnly' }

& pwsh @Args
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 delegated build failed with exit code $LASTEXITCODE"
}

if ($PreflightOnly) {
    Write-Host 'R94_1_PREVIEW_WRAPPER_PREFLIGHT_PASS' -ForegroundColor Green
} else {
    Write-Host 'R94_1_PREVIEW_WRAPPER_RUNTIME_PASS' -ForegroundColor Green
    Write-Host '  - visible/package identity is r94.1 / 2.4.5+94.1'
}
