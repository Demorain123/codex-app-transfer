#requires -Version 7.0

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$toolDir = Join-Path $repoRoot '.tools\nasm'
$stableExe = Join-Path $toolDir 'nasm.exe'

if (Test-Path -LiteralPath $stableExe -PathType Leaf) {
    Write-Host "Portable NASM already ready: $stableExe" -ForegroundColor Green
    exit 0
}

$systemNasm = Get-Command nasm.exe -ErrorAction SilentlyContinue
if (-not $systemNasm) { $systemNasm = Get-Command nasm -ErrorAction SilentlyContinue }
if ($systemNasm) {
    New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
    Copy-Item -LiteralPath $systemNasm.Source -Destination $stableExe -Force
    Write-Host "Cached system NASM for fast builds: $stableExe" -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
$zip = Join-Path $toolDir 'nasm-3.02-win64.zip'
$extractDir = Join-Path $toolDir '_extract'
$url = 'https://www.nasm.us/pub/nasm/releasebuilds/3.02/win64/nasm-3.02-win64.zip'

if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) {
    Write-Host 'System NASM is not discoverable; downloading official NASM 3.02 portable ZIP once...' -ForegroundColor Yellow
    Invoke-WebRequest -Uri $url -OutFile $zip
}

if (Test-Path -LiteralPath $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}
Expand-Archive -LiteralPath $zip -DestinationPath $extractDir -Force

$found = Get-ChildItem -LiteralPath $extractDir -Filter nasm.exe -File -Recurse -ErrorAction Stop | Select-Object -First 1
if (-not $found) {
    throw 'Official NASM portable ZIP extracted, but nasm.exe was not found.'
}

Copy-Item -LiteralPath $found.FullName -Destination $stableExe -Force
if (-not (Test-Path -LiteralPath $stableExe -PathType Leaf)) {
    throw 'Failed to stage portable nasm.exe into .tools\nasm.'
}

Write-Host "Portable NASM ready: $stableExe" -ForegroundColor Green
