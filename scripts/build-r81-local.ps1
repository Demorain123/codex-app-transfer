param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R64Unified = Join-Path $PSScriptRoot 'apply_r64_unified.py'
$R65Apply = Join-Path $PSScriptRoot 'apply_r65_startup_generation_gate.py'
$R80Builder = Join-Path $PSScriptRoot 'build-r80-local.ps1'

foreach ($Path in @($R64Unified, $R65Apply, $R80Builder)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r81 required file missing: $Path" }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'r81 requires python on PATH' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'r81 requires git on PATH' }

$TrackedBefore = @(& git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r81 git status preflight failed' }
if ($TrackedBefore.Count -gt 0) {
    throw "r81 refuses to materialize on a dirty tracked worktree. Commit/stash tracked changes first.`n$($TrackedBefore -join "`n")"
}

function Assert-Contains([string]$RelPath, [string[]]$Markers) {
    $Path = Join-Path $RepoRoot $RelPath
    if (-not (Test-Path -LiteralPath $Path)) { throw "r81 invariant file missing: $RelPath" }
    $Text = [System.IO.File]::ReadAllText($Path)
    foreach ($Marker in $Markers) {
        if (-not $Text.Contains($Marker)) { throw "r81 invariant missing in ${RelPath}: $Marker" }
    }
}

function Assert-ForbiddenRuntimeMarkersAbsent {
    $Roots = @('src-tauri\src','crates','frontend\src','resources')
    $Forbidden = @(
        'CAS-R66-POST-COMPACT-HOOKS-AB',
        'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE',
        'CAS-R68-SESSIONSTART-ONLY-HOOKS-AB',
        'CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB'
    )
    foreach ($RootRel in $Roots) {
        $Root = Join-Path $RepoRoot $RootRel
        if (-not (Test-Path -LiteralPath $Root)) { continue }
        foreach ($Marker in $Forbidden) {
            $Hit = Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
                Select-String -SimpleMatch -Pattern $Marker -List -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($Hit) { throw "r81 forbidden r66-r69 experimental runtime marker found: $Marker in $($Hit.Path)" }
        }
    }
}

$RestorePaths = @()
try {
    Write-Host '[r81 1/5] Materializing the reviewed cumulative r43-r64 chain...' -ForegroundColor Cyan
    & python $R64Unified
    if ($LASTEXITCODE -ne 0) { throw "r64 cumulative materializer failed with exit code $LASTEXITCODE" }

    Write-Host '[r81 2/5] Applying reusable r65 startup-generation gate...' -ForegroundColor Cyan
    & python $R65Apply
    if ($LASTEXITCODE -ne 0) { throw "r65 materializer failed with exit code $LASTEXITCODE" }

    Write-Host '[r81 3/5] Verifying carry-forward invariants and negative Hook-A/B boundary...' -ForegroundColor Cyan
    Assert-Contains 'crates\adapters\src\mapper\grok_build.rs' @(
        'CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD'
    )
    Assert-Contains 'src-tauri\src\admin\handlers\chain_health.rs' @(
        'CAS-R43-REWRITE-HEALTH-MCP',
        'CAS-R46-OLD-THREAD-RECOVERY-HINT',
        'CAS-R47-AGENT-LOOP-RECOVERY'
    )
    Assert-Contains 'crates\proxy\src\forward.rs' @(
        'CAS-R45-MODEL-SWITCH-CONTINUITY',
        'CAS-R45-COMPACTION-DETECTOR-SAFETY',
        'CAS-R45-COMPACTION-METADATA-TRUTH',
        'CAS-R45-RESPONSES-SEMANTIC-TERMINAL',
        'CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY',
        'CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE'
    )
    Assert-Contains 'src-tauri\src\admin\handlers\thread_recovery.rs' @(
        'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY',
        'CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY'
    )
    Assert-Contains 'src-tauri\src\admin\services\desktop\process.rs' @(
        'CAS-R47-CODEX-CUSTOM-TEMP',
        'CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD',
        'CAS-R61-LEGACY-COMPACTION-V1',
        'CAS-R64-POST-COMPACT-CONTINUATION-GUARD',
        'CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE'
    )
    Assert-Contains 'src-tauri\src\admin\services\mcp_servers.rs' @(
        'CAS-R55-DETACHED-MCP-HELPER',
        'CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION'
    )
    Assert-Contains 'crates\adapters\src\responses\compact.rs' @(
        'CAS-R51-COMPACT-HANDOFF-QUALITY',
        'CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK',
        'CAS-R62-COMPACT-SUMMARY-SELF-REPAIR'
    )
    Assert-Contains 'crates\adapters\src\mapper\sub2api_grok_compat.rs' @(
        'CAS-R60-SUB2API-POST-COMPACTION-REPLAY'
    )
    Assert-Contains 'crates\adapters\src\mapper\responses.rs' @(
        'CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK'
    )
    Assert-ForbiddenRuntimeMarkersAbsent

    $RestorePaths = @(& git -C $RepoRoot diff --name-only --diff-filter=ACMRTUXB)
    if ($LASTEXITCODE -ne 0) { throw 'r81 could not enumerate materialized paths' }
    if ($RestorePaths.Count -eq 0) { throw 'r81 materializer produced no tracked runtime changes; refusing a false-positive build' }

    Write-Host 'R81_R43_R65_MATERIALIZATION_GATE_PASS' -ForegroundColor Green
    Write-Host ("  - materialized tracked paths: {0}" -f $RestorePaths.Count)
    Write-Host '  - r44 terminal-semantics requirement is represented by the r45 semantic-terminal invariant'
    Write-Host '  - r66-r69 Hook A/B experimental runtime markers are absent'

    Write-Host '[r81 4/5] Building the current r80 observability/telemetry package on top of the materialized stack...' -ForegroundColor Cyan
    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$R80Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r81 package build failed with exit code $LASTEXITCODE" }

    Write-Host '[r81 5/5] Package complete; source restoration will run in finally.' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'R81_R43_R65_CARRY_FORWARD_PACKAGE_PASS' -ForegroundColor Green
    Write-Host '  - cumulative r43-r64 materializer completed before packaging'
    Write-Host '  - r65 startup-generation gate was composed on top'
    Write-Host '  - r80 exact telemetry targeting and r78 timestamp action-row behavior were retained'
    Write-Host '  - no r66-r69 Hook A/B experiment was materialized'
}
finally {
    $Changed = @(& git -C $RepoRoot diff --name-only --diff-filter=ACMRTUXB 2>$null)
    if ($Changed.Count -gt 0) {
        & git -C $RepoRoot restore --worktree -- $Changed
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'r81 could not fully restore materialized tracked sources; inspect git status before continuing.'
        }
    }
    $After = @(& git -C $RepoRoot status --porcelain --untracked-files=no 2>$null)
    if ($After.Count -eq 0) {
        Write-Host '[r81] tracked worktree restored clean; generated package artifacts are left intact.'
    } else {
        Write-Warning ("r81 tracked worktree is not clean after restore:`n" + ($After -join "`n"))
    }
}
