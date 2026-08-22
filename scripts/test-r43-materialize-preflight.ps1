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

function Test-PythonRunner {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Prefix = @()
    )

    try {
        $resolved = Get-Command $Command -ErrorAction Stop
        $source = [string]$resolved.Source
        if ($source -and $source -like "$env:LOCALAPPDATA\Microsoft\WindowsApps\*") {
            return $false
        }

        & $Command @Prefix -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Resolve-PythonRunner {
    if ($env:PYTHON) {
        if (Test-PythonRunner -Command $env:PYTHON) {
            return [pscustomobject]@{ Command = $env:PYTHON; Prefix = @() }
        }
    }

    # First keep compatibility with the classic CPython launcher selector.
    if (Test-PythonRunner -Command 'py' -Prefix @('-3')) {
        return [pscustomobject]@{ Command = 'py'; Prefix = @('-3') }
    }

    # `py -3` only targets PythonCore and can fail when its registered interpreter
    # was removed while another PEP 514 provider (for example Astral) is healthy.
    # Enumerate every launcher-advertised runtime and prove it by actually executing
    # a tiny Python 3 process.  This avoids trusting stale launcher registrations.
    try {
        if (Get-Command 'py' -ErrorAction Stop) {
            $launcherLines = @(& py --list 2>$null)
            foreach ($line in $launcherLines) {
                if ([string]$line -match '^\s*-V:([^\s*]+)') {
                    $tag = $Matches[1]
                    $prefix = @("-V:$tag")
                    if (Test-PythonRunner -Command 'py' -Prefix $prefix) {
                        return [pscustomobject]@{ Command = 'py'; Prefix = $prefix }
                    }
                }
            }
        }
    }
    catch {
        # Continue to PATH/filesystem discovery below.
    }

    foreach ($name in @('python', 'python3')) {
        if (Test-PythonRunner -Command $name) {
            return [pscustomobject]@{ Command = $name; Prefix = @() }
        }
    }

    # Last-resort discovery for normal per-user / system CPython installs that
    # exist but are not on PATH. Do not inspect command lines or user files.
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $roots) {
        $candidates = @()
        if ($root -like '*Programs\Python') {
            $candidates = @(Get-ChildItem -Path $root -Filter python.exe -File -Recurse -Depth 2 -ErrorAction SilentlyContinue)
        }
        else {
            $candidates = @(Get-ChildItem -Path $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName 'python.exe' } |
                Where-Object { Test-Path $_ } |
                ForEach-Object { Get-Item $_ })
        }

        foreach ($candidate in ($candidates | Sort-Object FullName -Descending)) {
            if (Test-PythonRunner -Command $candidate.FullName) {
                return [pscustomobject]@{ Command = $candidate.FullName; Prefix = @() }
            }
        }
    }

    throw @'
No working Python 3 runtime was found.
The Microsoft Store python.exe App Execution Alias and stale `py --list` registrations are intentionally ignored.
Quick checks: `py --list` and `Get-Command python,py -All`.
Install/expose Python 3, or set $env:PYTHON to a real python.exe path, then rerun this preflight.
'@
}

function Invoke-Python {
    param([Parameter(Mandatory)][string]$Script)
    $runnerArgs = @($script:PythonRunner.Prefix) + @($Script)
    Invoke-Checked -Command $script:PythonRunner.Command -Arguments $runnerArgs
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

$dirty = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git working tree.' }
if ($dirty.Count -gt 0) {
    throw "r43 materialize preflight requires a clean working tree:`n$($dirty -join "`n")"
}

$head = (& git rev-parse HEAD).Trim()
$script:PythonRunner = Resolve-PythonRunner
$pythonDisplay = @($script:PythonRunner.Command) + @($script:PythonRunner.Prefix)

Write-Host 'Codex App Transfer r43 - materializer preflight only' -ForegroundColor Green
Write-Host "Baseline: $head" -ForegroundColor DarkGray
Write-Host "Python runner: $($pythonDisplay -join ' ')" -ForegroundColor DarkGray
Write-Host 'This gate intentionally skips MSVC setup, Cargo build, legacy stress, frontend, and real-account tests.' -ForegroundColor DarkGray

try {
    Write-Host "`n[1/4] Materialize r43 exactly once" -ForegroundColor Green
    Invoke-Python 'scripts/apply_r43_unified.py'

    Write-Host "`n[2/4] Canonical runtime-classifier structure review" -ForegroundColor Green
    Invoke-Python 'scripts/review_r43_runtime_classifier_canonical.py'

    Write-Host "`n[3/4] Static r43 review" -ForegroundColor Green
    Invoke-Python 'scripts/review_r43_health_mcp_hardening.py'

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
