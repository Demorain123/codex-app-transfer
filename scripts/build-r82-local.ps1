param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Selective = Join-Path $PSScriptRoot 'apply_r43_r65_selective_modern.py'
$R80Builder = Join-Path $PSScriptRoot 'build-r80-local.ps1'
$TempR82Builder = Join-Path $PSScriptRoot '.build-r82-from-r80.generated.ps1'

foreach ($Path in @($Selective, $R80Builder)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r82 required file missing: $Path" }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'r82 requires python on PATH' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'r82 requires git on PATH' }

$TrackedBefore = @(& git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r82 git status preflight failed' }
if ($TrackedBefore.Count -gt 0) {
    throw "r82 requires a clean tracked worktree. Use the dedicated r81/r82 worktree, not the dirty source worktree.`n$($TrackedBefore -join "`n")"
}

$SelectiveText = [System.IO.File]::ReadAllText($Selective)
if ([regex]::IsMatch($SelectiveText, 'scripts/apply_r\d+_unified\.py'.Replace('\\','\'))) {
    throw 'r82 selective materializer must never invoke historical recursive apply_rXX_unified.py drivers'
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$R80Text = [System.IO.File]::ReadAllText($R80Builder)

# r80 already composes the repaired exact-token collector and r78 action-row
# timestamp renderer. Generate r82 identity from that modern builder; do not
# route package construction through the failed recursive r81 materializer.
$R82Text = $R80Text.Replace('r80', 'r82').Replace('R80', 'R82').Replace('+80', '+82')
foreach ($Marker in @(
    "Replace('r76', 'r82').Replace('R76', 'R82').Replace('+76', '+82')",
    "Replace('r75', 'r82')",
    'R82_EXACT_TOKEN_TELEMETRY_PASS',
    'R82_TIMESTAMP_ACTIONROW_V4_PASS',
    'R82_EXACT_TELEMETRY_TARGETING_PASS'
)) {
    if (-not $R82Text.Contains($Marker)) { throw "r82 generated builder verification failed: $Marker" }
}
[System.IO.File]::WriteAllText($TempR82Builder, $R82Text, $Utf8NoBom)

try {
    Write-Host '[r82 1/4] Selectively materializing r43-r65 onto the current r70+ tree...' -ForegroundColor Cyan
    & python $Selective
    if ($LASTEXITCODE -ne 0) { throw "r82 selective materializer failed with exit code $LASTEXITCODE" }

    Write-Host '[r82 2/4] Confirming selective materialization changed tracked runtime sources...' -ForegroundColor Cyan
    $Changed = @(& git -C $RepoRoot diff --name-only --diff-filter=ACMRTUXB)
    if ($LASTEXITCODE -ne 0) { throw 'r82 could not enumerate materialized paths' }
    if ($Changed.Count -eq 0) { throw 'r82 produced no tracked carry-forward changes; refusing a false-positive package build' }
    Write-Host ("  materialized tracked paths: {0}" -f $Changed.Count)

    Write-Host '[r82 3/4] Building r82 observability + selective carry-forward package...' -ForegroundColor Cyan
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR82Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r82 package build failed with exit code $LASTEXITCODE" }

    Write-Host '[r82 4/4] Package completed; restoring tracked source tree...' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'R82_LOCAL_BUILD_PASS' -ForegroundColor Green
    Write-Host 'R82_R43_R65_CARRY_FORWARD_PACKAGE_PASS' -ForegroundColor Green
    Write-Host '  - r43-r65 were selectively materialized without replaying r24-r41'
    Write-Host '  - r66-r69 Hook A/B experiments were not materialized'
    Write-Host '  - r70 masked-history repair was hash-preserved during carry-forward'
    Write-Host '  - r78 timestamp action-row behavior and r80 exact telemetry targeting were retained'
    Write-Host '  - visible/package identity is r82 / 2.4.5+82'
}
finally {
    Remove-Item -LiteralPath $TempR82Builder -Force -ErrorAction SilentlyContinue

    # This build is allowed only from a clean dedicated worktree, so restoring
    # HEAD is safe. Restore both index and worktree because a historical leaf may
    # stage files. Do not git clean: generated package/cache artifacts stay intact.
    & git -C $RepoRoot restore --source=HEAD --staged --worktree -- . 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'r82 could not fully restore tracked sources; inspect git status before another build.'
    }
    $After = @(& git -C $RepoRoot status --porcelain --untracked-files=no 2>$null)
    if ($After.Count -eq 0) {
        Write-Host '[r82] tracked worktree restored clean; generated package artifacts are retained.'
    } else {
        Write-Warning ("r82 tracked worktree is not clean after restore:`n" + ($After -join "`n"))
    }
}
