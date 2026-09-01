param()

$ErrorActionPreference = 'Stop'
$homeDir = [Environment]::GetFolderPath('UserProfile')
$detachedNeedle = '\.codex-app-transfer\mcp-bin\'
$oldExeName = 'codex-app-transfer.exe'

function Is-DetachedPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return $Path.Replace('/', '\').ToLowerInvariant().Contains($detachedNeedle)
}

function Is-WebFetchArgs($ArgsValue) {
    if ($null -eq $ArgsValue) { return $false }
    foreach ($a in @($ArgsValue)) {
        if ($a -eq '--mcp-serve-webfetch' -or $a -eq '--mcp-serve=webfetch') { return $true }
    }
    return $false
}

$sourceProblems = New-Object System.Collections.Generic.List[string]
$sourceSeen = New-Object System.Collections.Generic.List[string]

Write-Host '=== Active Transfer webfetch processes ===' -ForegroundColor Cyan
$active = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -match 'mcp-serve(?:=|-)webfetch' -or
        $_.CommandLine -match 'mcp-serve-webfetch'
    }
if ($active) {
    $active | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | Format-Table -AutoSize
} else {
    Write-Host '(none)'
}
$oldActive = @($active | Where-Object { $_.ExecutablePath -and -not (Is-DetachedPath $_.ExecutablePath) })

Write-Host ''
Write-Host '=== Codex live cat-webfetch ===' -ForegroundColor Cyan
$codexConfig = Join-Path $homeDir '.codex\config.toml'
if (Test-Path -LiteralPath $codexConfig) {
    $raw = Get-Content -LiteralPath $codexConfig -Raw -Encoding UTF8
    $m = [regex]::Match($raw, '(?ms)^\[mcp_servers\.cat-webfetch\]\s*(.*?)(?=^\[|\z)')
    if ($m.Success) {
        $cmd = [regex]::Match($m.Groups[1].Value, '(?m)^\s*command\s*=\s*"([^"]+)"').Groups[1].Value
        Write-Host "command=$cmd"
        $sourceSeen.Add('codex-live')
        if (-not (Is-DetachedPath $cmd)) { $sourceProblems.Add("codex-live:$cmd") }
    } else {
        Write-Host '(cat-webfetch block not found)'
    }
} else {
    Write-Host '(config.toml not found)'
}

Write-Host ''
Write-Host '=== CC Switch persistent MCP source ===' -ForegroundColor Cyan
$ccDb = Join-Path $homeDir '.cc-switch\cc-switch.db'
$python = Get-Command python -ErrorAction SilentlyContinue
if ((Test-Path -LiteralPath $ccDb) -and $python) {
    $py = @'
import json, sqlite3, sys
p=sys.argv[1]
con=sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1.5)
try:
    rows=con.execute("SELECT id,name,server_config FROM mcp_servers WHERE enabled_codex != 0").fetchall()
except Exception as e:
    print("__ERROR__="+str(e))
    raise SystemExit(0)
for i,n,raw in rows:
    try: v=json.loads(raw)
    except Exception: continue
    args=v.get("args") or []
    if "--mcp-serve-webfetch" in args or "--mcp-serve=webfetch" in args:
        print(json.dumps({"id":i,"name":n,"command":v.get("command"),"cwd":v.get("cwd")}, ensure_ascii=False))
'@
    $rows = & $python.Source -c $py $ccDb 2>$null
    foreach ($line in @($rows)) {
        if ($line -like '__ERROR__=*') {
            Write-Host $line
            continue
        }
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $obj = $line | ConvertFrom-Json } catch { continue }
        Write-Host "id=$($obj.id) name=$($obj.name) command=$($obj.command)"
        $sourceSeen.Add('cc-switch')
        if (-not (Is-DetachedPath ([string]$obj.command))) {
            $sourceProblems.Add("cc-switch:$($obj.command)")
        }
    }
} elseif (-not (Test-Path -LiteralPath $ccDb)) {
    Write-Host '(cc-switch.db not found)'
} else {
    Write-Host '(python unavailable; CC Switch DB check skipped)'
}

Write-Host ''
Write-Host '=== OMP-native MCP sources ===' -ForegroundColor Cyan
$ompCandidates = New-Object System.Collections.Generic.List[string]
$ompRoot = Join-Path $homeDir '.omp'
foreach ($rel in @('agent\mcp.json','agent\.mcp.json','mcp.json','.mcp.json')) {
    $ompCandidates.Add((Join-Path $ompRoot $rel))
}
$profiles = Join-Path $ompRoot 'profiles'
if (Test-Path -LiteralPath $profiles) {
    Get-ChildItem -LiteralPath $profiles -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $ompCandidates.Add((Join-Path $_.FullName 'agent\mcp.json'))
        $ompCandidates.Add((Join-Path $_.FullName 'agent\.mcp.json'))
    }
}
foreach ($path in $ompCandidates) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    try { $root = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable } catch { continue }
    if (-not $root.ContainsKey('mcpServers')) { continue }
    foreach ($name in $root.mcpServers.Keys) {
        $server = $root.mcpServers[$name]
        if (-not (Is-WebFetchArgs $server.args)) { continue }
        Write-Host "path=$path name=$name command=$($server.command)"
        $sourceSeen.Add('omp-native')
        if (-not (Is-DetachedPath ([string]$server.command))) {
            $sourceProblems.Add("omp-native:$($server.command)")
        }
    }
}
if (-not ($sourceSeen -contains 'omp-native')) { Write-Host '(no matching OMP-native webfetch entry)' }

Write-Host ''
if ($sourceProblems.Count -gt 0) {
    Write-Host 'R57 EXTERNAL MCP MIGRATION: SOURCE_MIGRATION_REQUIRED' -ForegroundColor Red
    $sourceProblems | ForEach-Object { Write-Host "OLD_SOURCE $_" -ForegroundColor Red }
    Write-Host 'Launch r57 once and review [mcp-r57] logs; if CC Switch rewrites the row again, close/reopen CC Switch after r57 migration.'
    exit 3
}

if ($oldActive.Count -gt 0) {
    Write-Host 'R57 EXTERNAL MCP MIGRATION: HOST_RESTART_REQUIRED' -ForegroundColor Yellow
    Write-Host 'Persistent sources are detached, but at least one already-running host still owns the old install-directory helper.'
    Write-Host 'Restart that host once; do not edit MCP configuration again.'
    exit 2
}

Write-Host 'R57 EXTERNAL MCP MIGRATION: PASS' -ForegroundColor Green
Write-Host 'No checked persistent source points at the installed main EXE, and no active webfetch helper is running from the install directory.'
exit 0
