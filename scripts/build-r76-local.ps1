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

function Replace-Required-OrAlready([string]$Value, [string]$Old, [string]$New, [string]$Label) {
    if ($Value.Contains($Old)) {
        return $Value.Replace($Old, $New)
    }
    if ($Value.Contains($New)) {
        Write-Host "R76_ENTRY_IDEMPOTENT_ALREADY_PASS: $Label" -ForegroundColor Green
        return $Value
    }
    throw "r76 entrypoint expected old/new text missing: $Label"
}

function Ensure-LineAfter([string]$Value, [string]$Anchor, [string]$Line, [string]$Label) {
    if ($Value.Contains($Line)) {
        Write-Host "R76_ENTRY_IDEMPOTENT_ALREADY_PASS: $Label" -ForegroundColor Green
        return $Value
    }
    if (-not $Value.Contains($Anchor)) {
        throw "r76 entrypoint anchor missing: $Label"
    }
    return $Value.Replace($Anchor, $Anchor + "`n" + $Line)
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
#
# Do not use multiline here-string matching for this migration. Nested builders
# rewrite temporary PowerShell sources with UTF-8 and may change CRLF/LF style;
# matching semantic single-line anchors keeps the migration strict without
# making line-ending style part of the contract.
$SpacerAnchor = "      '#' + STATUS_ID + ' .cas-status-spacer{flex:1 1 auto;min-width:2px;}',"
$Container720 = "      '@container (max-width:720px){#' + STATUS_ID + ' .cas-status-secondary{display:none;}}',"
$Container560 = "      '@container (max-width:560px){#' + STATUS_ID + ' .cas-status-tertiary{display:none;}}',"
$BarAnchor = '      bar.id = STATUS_ID;'
$ContainerTypeLine = "      bar.style.containerType = 'inline-size';"

$AdaptiveR74 = Ensure-LineAfter $OriginalR74 $SpacerAnchor $Container720 'status container-query <=720 rule'
$AdaptiveR74 = Ensure-LineAfter $AdaptiveR74 $Container720 $Container560 'status container-query <=560 rule'
$AdaptiveR74 = Ensure-LineAfter $AdaptiveR74 $BarAnchor $ContainerTypeLine 'status container type'

# OpenAI's current token accounting distinguishes active request/context usage
# (last_token_usage) from lifetime cumulative thread usage (total_token_usage).
# Calling the latter merely "session" is easy to misread when it reaches tens or
# hundreds of millions, so r76 labels it explicitly as cumulative total.
$AdaptiveR74 = Replace-Required-OrAlready $AdaptiveR74 `
    "    const session = 'session ' + shortNumber(effectiveSessionTotal());" `
    "    const session = 'total ' + shortNumber(effectiveSessionTotal());" `
    'status cumulative total label'
$AdaptiveR74 = Replace-Required-OrAlready $AdaptiveR74 `
    '<span>Session</span><span>' `
    '<span>Session total</span><span>' `
    'mirror cumulative total label'

foreach ($Marker in @(
    $Container720,
    $Container560,
    $ContainerTypeLine,
    "    const session = 'total ' + shortNumber(effectiveSessionTotal());",
    '<span>Session total</span><span>'
)) {
    if (-not $AdaptiveR74.Contains($Marker)) {
        throw "r76 entrypoint post-migration invariant missing: $Marker"
    }
}
Write-Host 'R76_ENTRY_UI_MIGRATION_PREFLIGHT_PASS' -ForegroundColor Green

try {
    [System.IO.File]::WriteAllText($R74Builder, $AdaptiveR74, $Utf8NoBom)
    [System.IO.File]::WriteAllText($Driver, $Text, $Utf8NoBom)

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Driver)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r76 local build failed with exit code $LASTEXITCODE" }

    Write-Host 'R76_LOCAL_ENTRYPOINT_PASS' -ForegroundColor Green
    Write-Host '  - status density follows the actual composer width via CSS container queries'
    Write-Host '  - <=720px hides cache/model; <=560px also hides cumulative total'
    Write-Host '  - ctx/in/out/tok-s remain the compact core metrics'
    Write-Host '  - lifetime total is labeled total, not context/session occupancy'
}
finally {
    [System.IO.File]::WriteAllText($R74Builder, $OriginalR74, $Utf8NoBom)
    Remove-Item -LiteralPath $Driver -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $PSScriptRoot '.build-r76-stage.generated.ps1') -Force -ErrorAction SilentlyContinue
}
