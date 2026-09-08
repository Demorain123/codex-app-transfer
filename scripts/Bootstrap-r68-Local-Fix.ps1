$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$bootstrap = Join-Path $RepoRoot 'scripts\Bootstrap-r68-Local.ps1'
if (-not (Test-Path -LiteralPath $bootstrap)) {
    throw 'Bootstrap-r68-Local.ps1 is missing; restore it from the r68 remote branch first.'
}

$text = Get-Content -LiteralPath $bootstrap -Raw -Encoding UTF8

$old = @'
    r67_call = "    sync_codex_hooks_selective_guard_r67();"
    if text.count(r67_call) != 2:
        raise SystemExit("r68 expected exactly two inherited r67 launch-pipeline calls")
    text = text.replace(r67_call, "    sync_codex_session_start_only_guard_r68();")
'@

$new = @'
    r67_call = "    sync_codex_hooks_selective_guard_r67();"
    # The newly inserted r68 helper intentionally calls r67 once internally.
    # Only replace the two inherited launch-pipeline calls that occur after
    # `fn open_codex_app`; otherwise replacing all three occurrences would make
    # the r68 helper recursively call itself.
    prefix, suffix = text.split(open_anchor, 1)
    if suffix.count(r67_call) != 2:
        raise SystemExit(
            f"r68 expected exactly two inherited r67 launch-pipeline calls after open_codex_app; found {suffix.count(r67_call)}"
        )
    suffix = suffix.replace(r67_call, "    sync_codex_session_start_only_guard_r68();")
    text = prefix + open_anchor + suffix
'@

if (-not $text.Contains($old)) {
    if ($text.Contains('prefix, suffix = text.split(open_anchor, 1)')) {
        Write-Host '[r68-fix] bootstrap already fixed; continuing.' -ForegroundColor Green
    } else {
        throw 'r68 hotfix anchor not found; refusing to rewrite an unknown bootstrap.'
    }
} else {
    $text = $text.Replace($old, $new)
    Set-Content -LiteralPath $bootstrap -Value $text -Encoding UTF8
    Write-Host '[r68-fix] fixed SessionStart helper/launch-call counting bug.' -ForegroundColor Green
}

Write-Host '[r68-fix] running corrected local bootstrap...' -ForegroundColor Cyan
& pwsh -NoProfile -ExecutionPolicy Bypass -File $bootstrap
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    throw "corrected r68 bootstrap failed with exit code $rc"
}
