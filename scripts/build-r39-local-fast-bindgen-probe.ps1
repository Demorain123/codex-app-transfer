#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$Frontend,
    [switch]$SkipCargoCheck,
    [switch]$SkipStress
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# r39 diagnostic wrapper for the V:-local libclang path.
# The compact PyPI libclang wheel gives bindgen a loadable libclang.dll, but it
# does not initialize the Visual Studio developer environment. Import the real
# MSVC/Windows SDK INCLUDE/LIB/PATH values through VsDevCmd, then pass the
# discovered include directories to rust-bindgen explicitly.

$preserveNames = @(
    'CARGO_HOME',
    'RUSTUP_HOME',
    'CARGO_TARGET_DIR',
    'npm_config_cache',
    'NPM_CONFIG_CACHE',
    'PIP_CACHE_DIR',
    'TEMP',
    'TMP',
    'RUSTUP_TOOLCHAIN',
    'CODEX_APP_TRANSFER_LOCAL_BUILD',
    'LIBCLANG_PATH',
    'CMAKE_GENERATOR',
    'ASM_NASM'
)
$preserved = @{}
foreach ($name in $preserveNames) {
    $preserved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$pathBeforeVsDevCmd = $env:PATH

$programFilesX86 = ${env:ProgramFiles(x86)}
if ([string]::IsNullOrWhiteSpace($programFilesX86)) {
    throw 'ProgramFiles(x86) is unavailable; cannot locate Visual Studio Installer/vswhere.exe.'
}

$vswhere = Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "vswhere.exe was not found at $vswhere"
}

Write-Host 'Codex App Transfer r39 - bindgen/MSVC environment probe' -ForegroundColor Green
Write-Host "vswhere      : $vswhere"

$installationPath = @(
    & $vswhere '-latest' '-products' '*' '-requires' 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' '-property' 'installationPath'
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($installationPath)) {
    throw 'No Visual Studio/Build Tools installation with VC x64/x86 tools was found by vswhere.'
}
$installationPath = $installationPath.Trim()
$vsDevCmd = Join-Path $installationPath 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsDevCmd -PathType Leaf)) {
    throw "VsDevCmd.bat was not found at $vsDevCmd"
}

Write-Host "VS install    : $installationPath"
Write-Host "VsDevCmd      : $vsDevCmd"
Write-Host 'Importing x64 MSVC + Windows SDK developer environment into this process...' -ForegroundColor Yellow

$cmdLine = "call `"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
$devEnvLines = & $env:ComSpec /d /s /c $cmdLine
if ($LASTEXITCODE -ne 0) {
    throw "VsDevCmd.bat failed with exit code $LASTEXITCODE"
}

foreach ($line in $devEnvLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}

# Keep the V:-local build/cache/tool paths already selected by the caller, while
# retaining the Visual Studio paths that VsDevCmd prepended/discovered.
$vsDevPath = $env:PATH
if (-not [string]::IsNullOrWhiteSpace($pathBeforeVsDevCmd)) {
    $env:PATH = $pathBeforeVsDevCmd + ';' + $vsDevPath
}
foreach ($name in $preserveNames) {
    $value = $preserved[$name]
    if ($null -ne $value) {
        [Environment]::SetEnvironmentVariable($name, [string]$value, 'Process')
    }
}

if ([string]::IsNullOrWhiteSpace($env:INCLUDE)) {
    throw 'VsDevCmd completed, but INCLUDE is empty. Bindgen cannot locate MSVC/Windows SDK headers.'
}

$includeDirs = @(
    $env:INCLUDE -split ';' |
        ForEach-Object { $_.Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_ -PathType Container) } |
        Select-Object -Unique
)
if ($includeDirs.Count -eq 0) {
    throw 'VsDevCmd produced INCLUDE, but none of its directories exist.'
}

Write-Host "INCLUDE dirs  : $($includeDirs.Count)"
foreach ($dir in $includeDirs) {
    Write-Host "  $dir" -ForegroundColor DarkGray
}

$requiredHeaders = @('stddef.h', 'stdint.h', 'intrin.h', 'windows.h')
foreach ($header in $requiredHeaders) {
    $hit = $includeDirs |
        ForEach-Object { Join-Path $_ $header } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $hit) {
        throw "MSVC/Windows SDK preflight failed: $header was not found in INCLUDE."
    }
    Write-Host ("{0,-13}: {1}" -f $header, $hit) -ForegroundColor Green
}

# Bindgen officially supports BINDGEN_EXTRA_CLANG_ARGS for end-user system
# include paths. Use forward slashes so shlex parsing does not reinterpret
# Windows backslashes inside quoted arguments.
$clangArgs = [System.Collections.Generic.List[string]]::new()
$clangArgs.Add('--target=x86_64-pc-windows-msvc')
foreach ($dir in $includeDirs) {
    $clangPath = $dir.Replace('\', '/')
    $clangArgs.Add(('-I"{0}"' -f $clangPath))
}
$env:BINDGEN_EXTRA_CLANG_ARGS = $clangArgs -join ' '

Write-Host "BINDGEN args  : --target=x86_64-pc-windows-msvc + $($includeDirs.Count) include dirs" -ForegroundColor Green
Write-Host 'Launching the normal r39 LOCAL FAST gate with the probed environment...' -ForegroundColor Green

$forward = @{}
if ($Frontend) { $forward['Frontend'] = $true }
if ($SkipCargoCheck) { $forward['SkipCargoCheck'] = $true }
if ($SkipStress) { $forward['SkipStress'] = $true }

$fastGate = Join-Path $PSScriptRoot 'build-r39-local-fast.ps1'
& $fastGate @forward
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
