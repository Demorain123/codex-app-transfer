#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$CleanCargoTarget,
    [double]$MinimumFreeGiB = 8
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$expectedTarget = 'V:\Codex-App-Transfer-DevCache\target\r39'
$target = $expectedTarget
$root = [System.IO.Path]::GetPathRoot($target)
if (-not $root) { throw "Unable to resolve drive root for Cargo target: $target" }

function Get-FreeGiB([string]$driveRoot) {
    $drive = [System.IO.DriveInfo]::new($driveRoot)
    return [math]::Round($drive.AvailableFreeSpace / 1GB, 2)
}

function Get-DirectoryGiB([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { return 0.0 }
    $sum = (Get-ChildItem -LiteralPath $path -File -Recurse -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    return [math]::Round(([double]$sum) / 1GB, 2)
}

$freeBefore = Get-FreeGiB $root
$targetGiB = Get-DirectoryGiB $target
Write-Host "R57 BUILD SPACE" -ForegroundColor Cyan
Write-Host "- Cargo target : $target"
Write-Host "- Target size  : $targetGiB GiB"
Write-Host "- Free on $root : $freeBefore GiB"
Write-Host "- Required free: $MinimumFreeGiB GiB"

if ($freeBefore -ge $MinimumFreeGiB) {
    Write-Host 'R57 BUILD SPACE: PASS' -ForegroundColor Green
    exit 0
}

if (-not $CleanCargoTarget) {
    Write-Host 'R57 BUILD SPACE: LOW' -ForegroundColor Yellow
    Write-Host 'The previous rustc failure was caused by the V: build-cache volume running out of space.'
    Write-Host 'Only the disposable Cargo target cache may be removed by this helper; source, Cargo registry, rustup/toolchains and project files are untouched.'
    Write-Host 'Run this once, then rerun Run-r57-FAST-REAL-USE.cmd:' -ForegroundColor Yellow
    Write-Host '  pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Repair-r57-Build-Space.ps1 -CleanCargoTarget' -ForegroundColor White
    exit 20
}

$resolvedExpected = [System.IO.Path]::GetFullPath($expectedTarget).TrimEnd('\')
$resolvedTarget = [System.IO.Path]::GetFullPath($target).TrimEnd('\')
if (-not $resolvedTarget.Equals($resolvedExpected, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Safety refusal: cleanup target differs from the fixed disposable Cargo target: $resolvedTarget"
}
if (-not $resolvedTarget.StartsWith('V:\Codex-App-Transfer-DevCache\target\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Safety refusal: cleanup target escaped the DevCache target root: $resolvedTarget"
}

if (Test-Path -LiteralPath $target -PathType Container) {
    Write-Host "Removing disposable Cargo target cache: $target" -ForegroundColor Yellow
    Remove-Item -LiteralPath $target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $target | Out-Null

$freeAfter = Get-FreeGiB $root
Write-Host "- Free after target cleanup: $freeAfter GiB"
if ($freeAfter -lt $MinimumFreeGiB) {
    Write-Host 'R57 BUILD SPACE: STILL LOW' -ForegroundColor Red
    Write-Host 'The Cargo target cache was removed safely, but V: still does not have enough free space. Free additional unrelated space on V: before rebuilding.'
    exit 21
}

Write-Host 'R57 BUILD SPACE: CLEAN PASS' -ForegroundColor Green
Write-Host 'The next build will recompile Rust artifacts because the Cargo target cache was intentionally cleared.'
exit 0
