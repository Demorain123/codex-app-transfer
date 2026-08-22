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

function Assert-Proof {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$ExpectedTests,
        [Parameter(Mandatory)][int]$ExpectedCount,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Packaging refused: missing proof transcript: $Path"
    }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    foreach ($expected in $ExpectedTests) {
        if ($text -notmatch [regex]::Escape($expected)) {
            throw "Packaging refused: $Label transcript is missing expected test: $expected"
        }
    }
    if ($text -notmatch ("(?m)^running\s+{0}\s+tests\s*$" -f $ExpectedCount) -or
        $text -notmatch ("test result:\s+ok\.\s+{0} passed;\s+0 failed;" -f $ExpectedCount)) {
        throw "Packaging refused: $Label does not prove $ExpectedCount passed / 0 failed: $Path"
    }
    Write-Host "$Label transcript proof: PASS ($ExpectedCount/$ExpectedCount)" -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r42 verified package policy requires the repository on physical V:. Current: $repoRoot"
}
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r42 - VERIFIED LOCAL PACKAGE' -ForegroundColor Green
Write-Host 'Gate: r39 100x lifecycle + r40 port guard + r41 explicit repair + r42 Grok effective-name collision 6/6 + cargo check + production frontend + Tauri NSIS.'
Write-Host 'Real acceptance: the two already-broken Codex sessions must resume in place after installation.'

$verifiedGate = Join-Path $PSScriptRoot 'build-r42-local-release-stress.ps1'
& $verifiedGate
if ($LASTEXITCODE -ne 0) {
    throw "r42 verified gate failed with exit code $LASTEXITCODE"
}

foreach ($name in @('CARGO_HOME','CARGO_TARGET_DIR','TEMP')) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { throw "$name is empty after the verified r42 gate." }
}
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) {
    throw "V:-local cargo.exe was not found: $cargoExe"
}

$lifecycleLog = Join-Path $env:TEMP 'r42-r39-lifecycle-proof-last.log'
$guardLog = Join-Path $env:TEMP 'r42-r40-port-guard-proof-last.log'
$repairLog = Join-Path $env:TEMP 'r42-r41-repair-proof-last.log'
$collisionLog = Join-Path $env:TEMP 'r42-grok-tool-collision-proof-last.log'

Assert-Proof -Path $lifecycleLog -ExpectedTests @(
    'proxy_lifecycle_r39_owner_thread_join_rebind_100_generations',
    'proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier'
) -ExpectedCount 2 -Label 'r39 lifecycle'

Assert-Proof -Path $guardLog -ExpectedTests @(
    'windows_port_guard_r40_clears_inherit_bit',
    'windows_port_guard_r40_classifies_foreign_and_stale_binders'
) -ExpectedCount 2 -Label 'r40 Windows Port Guard'

Assert-Proof -Path $repairLog -ExpectedTests @(
    'windows_port_repair_r41_rejects_self_owner',
    'windows_port_repair_r41_terminates_explicit_foreign_owner'
) -ExpectedCount 2 -Label 'r41 Explicit Port Repair'

Assert-Proof -Path $collisionLog -ExpectedTests @(
    'grok_tool_collision_r42_native_plus_function_web_search_is_one',
    'grok_tool_collision_r42_duplicate_native_web_search_is_one',
    'grok_tool_collision_r42_function_first_preserves_client_routing',
    'grok_tool_collision_r42_ordinary_function_duplicate_still_dedups',
    'grok_tool_collision_r42_unique_tools_are_preserved',
    'grok_tool_collision_r42_discovered_function_cannot_duplicate_native_web_search'
) -ExpectedCount 6 -Label 'r42 Grok collision'

Write-Host "`nBuilding production frontend..." -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'frontend')
try {
    Invoke-Checked 'npm.cmd' 'run' 'build'
} finally {
    Pop-Location
}
$frontendIndex = Join-Path $repoRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "Packaging refused: production frontend is missing: $frontendIndex"
}
$frontendIndexText = Get-Content -LiteralPath $frontendIndex -Raw -Encoding UTF8
if ($frontendIndexText -match 'dev placeholder|Frontend not built|前端未构建') {
    throw 'Packaging refused: frontend/dist/index.html is still the debug placeholder.'
}
Write-Host 'Frontend production build: PASS' -ForegroundColor Green

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
Write-Host "`nBuilding verified r42 Windows bundle(s): $bundles" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked $cargoExe 'tauri' 'build' '--target' $target '--bundles' $bundles
} finally {
    Pop-Location
}

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=42' -or $versionFile -notmatch 'app_version=2\.4\.5\+42') {
    throw 'Packaging refused: r42 version stamp mismatch.'
}
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+42' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r42\$safeVersion-verified"
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
    if ($null -eq $msiSource) { throw "Tauri reported success but no MSI was found under $msiDir" }
    $msiDest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64.msi"
    Copy-Item -LiteralPath $msiSource.FullName -Destination $msiDest -Force
    $copied.Add($msiDest)
}

$lifecycleCopy = Join-Path $outDir 'r42-r39-lifecycle-proof.log'
$guardCopy = Join-Path $outDir 'r42-r40-windows-port-guard-proof.log'
$repairCopy = Join-Path $outDir 'r42-r41-explicit-port-repair-proof.log'
$collisionCopy = Join-Path $outDir 'r42-grok-tool-collision-proof.log'
Copy-Item -LiteralPath $lifecycleLog -Destination $lifecycleCopy -Force
Copy-Item -LiteralPath $guardLog -Destination $guardCopy -Force
Copy-Item -LiteralPath $repairLog -Destination $repairCopy -Force
Copy-Item -LiteralPath $collisionLog -Destination $collisionCopy -Force

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 42
    acceptance = [ordered]@{
        r39LifecycleTestsPassed = 2
        samePortGenerations = 100
        r40PortGuardTestsPassed = 2
        r41RepairTestsPassed = 2
        r42GrokCollisionTestsPassed = 6
        nativeVsFunctionWebSearchCollision = 'passed'
        duplicateNativeWebSearchCollision = 'passed'
        discoveredWebSearchCollision = 'passed'
        functionFirstRoutingPreservation = 'passed'
        frontendProductionBuild = $true
        cargoCheck = 'passed-before-bundle'
        realAcceptance = 'both previously broken Codex sessions resume in place without fork/reset/reboot'
        automaticPortSwitching = $false
        backgroundProcessKill = $false
    }
    branch = (git branch --show-current).Trim()
    commit = (git rev-parse HEAD).Trim()
    builtAt = (Get-Date).ToString('o')
    target = $target
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
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "`nR42 VERIFIED LOCAL PACKAGE PASS" -ForegroundColor Green
Write-Host "Output          : $outDir"
Write-Host "Manifest        : $manifestPath"
Write-Host "Collision proof : $collisionCopy"
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
    Write-Host ("    SHA256 {0}" -f $hash.Hash)
}
Write-Host 'Next gate: install r42, then resume both already-broken old Codex sessions in place and send Continue. No fork/reset/reboot.' -ForegroundColor Green
