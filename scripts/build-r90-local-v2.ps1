param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Source = Join-Path $PSScriptRoot 'build-r90-local.ps1'
$Temp = Join-Path $PSScriptRoot '.build-r90-local-v2.generated.ps1'
if (-not (Test-Path -LiteralPath $Source)) { throw "r90 v2 source missing: $Source" }
if (Test-Path -LiteralPath $Temp) { throw "r90 v2 refuses pre-existing temp path: $Temp" }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Text = [System.IO.File]::ReadAllText($Source).Replace("`r`n","`n").Replace("`r","`n")

$OldReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r90 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
'@
$NewReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedOld = $Old.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedNew = $New.Replace("`r`n","`n").Replace("`r","`n")
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r90 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld,$NormalizedNew)
}
'@

$OldReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $StartIndex = $Text.IndexOf($Start)
    if ($StartIndex -lt 0) { throw "r90 block start missing: $Label" }
    $EndIndex = $Text.IndexOf($End,$StartIndex + $Start.Length)
    if ($EndIndex -le $StartIndex) { throw "r90 block end missing: $Label" }
    return $Text.Substring(0,$StartIndex) + $Replacement + "`n`n" + $Text.Substring($EndIndex)
}
'@
$NewReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedStart = $Start.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedEnd = $End.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedReplacement = $Replacement.Replace("`r`n","`n").Replace("`r","`n")
    $StartIndex = $NormalizedText.IndexOf($NormalizedStart)
    if ($StartIndex -lt 0) { throw "r90 block start missing: $Label" }
    $EndIndex = $NormalizedText.IndexOf($NormalizedEnd,$StartIndex + $NormalizedStart.Length)
    if ($EndIndex -le $StartIndex) { throw "r90 block end missing: $Label" }
    return $NormalizedText.Substring(0,$StartIndex) + $NormalizedReplacement + "`n`n" + $NormalizedText.Substring($EndIndex)
}
'@

foreach ($Patch in @(
    @($OldReplaceRequired,$NewReplaceRequired,'Replace-Required'),
    @($OldReplaceBlock,$NewReplaceBlock,'Replace-BlockRequired')
)) {
    $Old = $Patch[0].Replace("`r`n","`n").Replace("`r","`n")
    $New = $Patch[1].Replace("`r`n","`n").Replace("`r","`n")
    if (-not $Text.Contains($Old)) { throw "r90 v2 helper source missing: $($Patch[2])" }
    $Text = $Text.Replace($Old,$New)
}

foreach ($Marker in @(
    '$NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")',
    '$NormalizedOld = $Old.Replace("`r`n","`n").Replace("`r","`n")',
    '$NormalizedStart = $Start.Replace("`r`n","`n").Replace("`r","`n")'
)) {
    if (-not $Text.Contains($Marker)) { throw "r90 v2 EOL-normalization invariant missing: $Marker" }
}

$Tokens = $null
$Errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
if ($Errors -and $Errors.Count -gt 0) {
    $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
    throw "r90 v2 normalized PowerShell parse failed: $Summary"
}
Write-Host 'R90_V2_EOL_NORMALIZATION_PASS' -ForegroundColor Green

try {
    [System.IO.File]::WriteAllText($Temp,$Text,$Utf8NoBom)
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Temp)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r90 v2 delegated build failed with exit code $LASTEXITCODE" }
}
finally {
    Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
    Write-Host '[r90-v2] removed EOL-normalized temporary driver'
}
