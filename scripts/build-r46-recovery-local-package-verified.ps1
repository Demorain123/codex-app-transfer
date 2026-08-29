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
    param([Parameter(Mandatory)][string]$Command,[Parameter(ValueFromRemainingArguments)][string[]]$Arguments)
    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')" }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r46 verified package policy requires repository on physical V:. Current: $repoRoot"
}
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r46 - VERIFIED RECOVERY PACKAGE' -ForegroundColor Green
Write-Host 'This build validates code only; it never runs a real rollback/fork against a user thread.'

$gate = Join-Path $PSScriptRoot 'build-r46-recovery-local-release-stress-v2.ps1'
$gateArgs = @()
if ($SkipLegacyStress) { $gateArgs += '-SkipLegacyStress' }
& $gate @gateArgs
if ($LASTEXITCODE -ne 0) { throw "r46 validation gate failed with exit code $LASTEXITCODE" }

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) { throw 'CARGO_HOME is empty after r46 gate.' }
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) { throw "cargo.exe not found: $cargoExe" }

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
Write-Host "`nBuilding r46 Windows bundle(s): $bundles" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try { Invoke-Checked $cargoExe 'tauri' 'build' '--target' $target '--bundles' $bundles } finally { Pop-Location }

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=46' -or $versionFile -notmatch 'app_version=2\.4\.5\+46') {
    throw 'Packaging refused: r46 version stamp mismatch.'
}
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+46' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r46-thread-recovery\$safeVersion-verified"
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

foreach ($proof in @(
    (Join-Path $env:TEMP 'r46-model-switch-forensics-proof-last.log'),
    (Join-Path $env:TEMP 'r46-thread-recovery-proof-last.log'),
    (Join-Path $env:TEMP 'r45-model-switch-continuity-proof-last.log')
)) {
    if (Test-Path -LiteralPath $proof -PathType Leaf) {
        Copy-Item -LiteralPath $proof -Destination (Join-Path $outDir (Split-Path $proof -Leaf)) -Force
    }
}
Copy-Item -LiteralPath (Join-Path $repoRoot 'scripts\README-R46.md') -Destination (Join-Path $outDir 'README-R46.md') -Force

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 46
    branch = (git branch --show-current).Trim()
    commit = (git rev-parse HEAD).Trim()
    builtAt = (Get-Date).ToString('o')
    target = $target
    tauriCli = $tauriVersion
    bundles = $bundles
    safety = [ordered]@{
        realThreadRecoveryExecutedDuringBuild = $false
        sameThreadMaxRewindPerClick = 1
        backupBeforeMutation = 'rollout + current Codex state DB (+ sidecars when present)'
        workspaceFilesChangedByRecovery = $false
        preferredRecoveryApi = 'thread/revert'
        oldCliFallback = 'thread/rollback(numTurns=1), method-not-found only'
        nonDestructiveFallback = 'thread/fork'
    }
    acceptance = [ordered]@{
        inheritedR45Gate = 'passed'
        r46ForensicsTests = 'passed'
        r46RecoveryTests = 'passed'
        frontendProductionBuild = 'passed'
        windowsCargoCheck = 'passed'
        realEnvironmentOldThreadRecovery = 'NOT RUN - requires explicit user click after install'
    }
    files = @($copied | ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        [ordered]@{ path = $_; sha256 = $hash.Hash; bytes = (Get-Item -LiteralPath $_).Length }
    })
}
$manifestPath = Join-Path $outDir 'BUILD-MANIFEST.json'
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "`nR46 VERIFIED RECOVERY PACKAGE PASS" -ForegroundColor Green
Write-Host "Output   : $outDir"
Write-Host "Manifest : $manifestPath"
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
    Write-Host ("    SHA256 {0}" -f $hash.Hash)
}
Write-Host 'After install: open 路由 → 全链路健康 → 旧会话恢复 → read-only preview first.' -ForegroundColor Yellow
