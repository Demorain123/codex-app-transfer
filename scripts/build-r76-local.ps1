param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Source = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$Driver = Join-Path $PSScriptRoot '.build-r76-driver.generated.ps1'
if (-not (Test-Path $Source)) { throw "r76 source builder missing: $Source" }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Text = [System.IO.File]::ReadAllText($Source)
$Old = '$TempBuilder = Join-Path $PSScriptRoot ''.build-r76-output-ui-local.generated.ps1'''
$New = '$TempBuilder = Join-Path $PSScriptRoot ''.build-r76-stage.generated.ps1'''
if (-not $Text.Contains($Old)) { throw 'r76 driver could not find the expected temporary-builder declaration' }
$Text = $Text.Replace($Old, $New)

try {
    [System.IO.File]::WriteAllText($Driver, $Text, $Utf8NoBom)
    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Driver)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r76 local build failed with exit code $LASTEXITCODE" }
    Write-Host 'R76_LOCAL_ENTRYPOINT_PASS' -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $Driver -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $PSScriptRoot '.build-r76-stage.generated.ps1') -Force -ErrorAction SilentlyContinue
}
