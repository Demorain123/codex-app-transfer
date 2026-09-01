$ErrorActionPreference = 'Stop'

$rows = @()
$servers = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match '--mcp-serve-webfetch'
}

foreach ($p in $servers) {
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
    $exe = [string]$p.ExecutablePath
    $normalized = $exe.Replace('/', '\')
    $detached = $normalized -match '\\.codex-app-transfer\\mcp-bin\\codex-app-transfer-mcp-[0-9a-f]+\.exe$'
    $rows += [pscustomobject]@{
        PID = $p.ProcessId
        Parent = $parent.Name
        ParentPID = $p.ParentProcessId
        ExecutablePath = $exe
        Detached = $detached
    }
}

if ($rows.Count -eq 0) {
    Write-Host 'R55 MCP DETACH: NO_ACTIVE_HELPER'
    Write-Host 'No --mcp-serve-webfetch process is active. Start/restart the MCP host once, then run this verifier again.'
    exit 0
}

$rows | Format-Table -AutoSize

$legacy = @($rows | Where-Object { -not $_.Detached })
if ($legacy.Count -gt 0) {
    Write-Host ''
    Write-Host 'R55 MCP DETACH: HOST_RESTART_REQUIRED' -ForegroundColor Yellow
    Write-Host 'The external MCP host is still using the pre-r55 install-directory command cached in memory.'
    Write-Host 'Exit/restart that host once after r55 has launched and synced config, then rerun this script.'
    exit 2
}

Write-Host ''
Write-Host 'R55 MCP DETACH: PASS' -ForegroundColor Green
Write-Host 'All active webfetch MCP servers use detached user-data helper executables.'
Write-Host 'The installed main codex-app-transfer.exe is no longer held by these MCP processes.'
exit 0
