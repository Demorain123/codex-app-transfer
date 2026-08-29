#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$SkipTauriInstall,
    [switch]$ForceMaterialize,
    [switch]$ForceFrontendBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "`n> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Command @Arguments
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) { throw "Command failed ($exitCode): $Command $($Arguments -join ' ')" }
}

function Parse-RustVersion {
    param([Parameter(Mandatory)][string]$Line)
    if ($Line -notmatch '^rustc\s+(\d+)\.(\d+)\.(\d+)') { throw "Unable to parse rustc version: $Line" }
    [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
}

function Get-StableRustVersion {
    param([Parameter(Mandatory)][string]$Rustup)
    $global:LASTEXITCODE = 0
    $output = @(& $Rustup run stable rustc --version 2>&1)
    $exitCode = $global:LASTEXITCODE
    $line = $output | Select-Object -First 1
    if ($exitCode -ne 0 -or -not $line) { return $null }
    Parse-RustVersion ([string]$line).Trim()
}

function Invoke-StableCargo {
    param(
        [Parameter(Mandatory)][string]$Rustup,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "`n> rustup run stable cargo $($Arguments -join ' ')" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Rustup run stable cargo @Arguments
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) { throw "Command failed ($exitCode): rustup run stable cargo $($Arguments -join ' ')" }
}

function Find-FirstFile {
    param([string[]]$Roots,[string[]]$Names)
    foreach ($root in $Roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        foreach ($name in $Names) {
            $found = Get-ChildItem -LiteralPath $root -Filter $name -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    return $null
}

function Import-VsDevEnvironment {
    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not $programFilesX86) { return $false }
    $vswhere = Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) { return $false }
    $installationPath = @(& $vswhere '-latest' '-products' '*' '-requires' 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' '-property' 'installationPath') |
        Where-Object { $_ } | Select-Object -First 1
    if (-not $installationPath) { return $false }
    $vsDevCmd = Join-Path ([string]$installationPath).Trim() 'Common7\Tools\VsDevCmd.bat'
    if (-not (Test-Path -LiteralPath $vsDevCmd -PathType Leaf)) { return $false }

    $preserve = @{}
    foreach ($name in @('CARGO_HOME','RUSTUP_HOME','CARGO_TARGET_DIR','npm_config_cache','NPM_CONFIG_CACHE','PIP_CACHE_DIR','TEMP','TMP','RUSTUP_TOOLCHAIN','LIBCLANG_PATH','CMAKE','CMAKE_GENERATOR','ASM_NASM','CMAKE_ASM_NASM_COMPILER')) {
        $preserve[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
    }
    $pathBefore = $env:PATH
    $cmdLine = "call `"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
    $lines = & $env:ComSpec /d /s /c $cmdLine
    if ($LASTEXITCODE -ne 0) { return $false }
    foreach ($line in $lines) {
        if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process') }
    }
    $vsPath = $env:PATH
    $env:PATH = "$pathBefore;$vsPath"
    foreach ($name in $preserve.Keys) {
        if ($null -ne $preserve[$name]) { [Environment]::SetEnvironmentVariable($name,[string]$preserve[$name],'Process') }
    }

    if ($env:INCLUDE) {
        $includeDirs = @($env:INCLUDE -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique)
        if ($includeDirs.Count -gt 0) {
            $clangArgs = [System.Collections.Generic.List[string]]::new()
            $clangArgs.Add('--target=x86_64-pc-windows-msvc')
            foreach ($dir in $includeDirs) { $clangArgs.Add('-I"' + $dir.Replace('\','/') + '"') }
            $env:BINDGEN_EXTRA_CLANG_ARGS = $clangArgs -join ' '
        }
    }
    Write-Host "Reused Visual Studio developer environment: $installationPath" -ForegroundColor Green
    return $true
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'
$minimumRust = [version]'1.95.0'
$legacyCache = 'V:\Codex-App-Transfer-DevCache'
$legacyTools = Join-Path $legacyCache 'tools'
$legacyReused = Test-Path -LiteralPath $legacyCache -PathType Container

Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Codex App Transfer r46 - FAST REAL-USE BUILD' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Purpose: get to real old-thread testing as fast as possible.'
Write-Host 'Skipped: Rust unit tests / cargo check / legacy stress / release proof.' -ForegroundColor Yellow
Write-Host 'Successful stages and the proven r39-r42 V: build cache are reused automatically.' -ForegroundColor Green

Write-Host "`n[0/9] Reuse r39-r42 local build environment" -ForegroundColor Green
if ($legacyReused) {
    $env:CARGO_HOME = Join-Path $legacyCache 'cargo-home'
    $env:RUSTUP_HOME = Join-Path $legacyCache 'rustup-home'
    $env:CARGO_TARGET_DIR = Join-Path $legacyCache 'target\r39'
    $env:npm_config_cache = Join-Path $legacyCache 'npm-cache'
    $env:NPM_CONFIG_CACHE = $env:npm_config_cache
    $env:PIP_CACHE_DIR = Join-Path $legacyCache 'pip-cache'
    $env:TEMP = Join-Path $legacyCache 'tmp'
    $env:TMP = $env:TEMP
    $env:RUSTUP_TOOLCHAIN = 'stable'
    foreach ($dir in @($env:CARGO_HOME,$env:RUSTUP_HOME,$env:CARGO_TARGET_DIR,$env:npm_config_cache,$env:PIP_CACHE_DIR,$env:TEMP)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $legacyCargoBin = Join-Path $env:CARGO_HOME 'bin'
    $env:PATH = "$legacyCargoBin;$env:PATH"
    Write-Host "Legacy cache FOUND: $legacyCache" -ForegroundColor Green
    Write-Host "Cargo target reuse : $env:CARGO_TARGET_DIR" -ForegroundColor Green
} else {
    Write-Host 'Legacy r39-r42 cache not found; using current-machine caches.' -ForegroundColor Yellow
}

$legacyCmake = if ($legacyReused) { Find-FirstFile @($legacyTools) @('cmake.exe') } else { $null }
$legacyNinja = if ($legacyReused) { Find-FirstFile @($legacyTools) @('ninja.exe') } else { $null }
$legacyNasm = if ($legacyReused) { Find-FirstFile @($legacyTools) @('nasm.exe') } else { $null }
$legacyLibClang = if ($legacyReused) { Find-FirstFile @($legacyTools) @('libclang.dll','clang.dll') } else { $null }

if ($legacyNinja) {
    $env:PATH = "$(Split-Path -Parent $legacyNinja);$env:PATH"
    $env:CMAKE_GENERATOR = 'Ninja'
    Remove-Item Env:CMAKE_GENERATOR_PLATFORM -ErrorAction SilentlyContinue
    Remove-Item Env:CMAKE_GENERATOR_TOOLSET -ErrorAction SilentlyContinue
    Write-Host "Reusing Ninja      : $legacyNinja" -ForegroundColor Green
}
if ($legacyNasm) {
    $env:PATH = "$(Split-Path -Parent $legacyNasm);$env:PATH"
    $env:ASM_NASM = $legacyNasm
    $env:CMAKE_ASM_NASM_COMPILER = $legacyNasm
    Write-Host "Reusing NASM       : $legacyNasm" -ForegroundColor Green
}
if ($legacyLibClang) {
    $env:LIBCLANG_PATH = Split-Path -Parent $legacyLibClang
    $env:PATH = "$env:LIBCLANG_PATH;$env:PATH"
    Write-Host "Reusing libclang   : $legacyLibClang" -ForegroundColor Green
}
$null = Import-VsDevEnvironment

$versionPath = Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt'
$currentVersion = if (Test-Path -LiteralPath $versionPath -PathType Leaf) { Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 } else { '' }
$recoveryBackend = Join-Path $repoRoot 'src-tauri\src\admin\handlers\thread_recovery.rs'
$alreadyMaterialized = $currentVersion -match 'compat_revision=46' -and $currentVersion -match 'app_version=2\.4\.5\+46' -and (Test-Path -LiteralPath $recoveryBackend -PathType Leaf) -and ((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY')

Write-Host "`n[1/9] Materialize r46" -ForegroundColor Green
if ($alreadyMaterialized -and -not $ForceMaterialize) { Write-Host 'Warm r46 materialization detected; SKIP.' -ForegroundColor Green } else { Invoke-Checked 'python' '.\scripts\apply_r46_unified.py' }
$versionFile = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8
if ($versionFile -notmatch 'compat_revision=46' -or $versionFile -notmatch 'app_version=2\.4\.5\+46') { throw 'r46 materialization completed but version stamp is not 2.4.5+46.' }
Write-Host $versionFile.Trim() -ForegroundColor Green

Write-Host "`n[2/9] Frontend assets" -ForegroundColor Green
$frontendDir = Join-Path $repoRoot 'frontend'
$nodeModules = Join-Path $frontendDir 'node_modules'
$frontendIndex = Join-Path $frontendDir 'dist\index.html'
if ((Test-Path -LiteralPath $frontendIndex -PathType Leaf) -and -not $ForceFrontendBuild) {
    Write-Host "Warm frontend assets detected; SKIP: $frontendIndex" -ForegroundColor Green
} else {
    Push-Location $frontendDir
    try {
        if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) { Invoke-Checked 'npm.cmd' 'ci' }
        Invoke-Checked 'npm.cmd' 'run' 'build'
    } finally { Pop-Location }
    if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) { throw "Frontend build completed but dist/index.html is missing: $frontendIndex" }
}

Write-Host "`n[3/9] Ensure stable Rust >= 1.95" -ForegroundColor Green
$legacyRustup = if ($legacyReused) { Join-Path $env:CARGO_HOME 'bin\rustup.exe' } else { $null }
if ($legacyRustup -and (Test-Path -LiteralPath $legacyRustup -PathType Leaf)) {
    $rustup = $legacyRustup
    Write-Host "Using proven V:-local rustup: $rustup" -ForegroundColor Green
} else {
    $rustupCmd = Get-Command rustup.exe -ErrorAction SilentlyContinue
    if (-not $rustupCmd) { $rustupCmd = Get-Command rustup -ErrorAction SilentlyContinue }
    if (-not $rustupCmd) { throw 'rustup was not found.' }
    $rustup = $rustupCmd.Source
}
$rustVersion = Get-StableRustVersion $rustup
if ($rustVersion -and $rustVersion -ge $minimumRust) {
    Write-Host "Stable Rust already ready: $rustVersion; SKIP rustup update." -ForegroundColor Green
} else {
    Write-Host 'Stable Rust missing/too old; updating stable toolchain...' -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    & $rustup toolchain install stable --profile minimal --target $target
    $rustVersion = Get-StableRustVersion $rustup
    if (-not $rustVersion -or $rustVersion -lt $minimumRust) { throw "Stable Rust is still unavailable or < $minimumRust." }
}
Write-Host "Using stable rustc: $rustVersion" -ForegroundColor Green

Write-Host "`n[4/9] Locate Tauri" -ForegroundColor Green
$tauriAvailable = $false
try { $global:LASTEXITCODE = 0; & $rustup run stable cargo tauri --version *> $null; $tauriAvailable = ($global:LASTEXITCODE -eq 0) } catch { $tauriAvailable = $false }
if (-not $tauriAvailable) {
    if ($SkipTauriInstall) { throw 'cargo-tauri is not installed and -SkipTauriInstall was specified.' }
    Write-Host 'cargo-tauri missing in selected cache; installing once...' -ForegroundColor Yellow
    Invoke-StableCargo $rustup 'install' 'tauri-cli' '--version' '^2' '--locked'
} else { Write-Host 'cargo-tauri already available; SKIP install.' -ForegroundColor Green }

Write-Host "`n[5/9] Ensure CMake/Ninja for boring-sys2" -ForegroundColor Green
$cmake = $legacyCmake
if (-not $cmake) {
    $cmd = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command cmake -ErrorAction SilentlyContinue }
    if ($cmd) { $cmake = $cmd.Source }
}
if (-not $cmake) { throw 'cmake is required but was not found in legacy cache or PATH.' }
$env:CMAKE = $cmake
$cmakeBin = Split-Path -Parent $cmake
if (($env:PATH -split ';') -notcontains $cmakeBin) { $env:PATH = "$cmakeBin;$env:PATH" }
$global:LASTEXITCODE = 0
$cmakeVersion = @(& $cmake --version 2>&1) | Select-Object -First 1
if ($global:LASTEXITCODE -ne 0) { throw "cmake --version failed: $cmake" }
Write-Host "Using $cmakeVersion" -ForegroundColor Green
if ($legacyNinja) { Write-Host 'Using proven r39-r42 Ninja generator.' -ForegroundColor Green }

Write-Host "`n[6/9] Ensure NASM for BoringSSL" -ForegroundColor Green
$nasm = $legacyNasm
if (-not $nasm) {
    $portable = Join-Path $repoRoot '.tools\nasm\nasm.exe'
    if (Test-Path -LiteralPath $portable -PathType Leaf) { $nasm = $portable }
}
if (-not $nasm) { throw 'NASM is missing from both the r39-r42 cache and the r46 portable fallback.' }
$nasmBin = Split-Path -Parent $nasm
if (($env:PATH -split ';') -notcontains $nasmBin) { $env:PATH = "$nasmBin;$env:PATH" }
$env:ASM_NASM = $nasm
$env:CMAKE_ASM_NASM_COMPILER = $nasm
$global:LASTEXITCODE = 0
$nasmVersion = @(& $nasm -v 2>&1) | Select-Object -First 1
if ($global:LASTEXITCODE -ne 0) { throw "nasm -v failed: $nasm" }
Write-Host "Using $nasmVersion" -ForegroundColor Green

Write-Host "`n[7/9] Reuse libclang + bindgen/MSVC environment" -ForegroundColor Green
$libclang = $legacyLibClang
if (-not $libclang -and $env:LIBCLANG_PATH) { $libclang = Find-FirstFile @($env:LIBCLANG_PATH) @('libclang.dll','clang.dll') }
if (-not $libclang) {
    $libclang = Find-FirstFile @((Join-Path $env:ProgramFiles 'LLVM'),(Join-Path ${env:ProgramFiles(x86)} 'LLVM')) @('libclang.dll','clang.dll')
}
if (-not $libclang) { throw 'libclang is required by bindgen and was not found. The proven r39-r42 cache was expected to provide it.' }
$libclangDir = Split-Path -Parent $libclang
$env:LIBCLANG_PATH = $libclangDir
if (($env:PATH -split ';') -notcontains $libclangDir) { $env:PATH = "$libclangDir;$env:PATH" }
Write-Host "Using existing libclang: $libclang" -ForegroundColor Green
Write-Host "LIBCLANG_PATH: $libclangDir" -ForegroundColor Green
if ($env:BINDGEN_EXTRA_CLANG_ARGS) { Write-Host 'BINDGEN_EXTRA_CLANG_ARGS restored from MSVC/SDK include directories.' -ForegroundColor Green }

Write-Host "`n[8/9] Build actual Windows NSIS package" -ForegroundColor Green
Push-Location (Join-Path $repoRoot 'src-tauri')
try { Invoke-StableCargo $rustup 'tauri' 'build' '--target' $target '--bundles' 'nsis' } finally { Pop-Location }

Write-Host "`n[9/9] Copy real-use installer" -ForegroundColor Green
$appVersionLine = ($versionFile -split "`r?`n" | Where-Object { $_ -like 'app_version=*' } | Select-Object -First 1)
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+46' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r46-real-use\$safeVersion"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$bundleRoot = if ($env:CARGO_TARGET_DIR) { Join-Path $env:CARGO_TARGET_DIR "$target\release\bundle\nsis" } else { Join-Path $repoRoot "target\$target\release\bundle\nsis" }
$setup = Get-ChildItem -LiteralPath $bundleRoot -Filter '*.exe' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "NSIS installer not found under: $bundleRoot" }
$dest = Join-Path $outDir "Codex-App-Transfer-Sub2API-Grok-Compat-$safeVersion-FAST-REAL-USE.exe"
Copy-Item -LiteralPath $setup.FullName -Destination $dest -Force
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $dest).Hash
$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 46
    purpose = 'FAST REAL-USE TEST BUILD'
    fullReleaseValidation = $false
    skipped = @('Rust unit tests','cargo check','legacy stress','release proof')
    materialization = 'passed/reused'
    frontendBuild = 'passed/reused'
    legacyR39R42CacheReused = $legacyReused
    cargoTargetDir = [string]$env:CARGO_TARGET_DIR
    rustc = $rustVersion.ToString()
    cmake = [string]$cmakeVersion
    nasm = [string]$nasmVersion
    libclang = [string]$libclang
    windowsNsisCompilation = 'passed'
    realThreadRecoveryExecutedDuringBuild = $false
    installer = $dest
    sha256 = $sha
    builtAt = (Get-Date).ToString('o')
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outDir 'FAST-REAL-USE-MANIFEST.json') -Encoding UTF8

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host 'R46 FAST REAL-USE BUILD PASS' -ForegroundColor Green
Write-Host "Installer: $dest"
Write-Host "SHA256   : $sha"
Write-Host "Legacy cache reused: $legacyReused"
Write-Host '============================================================' -ForegroundColor Green
Write-Host 'Next: install r46, open 路由 -> 全链路健康 -> 旧会话恢复（先预览）.' -ForegroundColor Yellow
