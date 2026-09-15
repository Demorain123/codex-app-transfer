param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Source = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$R74Builder = Join-Path $PSScriptRoot 'build-r74-output-ui-local.ps1'
$Driver = Join-Path $PSScriptRoot '.build-r76-driver.generated.ps1'
if (-not (Test-Path $Source)) { throw "r76 source builder missing: $Source" }
if (-not (Test-Path $R74Builder)) { throw "r76 base builder missing: $R74Builder" }

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Text = [System.IO.File]::ReadAllText($Source)
$OriginalR74 = [System.IO.File]::ReadAllText($R74Builder)

function Replace-Required([string]$Value, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Value.Contains($Old)) { throw "r76 entrypoint expected text missing: $Label" }
    return $Value.Replace($Old, $New)
}

# Avoid an outer/inner generated-script filename collision while the r75-based
# finalizer is converted to r76 identity.
$Old = '$TempBuilder = Join-Path $PSScriptRoot ''.build-r76-output-ui-local.generated.ps1'''
$New = '$TempBuilder = Join-Path $PSScriptRoot ''.build-r76-stage.generated.ps1'''
$Text = Replace-Required $Text $Old $New 'outer generated builder path'

# r74 used viewport media queries. In Codex Desktop the conversation/composer
# column can be ~650-750 px wide while the app viewport remains >1500 px, so
# those rules never fire. Make the status bar a size query container and adapt
# optional metrics to the actual composer/status width instead.
$OldSpacer = @'
      '#' + STATUS_ID + ' .cas-status-spacer{flex:1 1 auto;min-width:2px;}',
'@
$NewSpacer = @'
      '#' + STATUS_ID + ' .cas-status-spacer{flex:1 1 auto;min-width:2px;}',
      '@container (max-width:720px){#' + STATUS_ID + ' .cas-status-secondary{display:none;}}',
      '@container (max-width:560px){#' + STATUS_ID + ' .cas-status-tertiary{display:none;}}',
'@
$OldBar = @'
      bar.id = STATUS_ID;
      bar.title = 'Click for live telemetry charts';
'@
$NewBar = @'
      bar.id = STATUS_ID;
      bar.style.containerType = 'inline-size';
      bar.title = 'Click for live telemetry charts';
'@

$AdaptiveR74 = Replace-Required $OriginalR74 $OldSpacer $NewSpacer 'status container-query rules'
$AdaptiveR74 = Replace-Required $AdaptiveR74 $OldBar $NewBar 'status container type'

try {
    [System.IO.File]::WriteAllText($R74Builder, $AdaptiveR74, $Utf8NoBom)
    [System.IO.File]::WriteAllText($Driver, $Text, $Utf8NoBom)

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Driver)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r76 local build failed with exit code $LASTEXITCODE" }

    Write-Host 'R76_LOCAL_ENTRYPOINT_PASS' -ForegroundColor Green
    Write-Host '  - status density follows the actual composer width via CSS container queries'
    Write-Host '  - <=720px hides cache/model; <=560px also hides cumulative session total'
    Write-Host '  - ctx/in/out/tok-s remain the compact core metrics'
}
finally {
    [System.IO.File]::WriteAllText($R74Builder, $OriginalR74, $Utf8NoBom)
    Remove-Item -LiteralPath $Driver -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $PSScriptRoot '.build-r76-stage.generated.ps1') -Force -ErrorAction SilentlyContinue
}
