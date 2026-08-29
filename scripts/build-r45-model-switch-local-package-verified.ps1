#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$WithMsi,
    [switch]$SkipTauriInstall,
    [switch]$SkipLegacyStress
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
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')" }
}

function Assert-Proof {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$ExpectedTests,
        [Parameter(Mandatory)][int]$ExpectedCount,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Packaging refused: missing proof: $Path" }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    foreach ($expected in $ExpectedTests) {
        if ($text -notmatch [regex]::Escape($expected)) { throw "Packaging refused: $Label missing test: $expected" }
    }
    if ($text -notmatch ("test result:\s+ok\.\s+{0} passed;\s+0 failed;" -f $ExpectedCount)) {
        throw "Packaging refused: $Label does not prove $ExpectedCount passed / 0 failed"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r45 verified package policy requires repository on physical V:. Current: $repoRoot"
}
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r45 - VERIFIED LOCAL PACKAGE' -ForegroundColor Green
Write-Host 'Scope: r43 verified base + model-switch continuity + compaction model rebind + semantic terminal lifecycle.'

$gate = Join-Path $PSScriptRoot 'build-r45-model-switch-local-release-stress.ps1'
if ($SkipLegacyStress) {
    & $gate -SkipLegacyStress
} else {
    & $gate
}
if ($LASTEXITCODE -ne 0) { throw "r45 verified gate failed with exit code $LASTEXITCODE" }

$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

$r45Log = Join-Path $env:TEMP 'r45-model-switch-continuity-proof-last.log'
Assert-Proof -Path $r45Log -ExpectedTests @(
    'r45_compaction_helper_detection_is_structural',
    'r45_semantic_terminal_detector_handles_chunk_boundaries',
    'r45_auxiliary_requests_do_not_advance_main_model'
) -ExpectedCount 3 -Label 'r45 model-switch/terminal'

Write-Host "`nBuilding production frontend..." -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'frontend')
try { Invoke-Checked 'npm.cmd' 'run' 'build' } finally { Pop-Location }
$frontendIndex = Join-Path $repoRoot 'frontend\dist\index.html'
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) { throw "Production frontend missing: $frontendIndex" }

$tauriAvailable = $false
try {
    & $cargoExe 'tauri' '--version' *> $null
    $tauriAvailable = ($LASTEXITCODE -eq 0)
} catch { $tauriAvailable = $false }
if (-not $tauriAvailable) {
    if ($SkipTauriInstall) { throw 'cargo-tauri unavailable and -SkipTauriInstall specified.' }
    Invoke-Checked $cargoExe 'install' 'tauri-cli' '--version' '^2' '--locked'
}
$tauriVersion = (& $cargoExe tauri --version).Trim()

$bundles = if ($WithMsi) { 'nsis,msi' } else { 'nsis' }
Write-Host "`nBuilding r45 Windows bundle(s): $bundles" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try { Invoke-Checked $cargoExe 'tauri' 'build' '--target' $target '--bundles' $bundles } finally { Pop-Location }

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=45' -or $versionFile -notmatch 'app_version=2\.4\.5\+45') {
    throw 'Packaging refused: r45 version stamp mismatch.'
}
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+45' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r45-model-switch\$safeVersion-verified"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$bundleRoot = Join-Path $env:CARGO_TARGET_DIR "$target\release\bundle"
$copied = [System.Collections.Generic.List[string]]::new()
$nsisDir = Join-Path $bundleRoot 'nsis'
$nsisSource = Get-ChildItem -LiteralPath $nsisDir -File -Filter '*.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $nsisSource) { throw "No NSIS setup executable under $nsisDir" }
$nsisDest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64-Setup.exe"
Copy-Item -LiteralPath $nsisSource.FullName -Destination $nsisDest -Force
$copied.Add($nsisDest)

if ($WithMsi) {
    $msiDir = Join-Path $bundleRoot 'msi'
    $msiSource = Get-ChildItem -LiteralPath $msiDir -File -Filter '*.msi' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $msiSource) { throw "No MSI under $msiDir" }
    $msiDest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64.msi"
    Copy-Item -LiteralPath $msiSource.FullName -Destination $msiDest -Force
    $copied.Add($msiDest)
}

Copy-Item -LiteralPath $r45Log -Destination (Join-Path $outDir 'r45-model-switch-continuity-proof.log') -Force

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 45
    architecture = 'r43 verified base + r45 cross-model continuity + Responses semantic-terminal lifecycle'
    acceptance = [ordered]@{
        inheritedR43Gate = 'passed'
        r45FocusedTestsPassed = 3
        cargoCheck = 'passed-before-bundle'
        frontendProductionBuild = $true
        realEnvironmentCrossModelAcceptance = 'not yet run'
    }
    branch = (git branch --show-current).Trim()
    commit = (git rev-parse HEAD).Trim()
    builtAt = (Get-Date).ToString('o')
    target = $target
    tauriCli = $tauriVersion
    bundles = $bundles
    files = @($copied | ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        [ordered]@{ path = $_; sha256 = $hash.Hash; bytes = (Get-Item -LiteralPath $_).Length }
    })
}
$manifestPath = Join-Path $outDir 'BUILD-MANIFEST.json'
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "`nR45 VERIFIED LOCAL PACKAGE PASS" -ForegroundColor Green
Write-Host "Output   : $outDir"
Write-Host "Manifest : $manifestPath"
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
    Write-Host ("    SHA256 {0}" -f $hash.Hash)
}
Write-Host 'Next acceptance: exercise Luna -> Grok and Grok -> Luna in the same long thread, including automatic compaction.' -ForegroundColor Green
