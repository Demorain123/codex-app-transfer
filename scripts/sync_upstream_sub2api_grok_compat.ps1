#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$UpstreamUrl = 'https://github.com/Cmochance/codex-app-transfer.git',
    [string]$UpstreamRef = 'main',
    [string]$RemoteName = 'upstream',
    [string]$SourceCompatBranch = 'sub2api-grok-compat',
    [string]$NewBranch = '',
    [switch]$SkipFrontend,
    [switch]$SkipTests
)

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

function Require-CleanWorktree {
    $dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Not inside a Git repository.' }
    if ($dirty) {
        throw 'Working tree is not clean. Commit/stash your changes before syncing upstream.'
    }
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw 'Could not determine repository root.' }
Set-Location $repoRoot
Require-CleanWorktree

if (-not $NewBranch) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $NewBranch = "sub2api-grok-compat-next-$stamp"
}

Write-Host 'Sub2API Grok Compat - safe upstream sync' -ForegroundColor Green
Write-Host "Repository     : $repoRoot"
Write-Host "Upstream       : $UpstreamUrl ($UpstreamRef)"
Write-Host "Overlay source : $SourceCompatBranch"
Write-Host "New branch     : $NewBranch"

# Keep the overlay assets outside the worktree while switching to a clean
# upstream-based branch. The official source itself is never copied from the old
# compat branch; only patch/build/docs assets are carried forward.
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("cat-sub2api-overlay-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp -Force | Out-Null

$assets = @(
    'scripts/apply_sub2api_grok_compat.py',
    'scripts/apply_sub2api_grok_compat_ui.py',
    'scripts/build_sub2api_grok_compat_windows.ps1',
    'scripts/sync_upstream_sub2api_grok_compat.ps1',
    '.github/workflows/apply-sub2api-grok-compat.yml',
    '.github/workflows/build-sub2api-grok-compat-windows.yml',
    'SUB2API_GROK_COMPAT.md'
)

try {
    foreach ($asset in $assets) {
        $dest = Join-Path $temp $asset
        New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
        $content = git show "${SourceCompatBranch}:$asset"
        if ($LASTEXITCODE -ne 0) {
            throw "Overlay asset missing from ${SourceCompatBranch}: $asset"
        }
        [System.IO.File]::WriteAllLines($dest, [string[]]$content, [System.Text.UTF8Encoding]::new($false))
    }

    $remoteExists = git remote | Where-Object { $_ -eq $RemoteName }
    if (-not $remoteExists) {
        Invoke-Checked git 'remote' 'add' $RemoteName $UpstreamUrl
    } else {
        $current = (git remote get-url $RemoteName).Trim()
        if ($current -ne $UpstreamUrl) {
            Write-Host "Updating $RemoteName URL: $current -> $UpstreamUrl" -ForegroundColor Yellow
            Invoke-Checked git 'remote' 'set-url' $RemoteName $UpstreamUrl
        }
    }

    Invoke-Checked git 'fetch' $RemoteName '--prune' '--tags'
    $baseRef = "$RemoteName/$UpstreamRef"
    Invoke-Checked git 'rev-parse' '--verify' $baseRef

    # Refuse to overwrite any existing branch. A sync must always create a fresh,
    # reviewable candidate so the currently working compat build remains intact.
    & git show-ref --verify --quiet "refs/heads/$NewBranch"
    if ($LASTEXITCODE -eq 0) {
        throw "Branch already exists: $NewBranch. Choose another -NewBranch."
    }

    Invoke-Checked git 'switch' '--create' $NewBranch $baseRef

    foreach ($asset in $assets) {
        $src = Join-Path $temp $asset
        $dest = Join-Path $repoRoot $asset
        New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dest -Force
    }

    Write-Host "`nApplying isolated overlay..." -ForegroundColor Green
    Invoke-Checked python 'scripts/apply_sub2api_grok_compat.py'
    Invoke-Checked python 'scripts/apply_sub2api_grok_compat_ui.py'
    Invoke-Checked cargo 'fmt' '--all'

    if (-not $SkipFrontend) {
        Invoke-Checked npm '--prefix' 'frontend' 'ci'
        Invoke-Checked npm '--prefix' 'frontend' 'run' 'build'
    }

    if (-not $SkipTests) {
        Invoke-Checked cargo 'test' '-p' 'codex-app-transfer-adapters' '--lib' '--' '--nocapture'
    }

    $baseSha = (git rev-parse $baseRef).Trim()
    Set-Content -LiteralPath 'SUB2API_GROK_COMPAT_UPSTREAM_BASE.txt' -Value "$baseRef`n$baseSha`n" -Encoding utf8NoBOM

    Invoke-Checked git 'add' '-A'
    Invoke-Checked git 'commit' '-m' "feat: apply Sub2API Grok compat overlay onto $baseRef ($baseSha)"

    Write-Host "`nCandidate branch created successfully." -ForegroundColor Green
    Write-Host "  Branch : $NewBranch"
    Write-Host "  Base   : $baseRef @ $baseSha"
    Write-Host 'Your current working compat branch was not overwritten.'
    Write-Host 'Build/test this candidate first, then promote it only after real Codex/Sub2API validation.' -ForegroundColor Yellow
}
finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
