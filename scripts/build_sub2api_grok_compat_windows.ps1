#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipTauriInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Command,

        [Parameter(ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $Command $($Arguments -join ' ')"
    }
}

function Require-Command {
    param([Parameter(Mandatory)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = 'x86_64-pc-windows-msvc'
$outDir = Join-Path $repoRoot 'dist\sub2api-grok-compat-windows'

Set-Location $repoRoot

Write-Host 'Sub2API Grok Compat - Windows local build' -ForegroundColor Green
Write-Host "Repository : $repoRoot"
Write-Host "Target     : $target"

Require-Command git
Require-Command node
Require-Command npm
Require-Command rustc
Require-Command cargo
Require-Command rustup

Write-Host "`nToolchain:" -ForegroundColor Yellow
Invoke-Checked git '--version'
Invoke-Checked node '--version'
Invoke-Checked npm '--version'
Invoke-Checked rustc '--version'
Invoke-Checked cargo '--version'

# This project is Tauri 2.x and the CI currently builds with Node 20 + stable Rust.
Invoke-Checked rustup 'target' 'add' $target

$tauriAvailable = $false
try {
    & cargo tauri --version *> $null
    $tauriAvailable = ($LASTEXITCODE -eq 0)
}
catch {
    $tauriAvailable = $false
}

if (-not $tauriAvailable) {
    if ($SkipTauriInstall) {
        throw 'cargo-tauri is not installed and -SkipTauriInstall was specified.'
    }

    Write-Host "`ncargo-tauri is missing. Installing Tauri CLI v2 (first install can take a while)..." -ForegroundColor Yellow
    Invoke-Checked cargo 'install' 'tauri-cli' '--version' '^2' '--locked'
}
else {
    Write-Host "`ncargo-tauri already installed:" -ForegroundColor Yellow
    Invoke-Checked cargo 'tauri' '--version'
}

Write-Host "`nBuilding frontend..." -ForegroundColor Green
Invoke-Checked npm '--prefix' 'frontend' 'ci'
Invoke-Checked npm '--prefix' 'frontend' 'run' 'build'

if (-not $SkipTests) {
    Write-Host "`nRunning Sub2API Grok compatibility tests..." -ForegroundColor Green
    Invoke-Checked cargo 'test' '-p' 'codex-app-transfer-adapters' 'sub2api_grok_compat' '--' '--nocapture'
}
else {
    Write-Host "`nSkipping tests because -SkipTests was specified." -ForegroundColor Yellow
}

Write-Host "`nBuilding Windows NSIS + MSI bundles..." -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try {
    Invoke-Checked cargo 'tauri' 'build' '--target' $target '--bundles' 'nsis,msi'
}
finally {
    Pop-Location
}

$metadataRaw = & cargo metadata --no-deps --format-version 1
if ($LASTEXITCODE -ne 0) {
    throw 'cargo metadata failed while locating build output.'
}
$metadata = $metadataRaw | ConvertFrom-Json
$bundleRoot = Join-Path ([string]$metadata.target_directory) "$target\release\bundle"
$nsisDir = Join-Path $bundleRoot 'nsis'
$msiDir = Join-Path $bundleRoot 'msi'

New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$copied = [System.Collections.Generic.List[string]]::new()

if (Test-Path $nsisDir) {
    Get-ChildItem -LiteralPath $nsisDir -File -Filter '*.exe' | ForEach-Object {
        $dest = Join-Path $outDir 'Sub2API-Grok-Compat-Windows-x64-Setup.exe'
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        $copied.Add($dest)
    }
}

if (Test-Path $msiDir) {
    Get-ChildItem -LiteralPath $msiDir -File -Filter '*.msi' | ForEach-Object {
        $dest = Join-Path $outDir 'Sub2API-Grok-Compat-Windows-x64.msi'
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        $copied.Add($dest)
    }
}

if ($copied.Count -eq 0) {
    throw "Build completed but no .exe/.msi bundles were found under: $bundleRoot"
}

Write-Host "`nBuild complete." -ForegroundColor Green
Write-Host "Output directory: $outDir" -ForegroundColor Green
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    Write-Host ("  {0}  ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
}

Write-Host "`nNext runtime topology:" -ForegroundColor Yellow
Write-Host '  Codex Desktop -> 127.0.0.1:18080 -> this compat proxy -> 127.0.0.1:8089/v1 -> Sub2API'
