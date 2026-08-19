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
    throw "r41 verified package policy requires the repository on physical V:. Current: $repoRoot"
}
Set-Location $repoRoot
$target = 'x86_64-pc-windows-msvc'

Write-Host 'Codex App Transfer r41 - VERIFIED LOCAL PACKAGE' -ForegroundColor Green
Write-Host 'Gate: r39 100-generation proof + r40 Windows Port Guard 2/2 + r41 explicit port repair 2/2 + cargo check + production frontend -> Tauri bundle.'
Write-Host 'Installed UX target: foreign live owner -> user clicks Try repair -> port FREE -> user clicks Start forwarding -> success.'
Write-Host 'Safety: no background process kill; no automatic port switching; no SO_REUSEADDR conflict masking; stale/dead binders remain evidence-only.'

$verifiedGate = Join-Path $PSScriptRoot 'build-r41-local-release-stress.ps1'
& $verifiedGate
if ($LASTEXITCODE -ne 0) {
    throw "r41 verified gate failed with exit code $LASTEXITCODE"
}

if ([string]::IsNullOrWhiteSpace($env:CARGO_HOME)) {
    throw 'CARGO_HOME is empty after the verified r41 gate.'
}
if ([string]::IsNullOrWhiteSpace($env:CARGO_TARGET_DIR)) {
    throw 'CARGO_TARGET_DIR is empty after the verified r41 gate.'
}
if ([string]::IsNullOrWhiteSpace($env:TEMP)) {
    throw 'TEMP is empty after the verified r41 gate.'
}
$cargoExe = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path -LiteralPath $cargoExe -PathType Leaf)) {
    throw "V:-local cargo.exe was not found: $cargoExe"
}

$lifecycleLog = Join-Path $env:TEMP 'r41-r39-lifecycle-proof-last.log'
$guardLog = Join-Path $env:TEMP 'r41-r40-windows-port-guard-proof-last.log'
$repairLog = Join-Path $env:TEMP 'r41-explicit-port-repair-proof-last.log'
foreach ($requiredLog in @($lifecycleLog, $guardLog, $repairLog)) {
    if (-not (Test-Path -LiteralPath $requiredLog -PathType Leaf)) {
        throw "Verified proof transcript is missing: $requiredLog"
    }
}

$lifecycleText = Get-Content -LiteralPath $lifecycleLog -Raw -Encoding UTF8
foreach ($expected in @(
    'proxy_lifecycle_r39_owner_thread_join_rebind_100_generations',
    'proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier'
)) {
    if ($lifecycleText -notmatch [regex]::Escape($expected)) {
        throw "Packaging refused: lifecycle transcript is missing expected test: $expected"
    }
}
if ($lifecycleText -notmatch '(?m)^running\s+2\s+tests\s*$' -or
    $lifecycleText -notmatch 'test result:\s+ok\.\s+2 passed;\s+0 failed;') {
    throw "Packaging refused: lifecycle transcript does not prove 2 passed / 0 failed: $lifecycleLog"
}
Write-Host "r39 lifecycle transcript proof: PASS ($lifecycleLog)" -ForegroundColor Green

$guardText = Get-Content -LiteralPath $guardLog -Raw -Encoding UTF8
foreach ($expected in @(
    'windows_port_guard_r40_clears_inherit_bit',
    'windows_port_guard_r40_classifies_foreign_and_stale_binders'
)) {
    if ($guardText -notmatch [regex]::Escape($expected)) {
        throw "Packaging refused: r40 guard transcript is missing expected test: $expected"
    }
}
if ($guardText -notmatch '(?m)^running\s+2\s+tests\s*$' -or
    $guardText -notmatch 'test result:\s+ok\.\s+2 passed;\s+0 failed;') {
    throw "Packaging refused: r40 guard transcript does not prove 2 passed / 0 failed: $guardLog"
}
Write-Host "r40 Windows Port Guard transcript proof: PASS ($guardLog)" -ForegroundColor Green

$repairText = Get-Content -LiteralPath $repairLog -Raw -Encoding UTF8
foreach ($expected in @(
    'windows_port_repair_r41_rejects_self_owner',
    'windows_port_repair_r41_terminates_explicit_foreign_owner'
)) {
    if ($repairText -notmatch [regex]::Escape($expected)) {
        throw "Packaging refused: r41 repair transcript is missing expected test: $expected"
    }
}
if ($repairText -notmatch '(?m)^running\s+2\s+tests\s*$' -or
    $repairText -notmatch 'test result:\s+ok\.\s+2 passed;\s+0 failed;') {
    throw "Packaging refused: r41 repair transcript does not prove 2 passed / 0 failed: $repairLog"
}
Write-Host "r41 Explicit Port Repair transcript proof: PASS ($repairLog)" -ForegroundColor Green

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
Write-Host "`nBuilding verified r41 Windows bundle(s): $bundles" -ForegroundColor Green
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
$appVersion = if ($appVersionLine) { $appVersionLine.Substring('app_version='.Length) } else { '2.4.5+41' }
$safeVersion = $appVersion -replace '\+', '-r'
$outDir = "V:\Codex-App-Transfer-Packages\r41\$safeVersion-verified"
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

$lifecycleCopy = Join-Path $outDir 'r41-r39-lifecycle-proof.log'
$guardCopy = Join-Path $outDir 'r41-r40-windows-port-guard-proof.log'
$repairCopy = Join-Path $outDir 'r41-explicit-port-repair-proof.log'
Copy-Item -LiteralPath $lifecycleLog -Destination $lifecycleCopy -Force
Copy-Item -LiteralPath $guardLog -Destination $guardCopy -Force
Copy-Item -LiteralPath $repairLog -Destination $repairCopy -Force

$manifest = [ordered]@{
    version = $appVersion
    compatRevision = 41
    acceptance = [ordered]@{
        r39LifecycleTestsVisible = 2
        r39LifecycleTestsPassed = 2
        r39LifecycleTestsFailed = 0
        samePortGenerations = 100
        r40PortGuardTestsVisible = 2
        r40PortGuardTestsPassed = 2
        r40PortGuardTestsFailed = 0
        r41RepairTestsVisible = 2
        r41RepairTestsPassed = 2
        r41RepairTestsFailed = 0
        socketInheritanceGuardTest = 'passed'
        ownerClassificationTest = 'passed'
        rejectSelfOwnerRepairTest = 'passed'
        explicitForeignOwnerTerminationTest = 'passed'
        lifecycleTranscript = $lifecycleCopy
        portGuardTranscript = $guardCopy
        explicitRepairTranscript = $repairCopy
        frontendProductionBuild = $true
        cargoCheck = 'passed-before-bundle'
        installedUxTarget = 'foreign_live -> Try repair -> port free -> manual Start forwarding -> success'
        backgroundProcessKill = $false
        explicitUserTriggeredForeignOwnerRepair = $true
        staleBinderProcessTermination = $false
        automaticPortSwitching = $false
        reuseAddrConflictMasking = $false
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
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "`nR41 VERIFIED LOCAL PACKAGE PASS" -ForegroundColor Green
Write-Host "Output          : $outDir"
Write-Host "Manifest        : $manifestPath"
Write-Host "Lifecycle proof : $lifecycleCopy"
Write-Host "Port guard proof: $guardCopy"
Write-Host "Repair proof    : $repairCopy"
foreach ($file in $copied) {
    $item = Get-Item -LiteralPath $file
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file
    Write-Host ("  {0} ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
    Write-Host ("    SHA256 {0}" -f $hash.Hash)
}
Write-Host 'Next gate: install r41. Deliberately occupy 18089 with a disposable foreign PowerShell listener, click Try repair, verify 18089 becomes FREE, then click Start forwarding and verify success.' -ForegroundColor Green
