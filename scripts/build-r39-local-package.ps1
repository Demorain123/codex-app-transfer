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

function Download-Once {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$OutFile,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $OutFile -PathType Leaf)) {
        Write-Host "Downloading $Label to V: (one-time)..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $repoRoot.StartsWith('V:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "r39 local package policy requires the repository on physical V:. Current: $repoRoot"
}

# Keep every project-generated cache/build/temp/package/toolchain byte on V:.
$cacheRoot = 'V:\Codex-App-Transfer-DevCache'
$env:CARGO_HOME = Join-Path $cacheRoot 'cargo-home'
$env:RUSTUP_HOME = Join-Path $cacheRoot 'rustup-home'
$env:CARGO_TARGET_DIR = Join-Path $cacheRoot 'target\r39'
$env:npm_config_cache = Join-Path $cacheRoot 'npm-cache'
$env:NPM_CONFIG_CACHE = $env:npm_config_cache
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:RUSTUP_TOOLCHAIN = 'stable'
$bootstrapDir = Join-Path $cacheRoot 'bootstrap'
$toolsRoot = Join-Path $cacheRoot 'tools'
foreach ($dir in @($env:CARGO_HOME, $env:RUSTUP_HOME, $env:CARGO_TARGET_DIR, $env:npm_config_cache, $env:TEMP, $bootstrapDir, $toolsRoot)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'
$localCargoBin = Join-Path $env:CARGO_HOME 'bin'
$localRustup = Join-Path $localCargoBin 'rustup.exe'
$rustupInit = Join-Path $bootstrapDir 'rustup-init-x86_64.exe'

if (-not (Test-Path -LiteralPath $localRustup -PathType Leaf)) {
    Download-Once 'https://win.rustup.rs/x86_64' $rustupInit 'official rustup-init.exe'
    Write-Host "Bootstrapping V:-local rustup proxies (one-time)..." -ForegroundColor Yellow
    $env:RUSTUP_INIT_SKIP_PATH_CHECK = 'yes'
    try {
        Invoke-Checked $rustupInit '-y' '--no-modify-path' '--profile' 'minimal' '--default-toolchain' 'none' '--default-host' $target
    } finally {
        Remove-Item Env:RUSTUP_INIT_SKIP_PATH_CHECK -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path -LiteralPath $localRustup -PathType Leaf)) {
    throw "V:-local rustup bootstrap did not create $localRustup"
}
$env:PATH = $localCargoBin + ';' + $env:PATH
Invoke-Checked $localRustup 'toolchain' 'install' 'stable' '--profile' 'minimal' '--component' 'rustfmt' '--target' $target

# Packaging must use the exact same V:-resident native toolchain as the fast gate.
$cmakeVersion = '4.4.2'
$ninjaVersion = '1.13.2'
$nasmVersion = '3.02'

$cmakeZip = Join-Path $bootstrapDir "cmake-$cmakeVersion-windows-x86_64.zip"
$cmakeRoot = Join-Path $toolsRoot "cmake-$cmakeVersion-windows-x86_64"
$cmakeExe = Join-Path $cmakeRoot 'bin\cmake.exe'
if (-not (Test-Path -LiteralPath $cmakeExe -PathType Leaf)) {
    Download-Once "https://github.com/Kitware/CMake/releases/download/v$cmakeVersion/cmake-$cmakeVersion-windows-x86_64.zip" $cmakeZip "CMake $cmakeVersion portable ZIP"
    Expand-Archive -LiteralPath $cmakeZip -DestinationPath $toolsRoot -Force
}
if (-not (Test-Path -LiteralPath $cmakeExe -PathType Leaf)) {
    throw "Portable CMake bootstrap failed: $cmakeExe"
}

$ninjaZip = Join-Path $bootstrapDir "ninja-$ninjaVersion-win.zip"
$ninjaRoot = Join-Path $toolsRoot "ninja-$ninjaVersion-win"
$ninjaExe = Join-Path $ninjaRoot 'ninja.exe'
if (-not (Test-Path -LiteralPath $ninjaExe -PathType Leaf)) {
    Download-Once "https://github.com/ninja-build/ninja/releases/download/v$ninjaVersion/ninja-win.zip" $ninjaZip "Ninja $ninjaVersion portable ZIP"
    New-Item -ItemType Directory -Force -Path $ninjaRoot | Out-Null
    Expand-Archive -LiteralPath $ninjaZip -DestinationPath $ninjaRoot -Force
}
if (-not (Test-Path -LiteralPath $ninjaExe -PathType Leaf)) {
    throw "Portable Ninja bootstrap failed: $ninjaExe"
}

$nasmZip = Join-Path $bootstrapDir "nasm-$nasmVersion-win64.zip"
$nasmRoot = Join-Path $toolsRoot "nasm-$nasmVersion-win64"
$nasmExe = Get-ChildItem -LiteralPath $nasmRoot -Filter 'nasm.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $nasmExe) {
    Download-Once "https://www.nasm.us/pub/nasm/releasebuilds/$nasmVersion/win64/nasm-$nasmVersion-win64.zip" $nasmZip "NASM $nasmVersion portable ZIP"
    New-Item -ItemType Directory -Force -Path $nasmRoot | Out-Null
    Expand-Archive -LiteralPath $nasmZip -DestinationPath $nasmRoot -Force
    $nasmExe = Get-ChildItem -LiteralPath $nasmRoot -Filter 'nasm.exe' -File -Recurse | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $nasmExe -or -not (Test-Path -LiteralPath $nasmExe -PathType Leaf)) {
    throw "Portable NASM bootstrap failed under $nasmRoot"
}

$env:PATH = $localCargoBin + ';' + (Split-Path -Parent $cmakeExe) + ';' + (Split-Path -Parent $ninjaExe) + ';' + (Split-Path -Parent $nasmExe) + ';' + $env:PATH
$env:CMAKE_GENERATOR = 'Ninja'
$env:ASM_NASM = $nasmExe
Remove-Item Env:CMAKE_GENERATOR_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:CMAKE_GENERATOR_TOOLSET -ErrorAction SilentlyContinue

if (-not $SkipFastGate) {
    Write-Host "`nRunning local r39 fast gate before packaging..." -ForegroundColor Green
    & (Join-Path $PSScriptRoot 'build-r39-local-fast.ps1') -Frontend
    if ($LASTEXITCODE -ne 0) {
        throw "r39 local fast gate failed with exit code $LASTEXITCODE"
    }
} else {
    Invoke-Checked python 'scripts/apply_r39_unified.py'
    Invoke-Checked cargo 'fmt' '--all'
    Invoke-Checked git 'diff' '--check'
    Invoke-Checked cargo 'fmt' '--all' '--' '--check'
    $nodeModules = Join-Path $repoRoot 'frontend\node_modules'
    if (-not (Test-Path $nodeModules)) {
        Invoke-Checked npm '--prefix' 'frontend' 'ci' '--prefer-offline' '--no-audit'
    }
    Invoke-Checked npm '--prefix' 'frontend' 'run' 'build'
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
    rustupHome = $env:RUSTUP_HOME
    cargoHome = $env:CARGO_HOME
    cmake = $cmakeExe
    ninja = $ninjaExe
    nasm = $nasmExe
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
