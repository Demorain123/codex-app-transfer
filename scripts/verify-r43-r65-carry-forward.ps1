param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$NoReportFile,
    [switch]$FailOnMissing
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ManifestPath = Join-Path $PSScriptRoot 'r43-r65-carry-forward-manifest.json'
if (-not (Test-Path -LiteralPath $ManifestPath)) { throw "manifest missing: $ManifestPath" }
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -Depth 32

$RuntimeRoots = @(
    (Join-Path $RepoRoot 'src-tauri\src'),
    (Join-Path $RepoRoot 'crates'),
    (Join-Path $RepoRoot 'frontend\src'),
    (Join-Path $RepoRoot 'resources')
) | Where-Object { Test-Path -LiteralPath $_ }

$RuntimeFiles = @()
foreach ($Root in $RuntimeRoots) {
    $RuntimeFiles += Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.rs','.ts','.tsx','.js','.mjs','.cjs','.vue','.json','.toml','.ps1','.cmd','.py') }
}

function Find-InFiles {
    param([string]$Needle, [System.IO.FileInfo[]]$Files)
    $Hits = @()
    foreach ($File in $Files) {
        try {
            if (Select-String -LiteralPath $File.FullName -SimpleMatch -Pattern $Needle -Quiet -ErrorAction Stop) {
                $Hits += [IO.Path]::GetRelativePath($RepoRoot, $File.FullName).Replace('\','/')
            }
        } catch { }
    }
    return @($Hits | Sort-Object -Unique)
}

function Extract-VersionMarkers {
    param([string]$Version, [object[]]$EvidenceScripts)
    $Escaped = [Regex]::Escape($Version.ToUpperInvariant())
    $Pattern = "CAS-$Escaped-[A-Z0-9_-]+"
    $Markers = New-Object System.Collections.Generic.HashSet[string]
    foreach ($Rel in $EvidenceScripts) {
        $Path = Join-Path $RepoRoot ([string]$Rel)
        if (-not (Test-Path -LiteralPath $Path)) { continue }
        $Text = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
        if ($null -eq $Text) { continue }
        foreach ($Match in [regex]::Matches($Text, $Pattern)) {
            [void]$Markers.Add($Match.Value)
        }
    }
    return @($Markers | Sort-Object)
}

function Git-Text([string[]]$Args) {
    try {
        $Out = & git -C $RepoRoot @Args 2>$null
        if ($LASTEXITCODE -eq 0) { return (($Out | Out-String).Trim()) }
    } catch { }
    return $null
}

$Head = Git-Text @('rev-parse','HEAD')
$R65Ancestor = $null
if ($Head) {
    try {
        & git -C $RepoRoot merge-base --is-ancestor 13c465135455a31bf86aa8f2dfcd7c0e24088845 $Head 2>$null
        $R65Ancestor = ($LASTEXITCODE -eq 0)
    } catch { $R65Ancestor = $null }
}

$Rows = @()
foreach ($Req in $Manifest.requirements) {
    $Version = [string]$Req.version
    $EvidenceScripts = @($Req.evidence_scripts)
    $ExistingScripts = @()
    $MissingScripts = @()
    foreach ($Rel in $EvidenceScripts) {
        if (Test-Path -LiteralPath (Join-Path $RepoRoot ([string]$Rel))) { $ExistingScripts += [string]$Rel }
        else { $MissingScripts += [string]$Rel }
    }

    $Markers = Extract-VersionMarkers -Version $Version -EvidenceScripts $EvidenceScripts
    $MarkerEvidence = @()
    foreach ($Marker in $Markers) {
        $Hits = Find-InFiles -Needle $Marker -Files $RuntimeFiles
        $MarkerEvidence += [pscustomobject]@{
            marker = $Marker
            runtime_hits = @($Hits)
            materialized = ($Hits.Count -gt 0)
        }
    }

    $MaterializedCount = @($MarkerEvidence | Where-Object materialized).Count
    $Status = if ($Markers.Count -eq 0) {
        'manual_review_required'
    } elseif ($MaterializedCount -eq $Markers.Count) {
        'materialized_by_marker'
    } elseif ($MaterializedCount -gt 0) {
        'partial_by_marker'
    } else {
        'bootstrap_or_history_only'
    }

    $Rows += [pscustomobject]@{
        version = $Version
        capability = [string]$Req.capability
        status = $Status
        reference_branches = @($Req.reference_branches)
        evidence_scripts_present = @($ExistingScripts)
        evidence_scripts_missing = @($MissingScripts)
        extracted_markers = @($Markers)
        marker_evidence = @($MarkerEvidence)
    }
}

$Forbidden = @()
foreach ($Experiment in $Manifest.excluded_experiments) {
    $Marker = [string]$Experiment.marker
    $Hits = Find-InFiles -Needle $Marker -Files $RuntimeFiles
    $Forbidden += [pscustomobject]@{
        version = [string]$Experiment.version
        marker = $Marker
        runtime_hits = @($Hits)
        absent = ($Hits.Count -eq 0)
    }
}
$ForbiddenPass = @($Forbidden | Where-Object { -not $_.absent }).Count -eq 0

$Counts = [ordered]@{
    materialized_by_marker = @($Rows | Where-Object status -eq 'materialized_by_marker').Count
    partial_by_marker = @($Rows | Where-Object status -eq 'partial_by_marker').Count
    bootstrap_or_history_only = @($Rows | Where-Object status -eq 'bootstrap_or_history_only').Count
    manual_review_required = @($Rows | Where-Object status -eq 'manual_review_required').Count
}

$CarryForwardPass = ($Counts.partial_by_marker -eq 0 -and $Counts.bootstrap_or_history_only -eq 0 -and $Counts.manual_review_required -eq 0)
$Report = [ordered]@{
    schema_version = 1
    generated_at = (Get-Date).ToString('o')
    repo_root = $RepoRoot
    head = $Head
    r65_is_ancestor = $R65Ancestor
    note = 'r65 ancestry is historical evidence only and is not counted as runtime materialization.'
    runtime_roots = @($RuntimeRoots | ForEach-Object { [IO.Path]::GetRelativePath($RepoRoot, $_).Replace('\','/') })
    counts = $Counts
    carry_forward_pass = $CarryForwardPass
    r66_r69_runtime_absence_pass = $ForbiddenPass
    requirements = $Rows
    excluded_experiments = $Forbidden
    future_required_after_carry_forward = $Manifest.future_required_after_carry_forward
}

if (-not $NoReportFile) {
    $OutDir = Join-Path $RepoRoot '.work\carry-forward'
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $OutPath = Join-Path $OutDir 'r43-r65-report.json'
    $Report | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $OutPath -Encoding utf8NoBOM
    Write-Host "report: $OutPath"
}

Write-Host ''
Write-Host '=== r43-r65 carry-forward audit ==='
foreach ($Row in $Rows) {
    Write-Host ("{0,-4} {1,-27} {2}" -f $Row.version, $Row.status, $Row.capability)
}
Write-Host ''
Write-Host ("materialized={0} partial={1} bootstrap/history-only={2} manual-review={3}" -f `
    $Counts.materialized_by_marker, $Counts.partial_by_marker, $Counts.bootstrap_or_history_only, $Counts.manual_review_required)
Write-Host ("r66-r69 runtime absence: {0}" -f $(if ($ForbiddenPass) {'PASS'} else {'FAIL'}))

if ($ForbiddenPass) { Write-Host 'R79_R66_R69_EXPERIMENTS_ABSENT_PASS' -ForegroundColor Green }
else { Write-Host 'R79_R66_R69_EXPERIMENTS_ABSENT_FAIL' -ForegroundColor Red }

if ($CarryForwardPass) { Write-Host 'R79_R43_R65_CARRY_FORWARD_PASS' -ForegroundColor Green }
else { Write-Host 'R79_R43_R65_CARRY_FORWARD_INCOMPLETE' -ForegroundColor Yellow }

if ($FailOnMissing -and (-not $CarryForwardPass -or -not $ForbiddenPass)) { exit 2 }
