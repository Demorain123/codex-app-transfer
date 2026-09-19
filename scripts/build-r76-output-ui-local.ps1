param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R74Builder = Join-Path $PSScriptRoot 'build-r74-output-ui-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$LauncherPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'src-tauri\resources\codex_no_micro_launcher.mjs'
$TempBuilder = Join-Path $PSScriptRoot '.build-r76-output-ui-local.generated.ps1'
$PreflightLauncher = Join-Path $PSScriptRoot '.r76-launcher-preflight.generated.mjs'

foreach ($Path in @($R74Builder, $R75Builder, $LauncherPath)) {
    if (-not (Test-Path $Path)) { throw "r76 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR74 = [System.IO.File]::ReadAllText($R74Builder)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)
$OriginalLauncher = [System.IO.File]::ReadAllText($LauncherPath)
$TouchedSources = $false

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
  const localUsageMissCache = new Map();
  const localUsageSnapshotCache = new Map();
  const R94_USAGE_LOOKUP_MISS_TTL_MS = 10000;

  const normalizeUsageThreadId = (value) => String(value || '')
    .replace(/^local:/i, '')
    .trim()
    .toLowerCase();

  // CAS-R94-ACTIVE-THREAD-FALLBACK
  // CAS-R94-MULTI-PANE-THREAD-COLLECTOR
  // Current Codex split view can expose a parent thread and one or more child
  // sub-agent threads at the same time. Collect every visible pane thread id;
  // only fall back to route/sidebar identity when no pane bar is available.
  const activeThreadExpression = "(() => {" +
    "const a=(e,n)=>e&&e.getAttribute?e.getAttribute(n):null;" +
    "const out=[];const seen=new Set();" +
    "for(const b of document.querySelectorAll('[data-cas-pane-statusbar=\"true\"][data-cas-pane-thread-id]')){" +
      "const v=String(a(b,'data-cas-pane-thread-id')||'').replace(/^local:/i,'').trim().toLowerCase();" +
      "if(v&&!seen.has(v)){seen.add(v);out.push(v);}" +
    "}" +
    "if(out.length)return out;" +
    "const p=String(location&&location.pathname||'');" +
    "const m=p.match(/\\/(?:local|thread|conversation)\\/([^/?#]+)/)||p.match(/\\/hotkey-window\\/thread\\/([^/?#]+)/);" +
    "if(m&&m[1]){let v=m[1];try{v=decodeURIComponent(v);}catch{};v=String(v).replace(/^local:/i,'').trim().toLowerCase();if(v)return [v];}" +
    "const r=document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][aria-current=\"page\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active]:not([data-app-action-sidebar-thread-active=\"false\"])');" +
    "const v=a(r,'data-app-action-sidebar-thread-id')||" +
      "a(r&&r.querySelector('[data-app-action-sidebar-thread-id]'),'data-app-action-sidebar-thread-id')||" +
      "a(document.querySelector('[data-conversation-id]'),'data-conversation-id')||" +
      "a(document.querySelector('[data-above-composer-conversation-id]'),'data-above-composer-conversation-id')||'';" +
    "return v?[String(v).replace(/^local:/i,'').trim().toLowerCase()]:[];" +
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

    const missedAt = Number(localUsageMissCache.get(normalized));
    if (Number.isFinite(missedAt) && Date.now() - missedAt < R94_USAGE_LOOKUP_MISS_TTL_MS) return null;

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
          localUsageMissCache.delete(normalized);
          localUsageFileCache.set(normalized, hit);
          return hit;
        }
      }
    }
    localUsageMissCache.set(normalized, Date.now());
    return null;
  };

  // CAS-R94-TURN-AWARE-ROLLOUT-BRIDGE
  // Keep r76's bounded read-only tailing, but preserve the exact turn identity
  // already written by Codex. This normalizes rollout task_started /
  // turn_context / token_count / task_complete into one recent-turn envelope;
  // it never edits the rollout and never treats cumulative totals as context.
  const latestUsageInfo = async (filePath) => {
    const fs = process.getBuiltinModule('fs').promises;
    let handle;
    try {
      handle = await fs.open(filePath, 'r');
      const stat = await handle.stat();
      const previous = localUsageSnapshotCache.get(filePath);
      if (previous && previous.size === stat.size) return previous.envelope;
      if (!stat.size) return previous?.envelope || null;

      const normalizeTurnId = (value) => String(value || '').trim().toLowerCase();
      const rowEpoch = (row, fallback) => {
        const parsed = Date.parse(String(row?.timestamp || ''));
        return Number.isFinite(parsed) ? parsed : fallback;
      };
      const limits = [2 * 1024 * 1024, 8 * 1024 * 1024];

      for (const limit of limits) {
        const length = Math.min(stat.size, limit);
        const buffer = Buffer.allocUnsafe(length);
        await handle.read(buffer, 0, length, stat.size - length);
        const lines = buffer.toString('utf8').split(/\r?\n/);

        let activeTurnId = '';
        const turnMeta = new Map();
        const itemMeta = new Map();
        let latestUsage = null;
        let latestTerminal = null;
        let latestItemEventAt = 0;

        const ensureTurn = (turnId) => {
          const id = normalizeTurnId(turnId);
          if (!id) return null;
          let meta = turnMeta.get(id);
          if (!meta) {
            meta = { turnId: id, startedAt: null, completedAt: null, durationMs: null, status: null, model: null };
            turnMeta.set(id, meta);
          }
          return meta;
        };

        for (let index = 0; index < lines.length; index += 1) {
          const line = lines[index];
          if (!line || !/(token_count|task_started|task_complete|turn_started|turn_complete|turn_context|item_started|item_completed)/.test(line)) continue;

          let row;
          try { row = JSON.parse(line); } catch { continue; }
          const payload = row && row.type === 'event_msg' && row.payload && typeof row.payload === 'object'
            ? row.payload
            : row;
          const type = String(payload?.type || row?.type || '').toLowerCase();

          if (type === 'item_started' || type === 'item_completed') {
            const turnId = normalizeTurnId(payload?.turn_id || payload?.turnId || row?.turn_id || row?.turnId);
            const item = payload?.item && typeof payload.item === 'object' ? payload.item : null;
            const itemId = String(item?.id || payload?.item_id || payload?.itemId || '').trim();
            const itemType = String(item?.type || '').trim();
            if (turnId && itemId) {
              const key = turnId + '\u0000' + itemId;
              let meta = itemMeta.get(key);
              if (!meta) {
                meta = {
                  turnId,
                  itemId,
                  itemType: itemType || null,
                  startedAtMs: null,
                  completedAtMs: null,
                };
              }
              const startedAtMs = Number(payload?.started_at_ms ?? payload?.startedAtMs);
              const completedAtMs = Number(payload?.completed_at_ms ?? payload?.completedAtMs);
              if (Number.isFinite(startedAtMs) && startedAtMs > 0) meta.startedAtMs = startedAtMs;
              if (Number.isFinite(completedAtMs) && completedAtMs > 0) meta.completedAtMs = completedAtMs;
              if (itemType) meta.itemType = itemType;
              itemMeta.delete(key);
              itemMeta.set(key, meta);
              latestItemEventAt = rowEpoch(row, Date.now());
            }
            continue;
          }

          if (type === 'task_started' || type === 'turn_started') {
            const id = normalizeTurnId(payload?.turn_id || payload?.turnId || row?.turn_id || row?.turnId);
            if (id) {
              activeTurnId = id;
              const meta = ensureTurn(id);
              const started = Date.parse(String(payload?.started_at || payload?.startedAt || row?.timestamp || ''));
              if (meta && Number.isFinite(started)) meta.startedAt = started;
              if (meta) meta.status = String(payload?.status || 'inProgress');
            }
            continue;
          }

          if (type === 'turn_context') {
            const id = normalizeTurnId(payload?.turn_id || payload?.turnId || row?.turn_id || row?.turnId);
            const model = typeof payload?.model === 'string' ? payload.model.trim() : '';
            if (id) {
              activeTurnId = id;
              const meta = ensureTurn(id);
              if (meta && model) meta.model = model;
            }
            continue;
          }

          if (type === 'token_count') {
            const info = payload?.info && typeof payload.info === 'object' ? payload.info : null;
            if (!info || !info.last_token_usage || !info.total_token_usage) continue;
            const activeMeta = activeTurnId ? turnMeta.get(activeTurnId) : null;
            latestUsage = {
              info,
              updatedAt: rowEpoch(row, Date.now()),
              turnId: activeTurnId || null,
              model: activeMeta && typeof activeMeta.model === 'string' && activeMeta.model ? activeMeta.model : null,
              lineIndex: index,
            };
            continue;
          }

          if (type === 'task_complete' || type === 'turn_complete') {
            const id = normalizeTurnId(
              payload?.turn_id || payload?.turnId || row?.turn_id || row?.turnId || activeTurnId
            );
            if (!id) continue;
            const meta = ensureTurn(id);
            const completed = Date.parse(String(payload?.completed_at || payload?.completedAt || row?.timestamp || ''));
            if (meta) {
              if (Number.isFinite(completed)) meta.completedAt = completed;
              const duration = Number(payload?.duration_ms ?? payload?.durationMs);
              if (Number.isFinite(duration)) meta.durationMs = duration;
              meta.status = String(payload?.status || (payload?.error ? 'failed' : 'completed'));
            }
            latestTerminal = meta;
            // When the bounded tail begins after task_started, a token_count may
            // precede the matching task_complete without an active turn id. The
            // immediately following terminal event is the only safe recovery.
            if (latestUsage && !latestUsage.turnId && latestUsage.lineIndex < index) {
              latestUsage.turnId = id;
            }
            if (activeTurnId === id) activeTurnId = '';
          }
        }

        if (!latestUsage) {
          const recentItems = Array.from(itemMeta.values()).slice(-96);
          const previousEnvelope = previous && previous.envelope && typeof previous.envelope === 'object'
            ? previous.envelope
            : null;
          if (recentItems.length || activeTurnId || latestTerminal) {
            const activeTurn = activeTurnId ? (turnMeta.get(activeTurnId) || { turnId: activeTurnId }) : null;
            const envelope = {
              info: previousEnvelope?.info || null,
              updatedAt: latestItemEventAt || Date.now(),
              model: previousEnvelope?.model || null,
              turnId: previousEnvelope?.turnId || null,
              turnStartedAt: previousEnvelope?.turnStartedAt ?? null,
              turnCompletedAt: previousEnvelope?.turnCompletedAt ?? null,
              turnDurationMs: previousEnvelope?.turnDurationMs ?? null,
              turnStatus: previousEnvelope?.turnStatus ?? null,
              activeTurn: activeTurn ? {
                turnId: normalizeTurnId(activeTurn.turnId),
                startedAt: activeTurn.startedAt ?? null,
                status: activeTurn.status || 'inProgress',
              } : null,
              terminalTurn: latestTerminal ? {
                turnId: normalizeTurnId(latestTerminal.turnId),
                startedAt: latestTerminal.startedAt ?? null,
                completedAt: latestTerminal.completedAt ?? null,
                durationMs: latestTerminal.durationMs ?? null,
                status: latestTerminal.status || 'completed',
              } : null,
              recentItems,
            };
            localUsageSnapshotCache.set(filePath, { size: stat.size, envelope });
            return envelope;
          }
          if (length === stat.size) break;
          continue;
        }

        const usageTurnId = normalizeTurnId(latestUsage.turnId);
        // If the 2 MiB window began after turn_context/task_started, expand to
        // the bounded 8 MiB window before giving up on exact turn identity.
        if (!usageTurnId && length < stat.size) continue;
        const usageTurn = usageTurnId ? (turnMeta.get(usageTurnId) || null) : null;
        const activeTurn = activeTurnId ? (turnMeta.get(activeTurnId) || { turnId: activeTurnId }) : null;
        const envelope = {
          info: latestUsage.info,
          updatedAt: latestUsage.updatedAt,
          model: latestUsage.model || (usageTurn && usageTurn.model) || null,
          turnId: usageTurnId || null,
          turnStartedAt: usageTurn?.startedAt ?? null,
          turnCompletedAt: usageTurn?.completedAt ?? null,
          turnDurationMs: usageTurn?.durationMs ?? null,
          turnStatus: usageTurn?.status ?? null,
          activeTurn: activeTurn ? {
            turnId: normalizeTurnId(activeTurn.turnId),
            startedAt: activeTurn.startedAt ?? null,
            status: activeTurn.status || 'inProgress',
          } : null,
          terminalTurn: latestTerminal ? {
            turnId: normalizeTurnId(latestTerminal.turnId),
            startedAt: latestTerminal.startedAt ?? null,
            completedAt: latestTerminal.completedAt ?? null,
            durationMs: latestTerminal.durationMs ?? null,
            status: latestTerminal.status || 'completed',
          } : null,
          recentItems: Array.from(itemMeta.values()).slice(-96),
        };
        localUsageSnapshotCache.set(filePath, { size: stat.size, envelope });
        return envelope;
      }

      const fallbackEnvelope = previous?.envelope || null;
      localUsageSnapshotCache.set(filePath, { size: stat.size, envelope: fallbackEnvelope });
      return fallbackEnvelope;
    } catch {
      return null;
    } finally {
      try { await handle?.close(); } catch {}
    }
  };

  const pushLocalUsage = async (contents, threadId, envelope) => {
    if (!contents || !envelope || contents.isDestroyed?.()) return;
    // Keep the historical r83 exact-replacement anchor intact. r83 inserts
    // the safe model field into this object during the nested carry-forward.
    // r94 turn metadata is appended afterwards so both generations compose.
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
    };
    safeEnvelope.turnId = envelope.turnId || null;
    safeEnvelope.turnStartedAt = envelope.turnStartedAt ?? null;
    safeEnvelope.turnCompletedAt = envelope.turnCompletedAt ?? null;
    safeEnvelope.turnDurationMs = envelope.turnDurationMs ?? null;
    safeEnvelope.turnStatus = envelope.turnStatus || null;
    safeEnvelope.activeTurn = envelope.activeTurn || null;
    safeEnvelope.terminalTurn = envelope.terminalTurn || null;
    safeEnvelope.recentItems = Array.isArray(envelope.recentItems)
      ? envelope.recentItems.slice(-96).map((item) => ({
          turnId: String(item?.turnId || ''),
          itemId: String(item?.itemId || ''),
          itemType: String(item?.itemType || ''),
          startedAtMs: Number(item?.startedAtMs) || null,
          completedAtMs: Number(item?.completedAtMs) || null,
        })).filter((item) => item.turnId && item.itemId)
      : [];
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
        const threadValue = await contents.executeJavaScript(activeThreadExpression, true);
        const threadIds = Array.from(new Set(
          (Array.isArray(threadValue) ? threadValue : [threadValue])
            .map(normalizeUsageThreadId)
            .filter(Boolean)
        ));
        if (!threadIds.length) continue;
        for (const threadId of threadIds) {
          const sessionFile = await findUsageSessionFile(threadId);
          if (!sessionFile) continue;
          const envelope = await latestUsageInfo(sessionFile);
          if (!envelope) continue;
          await pushLocalUsage(contents, threadId, envelope);
        }
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
    # 1) Build the exact read-only telemetry patches entirely in memory first.
    # Preflight mode exits before touching tracked r74/launcher sources.
    $PatchedR74 = Replace-Required $OriginalR74 `
        '  state.refresh = refreshUi;' `
        ($ExternalUsageIngest + '  state.refresh = refreshUi;') `
        'external local token_count ingestion hook'

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

    # 2) Reuse the reviewed r75 finalizer, but generate r76 identity directly
    # from r74 so the visible package/version and builder PASS markers stay in
    # one chain. No r75 install is required on the user's machine.
    $R76BuilderText = $OriginalR75.Replace('r75', 'r76').Replace('R75', 'R76').Replace('+75', '+76')
    foreach ($Marker in @(
        "const VERSION = 'r76.0';",
        'R76_TIMESTAMP_V3_PASS'
    )) {
        if (-not $R76BuilderText.Contains($Marker)) { throw "r76 generated builder verification failed: $Marker" }
    }

    $Combined = $PatchedLauncher + $PatchedR74
    foreach ($Marker in @(
        'CAS-R76-EXACT-TOKEN-TELEMETRY',
        'CAS-R94-TURN-AWARE-ROLLOUT-BRIDGE',
        'terminalTurn',
        'activeTurn',
        'activeThreadExpression',
        'last_token_usage',
        'total_token_usage',
        'armLocalUsageCollector(electron)',
        'ingestExternalUsage'
    )) {
        if (-not $Combined.Contains($Marker)) { throw "r76 telemetry source verification failed: $Marker" }
    }

    if ($PreflightOnly) {
        Write-Utf8NoBom $PreflightLauncher $PatchedLauncher
        node --check $PreflightLauncher
        if ($LASTEXITCODE -ne 0) { throw 'r76 patched launcher preflight JavaScript syntax check failed' }
        Write-Host 'R76_OUTPUT_JS_PREFLIGHT_PASS' -ForegroundColor Green
        Write-Host 'R76_OUTPUT_TEXT_TRANSFORM_PREFLIGHT_PASS' -ForegroundColor Green
        return
    }

    Write-Utf8NoBom $R74Builder $PatchedR74
    Write-Utf8NoBom $LauncherPath $PatchedLauncher
    Write-Utf8NoBom $TempBuilder $R76BuilderText
    $TouchedSources = $true

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
    if ($TouchedSources) {
        Write-Utf8NoBom $R74Builder $OriginalR74
        Write-Utf8NoBom $LauncherPath $OriginalLauncher
    }
    Remove-Item -LiteralPath $TempBuilder -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PreflightLauncher -Force -ErrorAction SilentlyContinue
    Write-Host '[r76] restored temporary source patches; worktree remains pull-friendly'
}
