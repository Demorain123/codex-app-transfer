#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$WithMsi,
    [switch]$SkipFastGate,
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
    throw "r39 local package policy requires the repository on physical V:. Current: $repoRoot"
}

# Keep every project-generated cache/build/temp/package byte on V:.
$cacheRoot = 'V:\Codex-App-Transfer-DevCache'
$env:CARGO_HOME = Join-Path $cacheRoot 'cargo-home'
$env:CARGO_TARGET_DIR = Join-Path $cacheRoot 'target\r39'
$env:npm_config_cache = Join-Path $cacheRoot 'npm-cache'
$env:NPM_CONFIG_CACHE = $env:npm_config_cache
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
foreach ($dir in @($env:CARGO_HOME, $env:CARGO_TARGET_DIR, $env:npm_config_cache, $env:TEMP)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

if (-not $SkipFastGate) {
    Write-Host "`nRunning local r39 fast gate before packaging..." -ForegroundColor Green
    & (Join-Path $PSScriptRoot 'build-r39-local-fast.ps1') -Frontend
    if ($LASTEXITCODE -ne 0) { throw "r39 fast gate failed before package build" }
} else {
    Invoke-Checked python 'scripts/apply_r39_unified.py'
}

$tauriAvailable = $false
try {
    & cargo tauri --version *> $null
    $tauriAvailable = ($LASTEXITCODE -eq 0)
} catch {
    $tauriAvailable = $false
}
if (-not $tauriAvailable) {
    if ($SkipTauriInstall) {
        throw 'cargo-tauri is unavailable and -SkipTauriInstall was specified.'
    }
    Write-Host "`nInstalling Tauri CLI v2 into V: CARGO_HOME (one-time cost)..." -ForegroundColor Yellow
    Invoke-Checked cargo 'install' 'tauri-cli' '--version' '^2' '--locked'
}

$bundles = if ($WithMsi) { 'nsis,msi' } else { 'nsis' }
Write-Host "`nBuilding local Windows bundle(s): $bundles" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked cargo 'tauri' 'build' '--target' $target '--bundles' $bundles
} finally {
    Pop-Location
}

$versionFile = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+39' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r39\$safeVersion"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$bundleRoot = Join-Path $env:CARGO_TARGET_DIR "$target\release\bundle"
$copied = [System.Collections.Generic.List[string]]::new()

$nsisDir = Join-Path $bundleRoot 'nsis'
if (Test-Path $nsisDir) {
    Get-ChildItem -LiteralPath $nsisDir -File -Filter '*.exe' | ForEach-Object {
        $dest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64-Setup.exe"
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        $copied.Add($dest)
    }
}

if ($WithMsi) {
    $msiDir = Join-Path $bundleRoot 'msi'
    if (Test-Path $msiDir) {
        Get-ChildItem -LiteralPath $msiDir -File -Filter '*.msi' | ForEach-Object {
            $dest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-Windows-x64.msi"
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
            $copied.Add($dest)
        }
    }
}

if ($copied.Count -eq 0) {
    throw "Tauri build returned success but no requested bundle found under $bundleRoot"
}

$manifest = [ordered]@{
    version = $appVersion
    branch = (git branch --show-current).Trim()
    commit = (git rev-parse HEAD).Trim()
    builtAt = (Get-Date).ToString('o')
    cargoTargetDir = $env:CARGO_TARGET_DIR
    bundles = $bundles
    files = @($copied | ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        [ordered]@{ path = $_; sha256 = $hash.Hash; bytes = (Get-Item $_).Length }
    })
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outDir 'BUILD-MANIFEST.json') -Encoding UTF8

Write-Host "`nLOCAL PACKAGE PASS" -ForegroundColor Green
Write-Host "Output: $outDir"
foreach ($file in $copied) {
    $item = Get-Item $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
}
Write-Host 'Default is NSIS-only to minimize iteration time; use -WithMsi only for release-candidate parity.' -ForegroundColor Green
