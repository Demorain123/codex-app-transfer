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
$Text = [System.IO.File]::ReadAllText($Source)

# PowerShell single-quoted here-strings preserve backslashes literally. The r90
# JS snippets/needles had JavaScript-style \" even though the surrounding JS
# selector strings are themselves single-quoted. Normalize those literals so
# exact source matching uses the same text as the reviewed r89 observer.
$EscapedQuote = '\"'
$EscapedCount = ([regex]::Matches($Text,[regex]::Escape($EscapedQuote))).Count
if ($EscapedCount -lt 1) { throw 'r90 v2 expected at least one redundant escaped double quote' }
$Text = $Text.Replace($EscapedQuote,'"')

foreach ($Marker in @(
    "const semantic = element.closest('[data-chatgpt-conversation-turn=\"true\"],[data-turn-key],[data-message-author-role=\"assistant\"],[role=\"status\"],[data-testid*=\"agent\"],[data-testid*=\"tool\"],[data-testid*=\"command\"],[data-testid*=\"integration\"]');",
    "const turn = element.closest('[data-turn-key],[data-chatgpt-conversation-turn=\"true\"]');",
    "const selector = '[role=\"status\"],[data-testid*=\"agent\"],[data-testid*=\"tool\"],[data-testid*=\"command\"],[data-testid*=\"integration\"]';"
)) {
    # The markers above are PowerShell double-quoted strings; remove the parser
    # escaping before comparing against the generated script text.
    $Expected = $Marker.Replace('\"','"')
    if (-not $Text.Contains($Expected)) { throw "r90 v2 normalized selector invariant missing: $Expected" }
}

$Tokens = $null
$Errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
if ($Errors -and $Errors.Count -gt 0) {
    $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
    throw "r90 v2 normalized PowerShell parse failed: $Summary"
}
Write-Host ("R90_V2_JS_QUOTE_NORMALIZATION_PASS count={0}" -f $EscapedCount) -ForegroundColor Green

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
    Write-Host '[r90-v2] removed normalized temporary driver'
}
