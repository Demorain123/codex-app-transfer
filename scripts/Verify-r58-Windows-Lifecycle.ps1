#requires -Version 7.0
$ErrorActionPreference = 'Stop'

$pkg = Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1
if ($null -eq $pkg) {
    Write-Host 'R58 WINDOWS LIFECYCLE: NO_CODEX_PACKAGE' -ForegroundColor Red
    exit 2
}
$targets = @(
    (Join-Path $pkg.InstallLocation 'app\ChatGPT.exe'),
    (Join-Path $pkg.InstallLocation 'app\Codex.exe')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
$mainExe = $targets | Select-Object -First 1
if (-not $mainExe) {
    Write-Host 'R58 WINDOWS LIFECYCLE: MAIN_EXE_NOT_FOUND' -ForegroundColor Red
    Write-Host "Package: $($pkg.InstallLocation)"
    exit 3
}

$rows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$main = @($rows | Where-Object {
    $_.ExecutablePath -and
    [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath),[IO.Path]::GetFullPath([string]$mainExe),[StringComparison]::OrdinalIgnoreCase)
})
$appServer = @($rows | Where-Object { $_.Name -ieq 'codex.exe' })
$staleWebfetch = @($rows | Where-Object {
    $_.Name -ieq 'codex-app-transfer.exe' -and
    $_.CommandLine -and
    ([string]$_.CommandLine -match '--mcp-serve(?:=|-)webfetch')
})
$detachedWebfetch = @($rows | Where-Object {
    $_.ExecutablePath -and
    ([string]$_.ExecutablePath -match '\\.codex-app-transfer\\mcp-bin\\codex-app-transfer-mcp-[^\\]+\.exe$') -and
    $_.CommandLine -and
    ([string]$_.CommandLine -match '--mcp-serve(?:=|-)webfetch')
})

Write-Host "OpenAI.Codex main EXE: $mainExe" -ForegroundColor Cyan
Write-Host "Main process count   : $($main.Count)"
$main | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath | Format-Table -AutoSize
Write-Host "codex.exe child count: $($appServer.Count)"
$appServer | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath | Format-Table -AutoSize
Write-Host "Detached webfetch    : $($detachedWebfetch.Count)"
$detachedWebfetch | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath | Format-Table -AutoSize
Write-Host "STALE main-EXE MCP   : $($staleWebfetch.Count)"
$staleWebfetch | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | Format-Table -AutoSize

if ($staleWebfetch.Count -gt 0) {
    Write-Host 'R58 WINDOWS LIFECYCLE: HOST_RESTART_REQUIRED' -ForegroundColor Yellow
    Write-Host 'An external MCP host is still running the installed main Transfer EXE. Restart OMP/CC Switch once.'
    exit 10
}

Write-Host 'R58 WINDOWS LIFECYCLE: PASS' -ForegroundColor Green
Write-Host 'Restart logic may now target only the exact OpenAI.Codex package main executable; internal codex.exe is diagnostic-only here.'
exit 0
