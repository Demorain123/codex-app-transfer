param(
    [switch]$Apply,
    [switch]$RunChecks
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$V1 = Join-Path $PSScriptRoot 'r70-local-gateway-bootstrap.ps1'
$Temp = Join-Path $PSScriptRoot '.r70-local-gateway-bootstrap-fixed.ps1'

function Normalize-RepoPath([string]$Path) {
    return $Path.Replace('\\', '/').Trim()
}

Push-Location $RepoRoot
try {
    if (-not (Test-Path $V1)) {
        throw "r70 v1 bootstrap not found: $V1"
    }

    # The first v1 run may already have updated the preset JSON/count before
    # stopping at the CRLF/LF-sensitive catalog anchor. Only tolerate files
    # owned by this r70 bootstrap; refuse unrelated dirty state.
    $allowed = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    @(
        'crates/registry/src/presets_data.json',
        'crates/registry/src/presets.rs',
        'crates/codex_integration/src/model_catalog.rs',
        'crates/codex_integration/tests/r70_local_gateway_catalog.rs',
        'scripts/r70-local-gateway-bootstrap-v2.ps1'
    ) | ForEach-Object { [void]$allowed.Add($_) }

    $dirty = @()
    $dirty += @(& git diff --name-only)
    $dirty += @(& git diff --cached --name-only)
    $dirty += @(& git ls-files --others --exclude-standard)
    $unknown = @(
        $dirty |
            ForEach-Object { Normalize-RepoPath $_ } |
            Where-Object { $_ -and -not $allowed.Contains($_) } |
            Sort-Object -Unique
    )
    if ($unknown.Count -gt 0) {
        throw "r70 v2 refuses unrelated dirty files:`n$($unknown -join "`n")"
    }

    $src = [IO.File]::ReadAllText($V1)
    $signature = 'function Replace-Once([string]$Text, [string]$Old, [string]$New, [string]$Label) {'
    if (-not $src.Contains($signature)) {
        throw 'r70 v2 could not locate Replace-Once in v1 bootstrap.'
    }

    # v1 normalizes target source files to LF, but on Windows its here-string
    # anchors can carry CRLF. Normalize Old/New before IndexOf so semantically
    # identical source anchors match independent of checkout line endings.
    $fixedSignature = $signature + "`r`n" +
        '    $Old = $Old.Replace("`r`n", "`n")'.Replace('\"','"') + "`r`n" +
        '    $New = $New.Replace("`r`n", "`n")'.Replace('\"','"')
    $fixed = $src.Replace($signature, $fixedSignature)

    $enc = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Temp, $fixed, $enc)

    Write-Host 'r70 v2 line-ending compatibility shim ready.' -ForegroundColor Cyan
    & $Temp -Apply:$Apply -RunChecks:$RunChecks -Force
    if ($LASTEXITCODE -ne 0) {
        throw "r70 patched bootstrap exited with code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -LiteralPath $Temp -Force -ErrorAction SilentlyContinue
    Pop-Location
}
