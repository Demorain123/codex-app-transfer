#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$WithMsi,
    [switch]$SkipTauriInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r39 verified package policy requires the repository on physical V:. Current: $repoRoot"
}
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r39 - VERIFIED LOCAL PACKAGE' -ForegroundColor Green
Write-Host 'Gate: real frontend + observable 2/2 Release-CRT lifecycle proof + cargo check -> Tauri bundle.'
Write-Host 'Policy: fixed port; no automatic port switching; all project build/cache/package outputs remain on V:.'

# Reuse the exact acceptance path that has already proven the V:-local Rust/native
# toolchain, VsDevCmd/MSVC+SDK environment, bindgen include injection, production
# frontend, Release-CRT linkage, and observable 100-generation same-port test.
$verifiedGate = Join-Path $PSScriptRoot 'build-r39-local-release-stress.ps1'
& $verifiedGate
if ($LASTEXITCODE -ne 0) {
    throw "r39 verified lifecycle gate failed with exit code $LASTEXITCODE"
}

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) {
    throw 'CARGO_HOME is empty after the verified r39 gate.'
}
if ([string]::IsNullOrWhiteSpace($env:CARGO_TARGET_DIR)) {
    throw 'CARGO_TARGET_DIR is empty after the verified r39 gate.'
}
if ([string]::IsNullOrWhiteSpace($env:TEMP)) {
    throw 'TEMP is empty after the verified r39 gate.'
}
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) {
    throw "V:-local cargo.exe was not found: $cargoExe"
}

# Refuse to package on exit-code-only evidence. Re-read the transcript and require
# the same auditable proof as the lifecycle gate itself.
$stressLog = Join-Path $env:TEMP 'r39-release-stress-last.log'
if (-not (Test-Path -LiteralPath $stressLog -PathType Leaf)) {
    throw "Verified stress transcript is missing: $stressLog"
}
$stressText = Get-Content -LiteralPath $stressLog -Raw -Encoding UTF8
foreach ($expected in @(
    'proxy_lifecycle_r39_owner_thread_join_rebind_100_generations',
    'proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier'
)) {
    if ($stressText -notmatch [regex]::Escape($expected)) {
        throw "Packaging refused: stress transcript is missing expected test: $expected"
    }
}
if ($stressText -notmatch '(?m)^running\s+2\s+tests\s*$' -or
    $stressText -notmatch 'test result:\s+ok\.\s+2 passed;\s+0 failed;') {
    throw "Packaging refused: stress transcript does not prove running 2 tests with 2 passed / 0 failed: $stressLog"
}
Write-Host "Lifecycle transcript proof: PASS ($stressLog)" -ForegroundColor Green

# Tauri release embeds frontend/dist. Require the real production asset and reject
# the debug fallback placeholder before invoking the bundler.
$frontendIndex = Join-Path $repoRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "Packaging refused: production frontend is missing: $frontendIndex"
}
$frontendIndexText = Get-Content -LiteralPath $frontendIndex -Raw -Encoding UTF8
if ($frontendIndexText -match 'dev placeholder|Frontend not built|前端未构建') {
    throw 'Packaging refused: frontend/dist/index.html is still the debug placeholder.'
}
Write-Host "Frontend production preflight: PASS ($frontendIndex)" -ForegroundColor Green

$tauriAvailable = $false
try {
    & $cargoExe 'tauri' '--version' *> $null
    $tauriAvailable = ($LASTEXITCODE -eq 0)
} catch {
    $tauriAvailable = $false
}
if (-not $tauriAvailable) {
    if ($SkipTauriInstall) {
        throw 'cargo-tauri is unavailable and -SkipTauriInstall was specified.'
    }
    Write-Host "`nInstalling Tauri CLI v2 into V:-local CARGO_HOME (one-time)..." -ForegroundColor Yellow
    Invoke-Checked $cargoExe 'install' 'tauri-cli' '--version' '^2' '--locked'
}
$tauriVersion = (& $cargoExe tauri --version).Trim()
Write-Host "Tauri CLI    : $tauriVersion"

$bundles = if ($WithMsi) { 'nsis,msi' } else { 'nsis' }
Write-Host "`nBuilding verified Windows bundle(s): $bundles" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked $cargoExe 'tauri' 'build' '--target' $target '--bundles' $bundles
} finally {
    Pop-Location
}

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "Version manifest is missing: $versionPath"
}
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+39' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r39\$safeVersion-verified"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$bundleRoot = Join-Path $env:CARGO_TARGET_DIR "$target\release\bundle"
$copied = [System.Collections.Generic.List[string]]::new()

$nsisDir = Join-Path $bundleRoot 'nsis'
$nsisSource = Get-ChildItem -LiteralPath $nsisDir -File -Filter '*.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $nsisSource) {
    throw "Tauri reported success but no NSIS setup executable was found under $nsisDir"
}
$nsisDest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64-Setup.exe"
Copy-Item -LiteralPath $nsisSource.FullName -Destination $nsisDest -Force
$copied.Add($nsisDest)

if ($WithMsi) {
    $msiDir = Join-Path $bundleRoot 'msi'
    $msiSource = Get-ChildItem -LiteralPath $msiDir -File -Filter '*.msi' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $msiSource) {
        throw "Tauri reported success but no MSI was found under $msiDir"
    }
    $msiDest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64.msi"
    Copy-Item -LiteralPath $msiSource.FullName -Destination $msiDest -Force
    $copied.Add($msiDest)
}

$stressCopy = Join-Path $outDir 'r39-release-stress-proof.log'
Copy-Item -LiteralPath $stressLog -Destination $stressCopy -Force

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 39
    acceptance = [ordered]@{
        lifecycleTestsVisible = 2
        lifecycleTestsPassed = 2
        lifecycleTestsFailed = 0
        samePortGenerations = 100
        stressTranscript = $stressCopy
        frontendProductionBuild = $true
        cargoCheck = 'passed-before-bundle'
    }
    branch = (git branch --show-current).Trim()
    commit = (git rev-parse HEAD).Trim()
    builtAt = (Get-Date).ToString('o')
    target = $target
    cargoTargetDir = $env:CARGO_TARGET_DIR
    rustupHome = $env:RUSTUP_HOME
    cargoHome = $env:CARGO_HOME
    libclangPath = $env:LIBCLANG_PATH
    bindgenExtraClangArgsPresent = -not [string]::IsNullOrWhiteSpace($env:BINDGEN_EXTRA_CLANG_ARGS)
    tauriCli = $tauriVersion
    bundles = $bundles
    files = @($copied | ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        [ordered]@{
            path = $_
            sha256 = $hash.Hash
            bytes = (Get-Item -LiteralPath $_).Length
        }
    })
}
$manifestPath = Join-Path $outDir 'BUILD-MANIFEST.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "`nR39 VERIFIED LOCAL PACKAGE PASS" -ForegroundColor Green
Write-Host "Output         : $outDir"
Write-Host "Manifest       : $manifestPath"
Write-Host "Stress proof   : $stressCopy"
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
    Write-Host ("    SHA256 {0}" -f $hash.Hash)
}
Write-Host 'Next gate is installed-binary fixed-port 18089 restart/recovery testing; do not switch ports to hide a bind failure.' -ForegroundColor Green
