# CAS-NO-LAGGING-R32-MCP-EXIT-GUARD
# Background Windows watcher for Codex Desktop generations.
# It never terminates helpers while the exact Codex Desktop executable is running.
# It does not read or log process command lines, prompts, tokens, or thread content.
param(
  [ValidateRange(1,30)][int]$PollSeconds = 2,
  [ValidateRange(3,120)][int]$ExitStableSeconds = 8,
  [ValidateRange(0,120)][int]$CleanupGraceSeconds = 5
)

$ErrorActionPreference = 'Stop'
$ExactCodexExe = $env:CAS_NO_LAGGING_EXE
if ([string]::IsNullOrWhiteSpace($ExactCodexExe)) { exit 20 }
try { $ExactCodexExe = [IO.Path]::GetFullPath($ExactCodexExe) } catch { exit 21 }

$stateDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexMcpJanitorR32'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$logPath = Join-Path $stateDir 'events.jsonl'
$mutexName = 'Local\CodexAppTransfer_NoLagging_R32_McpExitGuard'
$created = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$created)
if (-not $created) { $mutex.Dispose(); exit 0 }

$runtimeNames = @('node','node_repl','python','python3','pythonw','uv','uvx','npx','deno','bun','dotnet','java')
$knownPattern = '(?i)(mcp|node_repl|playwright|context7|tavily|fast-context|ask-user|ai-search|grok-search|kindly|chrome-devtools|contextweaver|sites-design-picker)'
$tracked = @{}
$seenDesktop = $false
$zeroSince = $null

function Write-Event([string]$eventName, [hashtable]$data = @{}) {
  try {
    $obj = [ordered]@{ ts = [DateTime]::UtcNow.ToString('o'); event = $eventName }
    foreach ($k in $data.Keys) { $obj[$k] = $data[$k] }
    Add-Content -LiteralPath $logPath -Value (($obj | ConvertTo-Json -Compress -Depth 4)) -Encoding UTF8
  } catch {}
}

function Base-Name([string]$name) {
  $n = [IO.Path]::GetFileNameWithoutExtension($name).ToLowerInvariant()
  return $n
}

function Start-Utc($creationDate) {
  try { return ([datetime]$creationDate).ToUniversalTime().ToString('o') } catch { return $null }
}

function Get-Inventory {
  $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CreationDate)
  $byId = @{}
  foreach ($p in $rows) { $byId[[int]$p.ProcessId] = $p }
  $desktop = @($rows | Where-Object {
    ($_.Name -ieq 'ChatGPT.exe' -or $_.Name -ieq 'Codex.exe') -and
    $_.ExecutablePath -and
    [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath), $ExactCodexExe, [StringComparison]::OrdinalIgnoreCase)
  })
  $desktopIds = @{}
  foreach ($p in $desktop) { $desktopIds[[int]$p.ProcessId] = $true }
  return [pscustomobject]@{ Rows=$rows; ById=$byId; Desktop=$desktop; DesktopIds=$desktopIds }
}

function Get-Desktop-Ancestry($p, [hashtable]$byId, [hashtable]$desktopIds) {
  $pid = [int]$p.ProcessId
  if ($desktopIds.ContainsKey($pid)) { return [pscustomobject]@{ Match=$true; Depth=0; DesktopPid=$pid } }
  $visited = @{}
  $parent = [int]$p.ParentProcessId
  for ($depth=1; $depth -le 64; $depth++) {
    if ($parent -le 0 -or $visited.ContainsKey($parent)) { break }
    $visited[$parent] = $true
    if ($desktopIds.ContainsKey($parent)) { return [pscustomobject]@{ Match=$true; Depth=$depth; DesktopPid=$parent } }
    if (-not $byId.ContainsKey($parent)) { break }
    $parent = [int]$byId[$parent].ParentProcessId
  }
  return [pscustomobject]@{ Match=$false; Depth=0; DesktopPid=$null }
}

function Track-Candidates($inv) {
  $added = 0
  foreach ($p in $inv.Rows) {
    $ancestry = Get-Desktop-Ancestry $p $inv.ById $inv.DesktopIds
    if (-not $ancestry.Match -or $ancestry.Depth -eq 0) { continue }
    $base = Base-Name ([string]$p.Name)
    $candidate = ($base -match $knownPattern) -or ($runtimeNames -contains $base)
    if (-not $candidate) { continue }
    $pid = [int]$p.ProcessId
    if ($tracked.ContainsKey($pid)) { continue }
    $start = Start-Utc $p.CreationDate
    if ([string]::IsNullOrWhiteSpace($start)) { continue }
    $tracked[$pid] = [pscustomobject]@{
      Pid = $pid
      ParentPid = [int]$p.ParentProcessId
      StartUtc = $start
      Path = if ($p.ExecutablePath) { [string]$p.ExecutablePath } else { $null }
      Name = $base
      Depth = [int]$ancestry.Depth
      DesktopPid = [int]$ancestry.DesktopPid
    }
    $added++
  }
  if ($added -gt 0) { Write-Event 'helper_tracked' @{ added=$added; tracked=$tracked.Count } }
}

function Same-Identity($record) {
  try {
    $p = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $record.Pid) -ErrorAction Stop
    if ($null -eq $p) { return $false }
    $start = Start-Utc $p.CreationDate
    if ($start -ne $record.StartUtc) { return $false }
    if ($record.Path -and $p.ExecutablePath -and -not [string]::Equals([string]$p.ExecutablePath,[string]$record.Path,[StringComparison]::OrdinalIgnoreCase)) { return $false }
    return $true
  } catch { return $false }
}

function Cleanup-OldGeneration {
  try {
    $guard = Get-Inventory
    if ($guard.Desktop.Count -gt 0) {
      Write-Event 'cleanup_cancelled_desktop_reappeared' @{ desktop=$guard.Desktop.Count; tracked=$tracked.Count }
      return $false
    }
  } catch {
    Write-Event 'cleanup_cancelled_inventory_error' @{ tracked=$tracked.Count }
    return $false
  }

  $survivors = @($tracked.Values | Where-Object { Same-Identity $_ } | Sort-Object Depth -Descending)
  $stopped = 0
  foreach ($r in $survivors) {
    # Race guard immediately before every stop.
    try {
      $guard = Get-Inventory
      if ($guard.Desktop.Count -gt 0) {
        Write-Event 'cleanup_cancelled_desktop_reappeared' @{ desktop=$guard.Desktop.Count; stopped=$stopped }
        return $false
      }
    } catch { return $false }
    if (-not (Same-Identity $r)) { continue }
    try {
      Stop-Process -Id $r.Pid -Force -ErrorAction Stop
      $stopped++
      Write-Event 'helper_stopped' @{ pid=$r.Pid; name=$r.Name }
    } catch {
      Write-Event 'helper_stop_failed' @{ pid=$r.Pid; name=$r.Name }
    }
  }
  Write-Event 'cleanup_complete' @{ tracked=$tracked.Count; survivors=$survivors.Count; stopped=$stopped }
  return $true
}

Write-Event 'guard_started' @{ pollSeconds=$PollSeconds; stableSeconds=$ExitStableSeconds; graceSeconds=$CleanupGraceSeconds }
try {
  while ($true) {
    try { $inv = Get-Inventory } catch { Write-Event 'inventory_failed'; Start-Sleep -Seconds $PollSeconds; continue }
    if ($inv.Desktop.Count -gt 0) {
      if (-not $seenDesktop) {
        $seenDesktop = $true
        $tracked.Clear()
        Write-Event 'desktop_generation_started' @{ desktop=$inv.Desktop.Count }
      }
      $zeroSince = $null
      Track-Candidates $inv
      Start-Sleep -Seconds $PollSeconds
      continue
    }

    if (-not $seenDesktop) { Start-Sleep -Seconds $PollSeconds; continue }
    if ($null -eq $zeroSince) {
      $zeroSince = Get-Date
      Write-Event 'desktop_zero_detected' @{ tracked=$tracked.Count }
    }
    $elapsed = ((Get-Date) - $zeroSince).TotalSeconds
    if ($elapsed -lt $ExitStableSeconds) { Start-Sleep -Seconds $PollSeconds; continue }

    if ($CleanupGraceSeconds -gt 0) { Start-Sleep -Seconds $CleanupGraceSeconds }
    if (Cleanup-OldGeneration) {
      $seenDesktop = $false
      $zeroSince = $null
      $tracked.Clear()
      Write-Event 'guard_waiting_next_generation'
    } else {
      # Safety wins over cleanup. Re-enter discovery and build fresh ownership evidence.
      $seenDesktop = $false
      $zeroSince = $null
      $tracked.Clear()
    }
  }
} finally {
  Write-Event 'guard_stopped'
  try { $mutex.ReleaseMutex() } catch {}
  $mutex.Dispose()
}
