param(
    [switch]$SkipFrontend,
    [switch]$SkipFocusedTests,
    [switch]$NoDeploy,
    [string]$DeployDir = "V:\Codex App Transfer"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LLVM_HOME = "V:\Local-Build-Shared\toolchains\llvm\22.1.8"
$LibClang = Join-Path $LLVM_HOME "bin\libclang.dll"
if (-not (Test-Path $LibClang)) {
    throw "r70 build requires shared libclang at: $LibClang"
}

$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $VsWhere)) {
    throw "vswhere.exe not found; Visual Studio C++ Build Tools are required"
}

$VS_HOME = (& $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if ([string]::IsNullOrWhiteSpace($VS_HOME)) {
    throw "Visual Studio C++ Build Tools installation not found"
}
$VS_HOME = $VS_HOME.Trim()
$VcVars = Join-Path $VS_HOME "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $VcVars)) {
    throw "vcvars64.bat not found: $VcVars"
}

$DevEnv = & $env:ComSpec /d /s /c "`"$VcVars`" >nul && set"
foreach ($Line in $DevEnv) {
    if ($Line -match '^([^=]+)=(.*)$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
    }
}

$env:LIBCLANG_PATH = Join-Path $LLVM_HOME "bin"
$env:Path = "$($env:LIBCLANG_PATH);$($env:Path)"

Write-Host "[r70] VS=$VS_HOME"
Write-Host "[r70] LIBCLANG_PATH=$env:LIBCLANG_PATH"

if (-not $SkipFrontend) {
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            npm ci --prefer-offline --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        }
        npm run build:nocheck
        if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    }
    finally {
        Pop-Location
    }
}

if (-not $SkipFocusedTests) {
    cargo test -p codex-app-transfer-registry presets_count_matches_python
    if ($LASTEXITCODE -ne 0) { throw "registry focused test failed" }

    cargo test -p codex-app-transfer-codex-integration --test r70_local_gateway_catalog
    if ($LASTEXITCODE -ne 0) { throw "r70 catalog focused test failed" }
}

$Exe = Join-Path $RepoRoot "target\release\codex-app-transfer.exe"
$DeployExe = Join-Path $DeployDir "codex-app-transfer.exe"

# Windows locks a running executable. Stop only the r70 build/deploy copies so a
# rebuild can replace target\release\codex-app-transfer.exe safely. Do not kill
# unrelated copies installed elsewhere.
$Running = @(Get-Process codex-app-transfer -ErrorAction SilentlyContinue | Where-Object {
    try {
        $ProcessPath = $_.Path
        ($ProcessPath -eq $Exe) -or ((-not $NoDeploy) -and ($ProcessPath -eq $DeployExe))
    }
    catch { $false }
})
if ($Running.Count -gt 0) {
    Write-Host "[r70] stopping running r70 Transfer before rebuild"
    $Running | Stop-Process -Force
    Start-Sleep -Milliseconds 500
}

cargo tauri build --no-bundle
if ($LASTEXITCODE -ne 0) { throw "Tauri release build failed" }

if (-not (Test-Path $Exe)) {
    throw "release executable was not produced: $Exe"
}

Write-Host ""
Write-Host "R70_LOCAL_BUILD_PASS"
Get-Item $Exe | Select-Object FullName, Length, LastWriteTime

if (-not $NoDeploy) {
    if (-not (Test-Path $DeployDir)) {
        New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
    }

    # Re-check in case the deployed copy was launched while compilation was running.
    $RunningDeploy = @(Get-Process codex-app-transfer -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $DeployExe } catch { $false }
    })
    if ($RunningDeploy.Count -gt 0) {
        Write-Host "[r70] stopping running deployed Transfer before replacement"
        $RunningDeploy | Stop-Process -Force
        Start-Sleep -Milliseconds 300
    }

    Copy-Item -LiteralPath $Exe -Destination $DeployExe -Force
    Write-Host ""
    Write-Host "R70_DEPLOY_PASS"
    Get-Item $DeployExe | Select-Object FullName, Length, LastWriteTime
}
