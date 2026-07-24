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
        [string[]]$Arguments = @()
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

function Resolve-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Command = 'python'; Prefix = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Command = 'py'; Prefix = @('-3') }
    }
    throw 'Python 3 was not found. Install Python 3 or make python/py available in PATH.'
}

function Resolve-UpstreamGitRef {
    param(
        [Parameter(Mandatory)][string]$Remote,
        [Parameter(Mandatory)][string]$RequestedRef
    )

    # Prefer an explicit remote branch when both a branch and tag share a name.
    $remoteBranch = "refs/remotes/$Remote/$RequestedRef"
    & git show-ref --verify --quiet $remoteBranch
    if ($LASTEXITCODE -eq 0) {
        return "$Remote/$RequestedRef"
    }

    $tagRef = "refs/tags/$RequestedRef"
    & git show-ref --verify --quiet $tagRef
    if ($LASTEXITCODE -eq 0) {
        return $tagRef
    }

    # Finally accept an explicit commit-ish/SHA fetched into the repository.
    & git rev-parse --verify --quiet "$RequestedRef^{commit}" *> $null
    if ($LASTEXITCODE -eq 0) {
        return $RequestedRef
    }

    throw "Could not resolve upstream ref '$RequestedRef' as $Remote branch, tag, or commit SHA."
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw 'Could not determine repository root.' }
Set-Location $repoRoot
Require-CleanWorktree

$python = Resolve-Python

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
    'scripts/sub2api_grok_compat_overlay.rs',
    'scripts/apply_sub2api_grok_compat_ui.py',
    'scripts/migrate_sub2api_grok_ui_to_overlay.py',
    'scripts/build_sub2api_grok_compat_windows.ps1',
    'scripts/sync_upstream_sub2api_grok_compat.ps1',
    '.github/workflows/apply-sub2api-grok-compat.yml',
    '.github/workflows/build-sub2api-grok-compat-windows.yml',
    '.github/workflows/validate-sub2api-grok-overlay-on-upstream.yml',
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
        Invoke-Checked -Command git -Arguments @('remote', 'add', $RemoteName, $UpstreamUrl)
    } else {
        $current = (git remote get-url $RemoteName).Trim()
        if ($current -ne $UpstreamUrl) {
            Write-Host "Updating $RemoteName URL: $current -> $UpstreamUrl" -ForegroundColor Yellow
            Invoke-Checked -Command git -Arguments @('remote', 'set-url', $RemoteName, $UpstreamUrl)
        }
    }

    Invoke-Checked -Command git -Arguments @('fetch', $RemoteName, '--prune', '--tags')
    $baseRef = Resolve-UpstreamGitRef -Remote $RemoteName -RequestedRef $UpstreamRef
    $baseSha = (git rev-parse "$baseRef^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $baseSha) {
        throw "Could not resolve commit for upstream base: $baseRef"
    }
    Write-Host "Resolved base   : $baseRef @ $baseSha"

    # Refuse to overwrite any existing branch. A sync must always create a fresh,
    # reviewable candidate so the currently working compat build remains intact.
    & git show-ref --verify --quiet "refs/heads/$NewBranch"
    if ($LASTEXITCODE -eq 0) {
        throw "Branch already exists: $NewBranch. Choose another -NewBranch."
    }

    Invoke-Checked -Command git -Arguments @('switch', '--create', $NewBranch, $baseSha)

    foreach ($asset in $assets) {
        $src = Join-Path $temp $asset
        $dest = Join-Path $repoRoot $asset
        New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dest -Force
    }

    Write-Host "`nApplying isolated overlay..." -ForegroundColor Green
    Invoke-Checked -Command $python.Command -Arguments (@($python.Prefix) + @('scripts/apply_sub2api_grok_compat.py'))
    Invoke-Checked -Command $python.Command -Arguments (@($python.Prefix) + @('scripts/apply_sub2api_grok_compat_ui.py'))
    Invoke-Checked -Command cargo -Arguments @('fmt', '--all')

    if (-not $SkipFrontend) {
        Invoke-Checked -Command npm -Arguments @('--prefix', 'frontend', 'ci')
        Invoke-Checked -Command npm -Arguments @('--prefix', 'frontend', 'run', 'build')
    }

    if (-not $SkipTests) {
        Invoke-Checked -Command cargo -Arguments @('test', '-p', 'codex-app-transfer-adapters', '--lib', '--', '--nocapture')
    }

    Set-Content -LiteralPath 'SUB2API_GROK_COMPAT_UPSTREAM_BASE.txt' -Value "$baseRef`n$baseSha`n" -Encoding utf8NoBOM

    Invoke-Checked -Command git -Arguments @('add', '-A')
    Invoke-Checked -Command git -Arguments @('commit', '-m', "feat: apply Sub2API Grok compat overlay onto $baseRef ($baseSha)")

    Write-Host "`nCandidate branch created successfully." -ForegroundColor Green
    Write-Host "  Branch : $NewBranch"
    Write-Host "  Base   : $baseRef @ $baseSha"
    Write-Host 'Your current working compat branch was not overwritten.'
    Write-Host 'Build/test this candidate first, then promote it only after real Codex/Sub2API validation.' -ForegroundColor Yellow
}
finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
