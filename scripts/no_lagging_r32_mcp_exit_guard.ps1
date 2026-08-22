# CAS-NO-LAGGING-R32-MCP-EXIT-GUARD
# CAS-R43-REWRITE-POST-CLEANUP-VERIFICATION
# Background Windows watcher for Codex Desktop generations.
# It never terminates helpers while the exact Codex Desktop executable is running.
# It does not read or log process command lines, prompts, tokens, or thread content.
param(
  [ValidateRange(1,30)][int]$PollSeconds = 2,
  [ValidateRange(5,300)][int]$InventorySeconds = 15,
  [ValidateRange(3,120)][int]$ExitStableSeconds = 8,
  [ValidateRange(0,120)][int]$CleanupGraceSeconds = 5,
  [ValidateRange(30,1800)][int]$MissingExecutableExitSeconds = 60
)

$ErrorActionPreference = 'Stop'
$ExactCodexExe = $env:CAS_NO_LAGGING_EXE
if ([string]::IsNullOrWhiteSpace($ExactCodexExe)) { exit 20 }
try { $ExactCodexExe = [IO.Path]::GetFullPath($ExactCodexExe) } catch { exit 21 }

$stateDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexMcpJanitorR32'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$logPath = Join-Path $stateDir 'events.jsonl'

# Key the singleton to the exact packaged executable path.
$sha = [Security.Cryptography.SHA256]::Create()
try {
  $hashBytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($ExactCodexExe.ToLowerInvariant()))
  $mutexSuffix = ([BitConverter]::ToString($hashBytes)).Replace('-','').Substring(0,16)
} finally { $sha.Dispose() }
$mutexName = "Local\CodexAppTransfer_NoLagging_R32_$mutexSuffix"
$created = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$created)
if (-not $created) { $mutex.Dispose(); exit 0 }

$runtimeNames = @('node','node_repl','python','python3','pythonw','uv','uvx','npx','deno','bun','dotnet','java')
$knownPattern = '(?i)(mcp|node_repl|playwright|context7|tavily|fast-context|ask-user|ai-search|grok-search|kindly|chrome-devtools|contextweaver|sites-design-picker)'
$tracked = @{}
$seenDesktop = $false
$zeroSince = $null
$lastInventoryUtc = [DateTime]::MinValue
$generationDesktopIds = @{}
$missingExecutableSince = $null

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

function Start-Ticks($creationDate) {
  try { return ([datetime]$creationDate).ToUniversalTime().Ticks } catch { return $null }
}

# CAS-NO-LAGGING-R32-LIGHT-DESKTOP-POLL
# This is the cheap heartbeat. Full process topology stays in the slower inventory path.
function Get-DesktopProcessesCheap {
  $matches = @()
  foreach ($p in @(Get-Process -Name 'ChatGPT','Codex' -ErrorAction SilentlyContinue)) {
    try { $path = [string]$p.Path } catch { continue }
    if ([string]::IsNullOrWhiteSpace($path)) { continue }
    try { $full = [IO.Path]::GetFullPath($path) } catch { continue }
    if ([string]::Equals($full, $ExactCodexExe, [StringComparison]::OrdinalIgnoreCase)) {
      $matches += $p
    }
  }
  return @($matches)
}

# CAS-NO-LAGGING-R32-HEAVY-INVENTORY
# Full parent topology is intentionally much less frequent than the desktop heartbeat.
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
    $startTicks = Start-Ticks $p.CreationDate
    if ($null -eq $startTicks) { continue }
    $tracked[$pid] = [pscustomobject]@{
      Pid = $pid
      ParentPid = [int]$p.ParentProcessId
      StartTicks = [long]$startTicks
      Path = if ($p.ExecutablePath) { [string]$p.ExecutablePath } else { $null }
      Name = $base
      Depth = [int]$ancestry.Depth
      DesktopPid = [int]$ancestry.DesktopPid
    }
    $added++
  }
  if ($added -gt 0) { Write-Event 'helper_tracked' @{ added=$added; tracked=$tracked.Count } }
}

# Exact-PID cleanup validation uses process identity and avoids per-PID CIM calls.
function Same-Identity($record) {
  try {
    $p = Get-Process -Id ([int]$record.Pid) -ErrorAction Stop
    $ticks = $p.StartTime.ToUniversalTime().Ticks
    if ([long]$ticks -ne [long]$record.StartTicks) { return $false }
    if ($record.Path) {
      try { $path = [string]$p.Path } catch { return $false }
      if ([string]::IsNullOrWhiteSpace($path)) { return $false }
      if (-not [string]::Equals([IO.Path]::GetFullPath($path),[IO.Path]::GetFullPath([string]$record.Path),[StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    return $true
  } catch { return $false }
}

function Cleanup-OldGeneration {
  $desktop = @(Get-DesktopProcessesCheap)
  if ($desktop.Count -gt 0) {
    Write-Event 'cleanup_cancelled_desktop_reappeared' @{ desktop=$desktop.Count; tracked=$tracked.Count }
    return $false
  }

  $targets = @($tracked.Values | Where-Object { Same-Identity $_ } | Sort-Object Depth -Descending)
  $stopped = 0
  foreach ($r in $targets) {
    if (@(Get-DesktopProcessesCheap).Count -gt 0) {
      Write-Event 'cleanup_cancelled_desktop_reappeared' @{ stopped=$stopped }
      return $false
    }
    if (-not (Same-Identity $r)) { continue }
    try {
      Stop-Process -Id $r.Pid -Force -ErrorAction Stop
      $stopped++
      Write-Event 'helper_stopped' @{ pid=$r.Pid; name=$r.Name }
    } catch {
      Write-Event 'helper_stop_failed' @{ pid=$r.Pid; name=$r.Name }
    }
  }

  # CAS-R43: re-check the exact PID + creation-time/path identity after termination.
  # Cleanup never broadens from the tracked identity set to an executable-name-wide scope.
  Start-Sleep -Milliseconds 250
  $remaining = @($targets | Where-Object { Same-Identity $_ })
  Write-Event 'cleanup_verified' @{ attempted=$targets.Count; stopped=$stopped; remaining=$remaining.Count }
  Write-Event 'cleanup_complete' @{ tracked=$tracked.Count; attempted=$targets.Count; survivors=$remaining.Count; stopped=$stopped }
  return $true
}

Write-Event 'guard_started' @{ pollSeconds=$PollSeconds; inventorySeconds=$InventorySeconds; stableSeconds=$ExitStableSeconds; graceSeconds=$CleanupGraceSeconds }
try {
  while ($true) {
    $desktop = @(Get-DesktopProcessesCheap)
    if ($desktop.Count -gt 0) {
      $missingExecutableSince = $null
      if (-not $seenDesktop) {
        $seenDesktop = $true
        $tracked.Clear()
        $generationDesktopIds = @{}
        $lastInventoryUtc = [DateTime]::MinValue
        Write-Event 'desktop_generation_started' @{ desktop=$desktop.Count }
      }
      foreach ($p in $desktop) { $generationDesktopIds[[int]$p.Id] = $true }
      $zeroSince = $null

      $nowUtc = [DateTime]::UtcNow
      if (($nowUtc - $lastInventoryUtc).TotalSeconds -ge $InventorySeconds) {
        try {
          $inv = Get-Inventory
          Track-Candidates $inv
          $lastInventoryUtc = $nowUtc
        } catch {
          Write-Event 'inventory_failed'
        }
      }
      Start-Sleep -Seconds $PollSeconds
      continue
    }

    if (-not $seenDesktop) {
      if (-not (Test-Path -LiteralPath $ExactCodexExe -PathType Leaf)) {
        if ($null -eq $missingExecutableSince) {
          $missingExecutableSince = Get-Date
        } elseif (((Get-Date) - $missingExecutableSince).TotalSeconds -ge $MissingExecutableExitSeconds) {
          Write-Event 'guard_retired_missing_executable'
          break
        }
      } else {
        $missingExecutableSince = $null
      }
      Start-Sleep -Seconds $PollSeconds
      continue
    }

    if ($null -eq $zeroSince) {
      $zeroSince = Get-Date
      try {
        $finalInv = Get-Inventory
        $finalInv.DesktopIds = $generationDesktopIds
        Track-Candidates $finalInv
      } catch {
        Write-Event 'final_inventory_failed'
      }
      Write-Event 'desktop_zero_detected' @{ tracked=$tracked.Count }
    }
    $elapsed = ((Get-Date) - $zeroSince).TotalSeconds
    if ($elapsed -lt $ExitStableSeconds) { Start-Sleep -Seconds $PollSeconds; continue }

    if ($CleanupGraceSeconds -gt 0) { Start-Sleep -Seconds $CleanupGraceSeconds }
    if (Cleanup-OldGeneration) {
      $seenDesktop = $false
      $zeroSince = $null
      $tracked.Clear()
      $generationDesktopIds = @{}
      Write-Event 'guard_waiting_next_generation'
    } else {
      $seenDesktop = $false
      $zeroSince = $null
      $tracked.Clear()
      $generationDesktopIds = @{}
    }
  }
} finally {
  Write-Event 'guard_stopped'
  try { $mutex.ReleaseMutex() } catch {}
  $mutex.Dispose()
}
