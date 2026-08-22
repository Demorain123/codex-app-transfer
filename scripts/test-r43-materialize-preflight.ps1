#requires -Version 7.0

[CmdletBinding()]
param()

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
Set-Location $repoRoot

$dirty = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git working tree.' }
if ($dirty.Count -gt 0) {
    throw "r43 materialize preflight requires a clean working tree:`n$($dirty -join "`n")"
}

$head = (& git rev-parse HEAD).Trim()
Write-Host 'Codex App Transfer r43 - materializer preflight only' -ForegroundColor Green
Write-Host "Baseline: $head" -ForegroundColor DarkGray
Write-Host 'This gate intentionally skips MSVC setup, Cargo build, legacy stress, frontend, and real-account tests.' -ForegroundColor DarkGray

try {
    Write-Host "`n[1/4] Materialize r43 exactly once" -ForegroundColor Green
    Invoke-Checked python 'scripts/apply_r43_unified.py'

    Write-Host "`n[2/4] Canonical runtime-classifier structure review" -ForegroundColor Green
    Invoke-Checked python 'scripts/review_r43_runtime_classifier_canonical.py'

    Write-Host "`n[3/4] Static r43 review" -ForegroundColor Green
    Invoke-Checked python 'scripts/review_r43_health_mcp_hardening.py'

    Write-Host "`n[4/4] Version/invariant smoke" -ForegroundColor Green
    $version = Get-Content (Join-Path $repoRoot 'SUB2API_GROK_COMPAT_VERSION.txt') -Raw -Encoding UTF8
    if ($version -notmatch 'compat_revision=43' -or $version -notmatch 'app_version=2\.4\.5\+43') {
        throw 'r43 version stamp mismatch'
    }

    Write-Host 'R43 MATERIALIZER PREFLIGHT PASS' -ForegroundColor Green
    Write-Host $version.Trim()
}
finally {
    Write-Host "`nRestoring clean baseline..." -ForegroundColor DarkGray
    & git reset --hard $head | Out-Host
    & git clean -fd | Out-Host
}
