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
$CodexRuntimeBuilder = Join-Path $PSScriptRoot 'build-r94.1-codex-runtime.ps1'
$NoMicroRs = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\no_micro.rs'
$DesktopProcessRs = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$NoMicroLauncher = Join-Path $RepoRoot 'src-tauri\resources\codex_no_micro_launcher.mjs'
$CodexRuntimeExe = Join-Path $RepoRoot 'target\release\codex-r94.1-runtime.exe'
$DeployDir = 'V:\Codex App Transfer'
$DeployCodexRuntime = Join-Path $DeployDir 'codex-r94.1-runtime.exe'

foreach ($Path in @($Inner,$CargoToml,$CargoLock,$DebugBanner,$ThemeInjector,$OutputUiBuilder,$CodexRuntimeBuilder,$NoMicroRs,$DesktopProcessRs,$NoMicroLauncher)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "r94.1 required source missing: $Path"
    }
}

$CargoText = [System.IO.File]::ReadAllText($CargoToml)
$LockText = [System.IO.File]::ReadAllText($CargoLock)
$DebugText = [System.IO.File]::ReadAllText($DebugBanner)
$ThemeText = [System.IO.File]::ReadAllText($ThemeInjector)
$OutputUiText = [System.IO.File]::ReadAllText($OutputUiBuilder)
$CodexRuntimeBuilderText = [System.IO.File]::ReadAllText($CodexRuntimeBuilder)
$NoMicroText = [System.IO.File]::ReadAllText($NoMicroRs)
$DesktopProcessText = [System.IO.File]::ReadAllText($DesktopProcessRs)
$NoMicroLauncherText = [System.IO.File]::ReadAllText($NoMicroLauncher)

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
    @{ Text = $CodexRuntimeBuilderText; Marker = 'CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY' },
    @{ Text = $CodexRuntimeBuilderText; Marker = 'built_in_provider.stream_max_retries = provider.stream_max_retries' },
    @{ Text = $CodexRuntimeBuilderText; Marker = 'built_in_provider.request_max_retries = provider.request_max_retries' },
    @{ Text = $CodexRuntimeBuilderText; Marker = 'built_in_provider.stream_idle_timeout_ms = provider.stream_idle_timeout_ms' },
    @{ Text = $CodexRuntimeBuilderText; Marker = 'built_in_provider.websocket_connect_timeout_ms' },
    @{ Text = $NoMicroText; Marker = 'R94_1_CODEX_RUNTIME_FILE' },
    @{ Text = $NoMicroText; Marker = 'r94_1_openai_policy_overlay_active' },
    @{ Text = $NoMicroText; Marker = 'CAS_R94_1_CODEX_RUNTIME_EXE' },
    @{ Text = $NoMicroText; Marker = 'CAS_R94_1_OPENAI_POLICY_OVERLAY' },
    @{ Text = $DesktopProcessText; Marker = 'r94_1_openai_policy_overlay_active()' },
    @{ Text = $DesktopProcessText; Marker = '请使用 No Lagging 启动 (B)' },
    @{ Text = $NoMicroLauncherText; Marker = 'CAS-R94-1-CODEX-APP-SERVER-RUNTIME-OVERLAY' },
    @{ Text = $NoMicroLauncherText; Marker = 'CAS-R94-1-CODEX-APP-SERVER-RUNTIME-VERIFY' },
    @{ Text = $NoMicroLauncherText; Marker = 'return args.some((arg) => String(arg) === "app-server")' },
    @{ Text = $NoMicroLauncherText; Marker = 'args[0] = r941RuntimeExe' },
    @{ Text = $NoMicroLauncherText; Marker = 'native-runtime-verified' },
    @{ Text = $NoMicroLauncherText; Marker = 'waitForR941RuntimeOverlay' }
)) {
    if (-not $Check.Text.Contains($Check.Marker)) {
        throw "r94.1 native runtime overlay integration missing: $($Check.Marker)"
    }
}
if (-not $CodexRuntimeBuilderText.Contains("if ($MergeReplacement.Contains('built_in_provider.base_url')") -or
    -not $CodexRuntimeBuilderText.Contains("$MergeReplacement.Contains('built_in_provider.requires_openai_auth')") -or
    -not $CodexRuntimeBuilderText.Contains("$MergeReplacement.Contains('built_in_provider.name =')")) {
    throw 'r94.1 patched runtime builder is missing its precise identity/routing/auth negative guard'
}
Write-Host 'R94_1_BUILTIN_OPENAI_RUNTIME_CHAIN_PREFLIGHT_PASS' -ForegroundColor Green

$PsTokens = $null
$PsErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $CodexRuntimeBuilder,
    [ref]$PsTokens,
    [ref]$PsErrors
) | Out-Null
if (@($PsErrors).Count -ne 0) {
    throw ("r94.1 Codex runtime builder PowerShell parse failed: " + (($PsErrors | ForEach-Object Message) -join '; '))
}
Write-Host 'R94_1_CODEX_RUNTIME_PS_PARSE_PASS' -ForegroundColor Green

& node --check $NoMicroLauncher
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 No Lagging launcher JavaScript syntax check failed with exit code $LASTEXITCODE"
}
Write-Host 'R94_1_CODEX_RUNTIME_JS_SYNTAX_PASS' -ForegroundColor Green

& pwsh -NoProfile -ExecutionPolicy Bypass -File $CodexRuntimeBuilder -PreflightOnly
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 Codex runtime patch preflight failed with exit code $LASTEXITCODE"
}

$WorkspaceCargo = Join-Path $RepoRoot 'Cargo.toml'
& cargo test --manifest-path $WorkspaceCargo -p codex-app-transfer-codex-integration --lib r94_1_
if ($LASTEXITCODE -ne 0) {
    throw "r94.1 built-in openai provider-policy overlay focused tests failed with exit code $LASTEXITCODE"
}
Write-Host 'R94_1_BUILTIN_OPENAI_POLICY_OVERLAY_FOCUSED_TESTS_PASS' -ForegroundColor Green

$Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Inner)
if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
if ($PreflightOnly) { $Args += '-PreflightOnly' }

$OldVisibleRevision = $env:CAS_TRANSFER_VISIBLE_REVISION
$OldVisibleVersion = $env:CAS_TRANSFER_VISIBLE_VERSION
try {
    $env:CAS_TRANSFER_VISIBLE_REVISION = 'r94.1'
    $env:CAS_TRANSFER_VISIBLE_VERSION = '2.4.5+94.1'

    if (-not $PreflightOnly) {
        $CheapPreflightArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Inner,'-PreflightOnly')
        & pwsh @CheapPreflightArgs
        if ($LASTEXITCODE -ne 0) {
            throw "r94.1 inherited preflight failed before native runtime build with exit code $LASTEXITCODE"
        }
        Write-Host 'R94_1_INHERITED_PREFLIGHT_BEFORE_NATIVE_BUILD_PASS' -ForegroundColor Green

        & pwsh -NoProfile -ExecutionPolicy Bypass -File $CodexRuntimeBuilder -OutputPath $CodexRuntimeExe
        if ($LASTEXITCODE -ne 0) {
            throw "r94.1 patched Codex runtime build failed with exit code $LASTEXITCODE"
        }
        if (-not (Test-Path -LiteralPath $CodexRuntimeExe)) {
            throw "r94.1 patched Codex runtime missing after build: $CodexRuntimeExe"
        }
    }

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
    if (-not (Test-Path -LiteralPath $DeployDir)) {
        New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
    }
    Copy-Item -LiteralPath $CodexRuntimeExe -Destination $DeployCodexRuntime -Force
    Copy-Item -LiteralPath "$CodexRuntimeExe.json" -Destination "$DeployCodexRuntime.json" -Force

    Write-Host 'R94_1_PREVIEW_WRAPPER_RUNTIME_PASS' -ForegroundColor Green
    Write-Host '  - visible/package identity is r94.1 / 2.4.5+94.1'
    Write-Host '  - Windows title, in-app badge and nested base-builder identity are forced through the visible-identity override hook'
    Write-Host '  - No Lagging B has a side-by-side, version-matched Codex runtime for built-in openai provider-policy overlay'
    Write-Host '  - standard MSIX restart fails closed while an overlay is active, so stock Codex cannot silently fall back to /5'
    Write-Host '  - No Lagging B launch itself must observe the codex app-server runtime swap before reporting success'
    Write-Host "  - patched runtime deployed: $DeployCodexRuntime"
}
