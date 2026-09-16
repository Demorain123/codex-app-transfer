  // CAS-R87-MULTI-PANE-EXACT-TOKEN-TELEMETRY
  // Read-only bridge: resolve every visible conversation/composer thread,
  // read the matching local rollout JSONL, and forward only usage + identity
  // metadata required by the renderer. No transcript/prompt/response text is
  // copied into the renderer and no rollout file is modified.
  let localUsageCollectorArmed = false;
  const localUsageFileCache = new Map();
  const localUsageSnapshotCache = new Map();
  const localUsageIdentityCache = new Map();

  const normalizeUsageThreadId = (value) => String(value || '')
    .replace(/^local:/i, '')
    .trim()
    .toLowerCase();

  const visibleThreadExpression = "(() => {" +
    "const ids=new Set();" +
    "const norm=v=>String(v||'').replace(/^local:/i,'').trim().toLowerCase();" +
    "const vis=e=>{if(!e||!e.getClientRects)return false;try{const s=getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)!==0&&e.getClientRects().length>0}catch{return true}};" +
    "const add=v=>{v=norm(v);if(v)ids.add(v)};" +
    "document.querySelectorAll('[data-above-composer-conversation-id]').forEach(e=>{if(vis(e)||vis(e.parentElement))add(e.getAttribute('data-above-composer-conversation-id'))});" +
    "const edit='[data-codex-composer-root],[data-thread-find-composer=\"true\"],[data-codex-composer=\"true\"],.composer-surface-chrome,form,.ProseMirror[contenteditable=\"true\"],[role=\"textbox\"][contenteditable=\"true\"],textarea';" +
    "document.querySelectorAll(edit).forEach(c=>{if(!vis(c))return;let n=c;for(let d=0;n&&n!==document.body&&d<8;d++,n=n.parentElement){add(n.getAttribute&&n.getAttribute('data-above-composer-conversation-id'));add(n.getAttribute&&n.getAttribute('data-conversation-id'));add(n.getAttribute&&n.getAttribute('data-thread-id'));const marks=n.querySelectorAll?n.querySelectorAll('[data-above-composer-conversation-id],[data-conversation-id],[data-thread-id]'):[];if(marks.length===1){const m=marks[0];add(m.getAttribute('data-above-composer-conversation-id')||m.getAttribute('data-conversation-id')||m.getAttribute('data-thread-id'))}}});" +
    "if(!ids.size){const r=document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active=\"true\"]')||document.querySelector('[data-app-action-sidebar-thread-row][aria-current=\"page\"]')||document.querySelector('[data-app-action-sidebar-thread-active=\"true\"]')||document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active]:not([data-app-action-sidebar-thread-active=\"false\"])');if(r)add(r.getAttribute('data-app-action-sidebar-thread-id')||(r.querySelector('[data-app-action-sidebar-thread-id]')||{}).getAttribute?.('data-app-action-sidebar-thread-id'))}" +
    "return Array.from(ids);" +
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
      for (const entry of entries) {
        if (!entry.isFile()) continue;
        const name = String(entry.name || '').toLowerCase();
        if (name.endsWith('.jsonl') && name.includes(normalized)) return path.join(dir, entry.name);
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

  const nestedString = (obj, keys, depth = 0) => {
    if (!obj || typeof obj !== 'object' || depth > 6) return null;
    for (const key of Object.keys(obj)) {
      if (keys.includes(key) && typeof obj[key] === 'string' && obj[key].trim()) return obj[key].trim();
    }
    for (const value of Object.values(obj)) {
      if (!value || typeof value !== 'object') continue;
      const hit = nestedString(value, keys, depth + 1);
      if (hit) return hit;
    }
    return null;
  };

  const readUsageIdentity = async (filePath, fallbackThreadId) => {
    const cached = localUsageIdentityCache.get(filePath);
    if (cached) return cached;
    const fs = process.getBuiltinModule('fs').promises;
    let handle;
    try {
      handle = await fs.open(filePath, 'r');
      const stat = await handle.stat();
      const length = Math.min(stat.size, 512 * 1024);
      if (!length) return null;
      const buffer = Buffer.allocUnsafe(length);
      await handle.read(buffer, 0, length, 0);
      const lines = buffer.toString('utf8').split(/\r?\n/).slice(0, 256);
      for (const line of lines) {
        if (!line || !line.includes('session_meta')) continue;
        try {
          const row = JSON.parse(line);
          if (!row || row.type !== 'session_meta') continue;
          const payload = row.payload && typeof row.payload === 'object' ? row.payload : row;
          const threadId = normalizeUsageThreadId(
            payload.id || payload.thread_id || payload.threadId || fallbackThreadId
          );
          const sessionId = normalizeUsageThreadId(
            payload.session_id || payload.sessionId || (!payload.parent_thread_id && !payload.parentThreadId ? threadId : '')
          );
          const parentThreadId = normalizeUsageThreadId(
            payload.parent_thread_id || payload.parentThreadId || nestedString(payload.source, ['parent_thread_id','parentThreadId']) || ''
          );
          const identity = { threadId, sessionId: sessionId || null, parentThreadId: parentThreadId || null };
          localUsageIdentityCache.set(filePath, identity);
          return identity;
        } catch {}
      }
      const fallback = { threadId: normalizeUsageThreadId(fallbackThreadId), sessionId: null, parentThreadId: null };
      localUsageIdentityCache.set(filePath, fallback);
      return fallback;
    } catch {
      return null;
    } finally {
      try { await handle?.close(); } catch {}
    }
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

      const limits = [2 * 1024 * 1024, 8 * 1024 * 1024];
      for (const limit of limits) {
        const length = Math.min(stat.size, limit);
        const buffer = Buffer.allocUnsafe(length);
        await handle.read(buffer, 0, length, stat.size - length);
        const lines = buffer.toString('utf8').split(/\r?\n/);
        let usage = null;
        let model = null;
        for (let index = lines.length - 1; index >= 0; index -= 1) {
          const line = lines[index];
          if (!line) continue;
          const wantsUsage = !usage && line.includes('token_count') && line.includes('last_token_usage');
          const wantsModel = !model && line.includes('turn_context') && /\"model\"/.test(line);
          if (!wantsUsage && !wantsModel) continue;
          try {
            const row = JSON.parse(line);
            if (wantsModel && row && row.type === 'turn_context') {
              const candidate = row.payload && typeof row.payload.model === 'string' ? row.payload.model : null;
              if (candidate) model = candidate;
            }
            if (wantsUsage) {
              const payload = row && row.type === 'event_msg' && row.payload && row.payload.type === 'token_count'
                ? row.payload
                : null;
              const info = payload && payload.info && typeof payload.info === 'object' ? payload.info : null;
              if (info && info.last_token_usage && info.total_token_usage) {
                usage = { info, updatedAt: Date.parse(row.timestamp || '') || Date.now() };
              }
            }
          } catch {}
          if (usage && model) break;
        }
        if (usage) {
          const envelope = { ...usage, model };
          localUsageSnapshotCache.set(filePath, { size: stat.size, envelope });
          return envelope;
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

  const pushLocalUsage = async (contents, threadId, envelope, identity) => {
    if (!contents || !envelope || contents.isDestroyed?.()) return;
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      sessionId: identity && typeof identity.sessionId === 'string' ? identity.sessionId : null,
      parentThreadId: identity && typeof identity.parentThreadId === 'string' ? identity.parentThreadId : null,
      updatedAt: envelope.updatedAt,
      model: typeof envelope.model === 'string' ? envelope.model : null,
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
        if (url && /^(devtools:|chrome-extension:|chrome:)/i.test(url)) continue;
        const resolved = await contents.executeJavaScript(visibleThreadExpression, true);
        const threadIds = Array.isArray(resolved) ? resolved.map(normalizeUsageThreadId).filter(Boolean) : [];
        for (const threadId of Array.from(new Set(threadIds)).slice(0, 8)) {
          const sessionFile = await findUsageSessionFile(threadId);
          if (!sessionFile) continue;
          const [envelope, identity] = await Promise.all([
            latestUsageInfo(sessionFile),
            readUsageIdentity(sessionFile, threadId),
          ]);
          if (!envelope) continue;
          await pushLocalUsage(contents, threadId, envelope, identity);
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

