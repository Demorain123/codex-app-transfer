param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R74Builder = Join-Path $PSScriptRoot 'build-r74-output-ui-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$LauncherPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'src-tauri\resources\codex_no_micro_launcher.mjs'
$TempBuilder = Join-Path $PSScriptRoot '.build-r76-output-ui-local.generated.ps1'

foreach ($Path in @($R74Builder, $R75Builder, $LauncherPath)) {
    if (-not (Test-Path $Path)) { throw "r76 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR74 = [System.IO.File]::ReadAllText($R74Builder)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)
$OriginalLauncher = [System.IO.File]::ReadAllText($LauncherPath)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    # Generated Windows builders may alternate between CRLF and LF. Make EOL
    # style irrelevant while keeping the actual source text contract strict.
    $NormalizedText = $Text.Replace("`r`n", "`n").Replace("`r", "`n")
    $NormalizedOld = $Old.Replace("`r`n", "`n").Replace("`r", "`n")
    $NormalizedNew = $New.Replace("`r`n", "`n").Replace("`r", "`n")
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r76 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld, $NormalizedNew)
}

# r74/r75 could populate Context, cache, native tok/s and cumulative session
# from the visible Codex Usage panel, but exact latest-request in/out only arrived
# when a response stream happened to pass through window.fetch. Current Codex
# Desktop delivers token accounting through app-server and persists authoritative
# token_count events in the local rollout JSONL, so r76 adds a read-only local
# collector in the already-installed Electron main-process hook.
#
# The collector design intentionally follows the proven local-only approach used
# by MIT-licensed KevinKE93/Codex-Monitor: identify the active thread from stable
# renderer attributes, read the matching ~/.codex session JSONL, and use
# last_token_usage for current-request/context values while total_token_usage is
# retained only for cumulative session totals. No session file is modified.
$ExternalUsageIngest = @'
  function ingestExternalUsage(envelope) {
    if (!envelope || typeof envelope !== 'object') return false;
    const info = envelope.info && typeof envelope.info === 'object' ? envelope.info : null;
    if (!info) return false;
    const hit = consumeValue(info, 0);
    if (!hit) return false;
    state.metrics.externalUsageSource = 'local-session-jsonl';
    state.metrics.externalThreadId = typeof envelope.threadId === 'string' ? envelope.threadId : null;
    state.metrics.externalUpdatedAt = Number(envelope.updatedAt) || Date.now();
    try { refreshUi(); } catch {}
    return true;
  }

'@

$MainProcessCollector = @'
  // CAS-R76-EXACT-TOKEN-TELEMETRY
  // Read-only bridge inspired by KevinKE93/Codex-Monitor (MIT): resolve the
  // active Codex thread in the renderer, tail its local rollout JSONL, and
  // forward only token_count.info back to the already-injected telemetry UI.
  // No transcript text, prompts, responses, credentials, or provider traffic
  // are copied into the renderer.
  let localUsageCollectorArmed = false;
  const localUsageFileCache = new Map();
  const localUsageSnapshotCache = new Map();

  const normalizeUsageThreadId = (value) => String(value || '')
    .replace(/^local:/i, '')
    .trim()
    .toLowerCase();

  const activeThreadExpression = "(() => {" +
    "const a=(e,n)=>e&&e.getAttribute?e.getAttribute(n):null;" +
    "const r=document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][aria-current=\"page\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active]:not([data-app-action-sidebar-thread-active=\"false\"])');" +
    "return a(r,'data-app-action-sidebar-thread-id')||" +
      "a(r&&r.querySelector('[data-app-action-sidebar-thread-id]'),'data-app-action-sidebar-thread-id')||" +
      "a(document.querySelector('[data-conversation-id]'),'data-conversation-id')||" +
      "a(document.querySelector('[data-above-composer-conversation-id]'),'data-above-composer-conversation-id')||null;" +
  "})()";

  const codexUsageRoots = () => {
    const path = process.getBuiltinModule('path');
    const os = process.getBuiltinModule('os');
    const raw = String(process.env.CODEX_HOME || '').trim();
    const homes = raw ? raw.split(',').map((value) => value.trim()).filter(Boolean) : [];
    homes.push(path.join(os.homedir(), '.codex'));
    return Array.from(new Set(homes.map((home) => path.resolve(home))));
  };

  const findUsageSessionFile = async (threadId) => {
    const normalized = normalizeUsageThreadId(threadId);
    if (!normalized) return null;
    const cached = localUsageFileCache.get(normalized);
    if (cached) {
      try {
        await process.getBuiltinModule('fs').promises.access(cached);
        return cached;
      } catch {
        localUsageFileCache.delete(normalized);
      }
    }

    const fs = process.getBuiltinModule('fs').promises;
    const path = process.getBuiltinModule('path');
    const walk = async (dir) => {
      let entries;
      try { entries = await fs.readdir(dir, { withFileTypes: true }); }
      catch { return null; }

      // Session filenames contain the thread UUID, so test files before
      // descending. This makes the common current-day lookup very cheap.
      for (const entry of entries) {
        if (!entry.isFile()) continue;
        const name = String(entry.name || '').toLowerCase();
        if (name.endsWith('.jsonl') && name.includes(normalized)) {
          return path.join(dir, entry.name);
        }
      }
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const hit = await walk(path.join(dir, entry.name));
        if (hit) return hit;
      }
      return null;
    };

    for (const home of codexUsageRoots()) {
      for (const leaf of ['sessions', 'archived_sessions']) {
        const hit = await walk(path.join(home, leaf));
        if (hit) {
          localUsageFileCache.set(normalized, hit);
          return hit;
        }
      }
    }
    return null;
  };

  const latestUsageInfo = async (filePath) => {
    const fs = process.getBuiltinModule('fs').promises;
    let handle;
    try {
      handle = await fs.open(filePath, 'r');
      const stat = await handle.stat();
      const previous = localUsageSnapshotCache.get(filePath);
      if (previous && previous.size === stat.size) return previous.envelope;
      if (!stat.size) return previous?.envelope || null;

      // token_count rows are small and normally near EOF. Start with 2 MiB;
      // retry with an 8 MiB tail only when a very large tool/output row sits
      // after the last token_count. Never parse unrelated transcript rows.
      const limits = [2 * 1024 * 1024, 8 * 1024 * 1024];
      for (const limit of limits) {
        const length = Math.min(stat.size, limit);
        const buffer = Buffer.allocUnsafe(length);
        await handle.read(buffer, 0, length, stat.size - length);
        const lines = buffer.toString('utf8').split(/\r?\n/);
        for (let index = lines.length - 1; index >= 0; index -= 1) {
          const line = lines[index];
          if (!line || !line.includes('token_count') || !line.includes('last_token_usage')) continue;
          try {
            const row = JSON.parse(line);
            const payload = row && row.type === 'event_msg' && row.payload && row.payload.type === 'token_count'
              ? row.payload
              : null;
            const info = payload && payload.info && typeof payload.info === 'object' ? payload.info : null;
            if (!info || !info.last_token_usage || !info.total_token_usage) continue;
            const envelope = {
              info,
              updatedAt: Date.parse(row.timestamp || '') || Date.now(),
            };
            localUsageSnapshotCache.set(filePath, { size: stat.size, envelope });
            return envelope;
          } catch {}
        }
        if (length === stat.size) break;
      }
      return previous?.envelope || null;
    } catch {
      return null;
    } finally {
      try { await handle?.close(); } catch {}
    }
  };

  const pushLocalUsage = async (contents, threadId, envelope) => {
    if (!contents || !envelope || contents.isDestroyed?.()) return;
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
    };
    const expression =
      "globalThis.__casOutputTelemetryRuntime&&" +
      "globalThis.__casOutputTelemetryRuntime.ingestExternalUsage&&" +
      "globalThis.__casOutputTelemetryRuntime.ingestExternalUsage(" + JSON.stringify(safeEnvelope) + ")";
    try { await contents.executeJavaScript(expression, true); } catch {}
  };

  const runLocalUsageCollector = async (electron) => {
    let contentsList = [];
    try { contentsList = electron.webContents.getAllWebContents(); } catch { return; }
    for (const contents of contentsList) {
      try {
        if (!contents || contents.isDestroyed?.()) continue;
        const type = contents.getType?.();
        if (type && type !== 'window' && type !== 'webview') continue;
        const url = String(contents.getURL?.() || '');
        if (url && !url.startsWith('app://')) continue;
        const threadId = await contents.executeJavaScript(activeThreadExpression, true);
        if (typeof threadId !== 'string' || !normalizeUsageThreadId(threadId)) continue;
        const sessionFile = await findUsageSessionFile(threadId);
        if (!sessionFile) continue;
        const envelope = await latestUsageInfo(sessionFile);
        if (!envelope) continue;
        await pushLocalUsage(contents, threadId, envelope);
      } catch {}
    }
  };

  const armLocalUsageCollector = (electron) => {
    if (localUsageCollectorArmed || !electron?.webContents) return;
    localUsageCollectorArmed = true;
    const tick = () => { void runLocalUsageCollector(electron); };
    const start = () => {
      tick();
      const timer = setInterval(tick, 2500);
      try { timer.unref?.(); } catch {}
    };
    try {
      if (electron.app?.isReady?.()) start();
      else electron.app?.whenReady?.().then(start).catch(() => {});
    } catch {}
  };

'@

try {
    # 1) Temporarily teach the r74 telemetry template how to accept the exact,
    # read-only local token_count payload. r75/r76's timestamp finalizer then
    # layers on top of this same runtime instead of forking another renderer.
    $PatchedR74 = Replace-Required $OriginalR74 `
        '  state.refresh = refreshUi;' `
        ($ExternalUsageIngest + '  state.refresh = refreshUi;') `
        'external local token_count ingestion hook'
    Write-Utf8NoBom $R74Builder $PatchedR74

    # 2) Temporarily extend the proven Electron main-process startup hook. The
    # code lives inside Codex itself after injection, so the small launcher may
    # exit exactly as before; no background PowerShell/Python process is needed.
    $PatchedLauncher = Replace-Required $OriginalLauncher `
        '  const armOutputTelemetry = (electron) => {' `
        ($MainProcessCollector + '  const armOutputTelemetry = (electron) => {') `
        'main-process read-only JSONL collector'

    $OldAttach = @'
    try {
      if (electron.app.isReady?.()) attachExisting();
      else electron.app.whenReady?.().then(attachExisting).catch(() => {});
    } catch {}
  };
'@
    $NewAttach = @'
    try {
      if (electron.app.isReady?.()) attachExisting();
      else electron.app.whenReady?.().then(attachExisting).catch(() => {});
    } catch {}
    try { armLocalUsageCollector(electron); } catch {}
  };
'@
    $PatchedLauncher = Replace-Required $PatchedLauncher $OldAttach $NewAttach 'arm local usage collector with telemetry'
    Write-Utf8NoBom $LauncherPath $PatchedLauncher

    # 3) Reuse the reviewed r75 finalizer, but generate r76 identity directly
    # from r74 so the visible package/version and builder PASS markers stay in
    # one chain. No r75 install is required on the user's machine.
    $R76BuilderText = $OriginalR75.Replace('r75', 'r76').Replace('R75', 'R76').Replace('+75', '+76')
    foreach ($Marker in @(
        "const VERSION = 'r76.0';",
        'R76_TIMESTAMP_V3_PASS'
    )) {
        if (-not $R76BuilderText.Contains($Marker)) { throw "r76 generated builder verification failed: $Marker" }
    }
    Write-Utf8NoBom $TempBuilder $R76BuilderText

    # Source-level guards before invoking the expensive package build.
    foreach ($Marker in @(
        'CAS-R76-EXACT-TOKEN-TELEMETRY',
        'activeThreadExpression',
        'last_token_usage',
        'total_token_usage',
        'armLocalUsageCollector(electron)',
        'ingestExternalUsage'
    )) {
        $Combined = [System.IO.File]::ReadAllText($LauncherPath) + [System.IO.File]::ReadAllText($R74Builder)
        if (-not $Combined.Contains($Marker)) { throw "r76 telemetry source verification failed: $Marker" }
    }

    node --check $LauncherPath
    if ($LASTEXITCODE -ne 0) { throw 'r76 temporary launcher JavaScript syntax check failed' }

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r76 generated builder failed with exit code $LASTEXITCODE" }

    Write-Host 'R76_EXACT_TOKEN_TELEMETRY_PASS' -ForegroundColor Green
    Write-Host '  - in/out: exact latest-request last_token_usage from active session JSONL'
    Write-Host '  - ctx/cache: last_token_usage + model_context_window, with native UI fallback'
    Write-Host '  - session: cumulative total_token_usage (intentionally may reach tens/hundreds of millions)'
    Write-Host '  - collector: local read-only; no app.asar/session/auth/provider writes'
}
finally {
    Write-Utf8NoBom $R74Builder $OriginalR74
    Write-Utf8NoBom $LauncherPath $OriginalLauncher
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
    Write-Host '[r76] restored temporary source patches; worktree remains pull-friendly'
}
