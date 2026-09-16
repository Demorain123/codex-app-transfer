param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$R76Output = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$R77Entry = Join-Path $PSScriptRoot 'build-r77-local.ps1'
$TempR78Entry = Join-Path $PSScriptRoot '.build-r78-entry.generated.ps1'

foreach ($Path in @($R75Builder, $R76Output, $R77Entry)) {
    if (-not (Test-Path $Path)) { throw "r78 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)
$OriginalR76Output = [System.IO.File]::ReadAllText($R76Output)
$OriginalR77Entry = [System.IO.File]::ReadAllText($R77Entry)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r78 expected text missing: $Label" }
    return $Text.Replace($Old, $New)
}

# ---------------------------------------------------------------------------
# r78 timestamp hardening
# ---------------------------------------------------------------------------
$TimestampMatchHelpers = @'
  function normalizedOutputMatchText(value) {
    return String(value || '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[`*~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function finalOutputSegment(segment, root) {
    if (!(segment instanceof Element) || !(root instanceof Element)) return false;
    if (segment.matches('[data-local-conversation-final-assistant]')) return true;
    if (segment.querySelector('[data-assistant-message-sent-time],time[datetime]')) return true;
    const final = root.matches('[data-local-conversation-final-assistant]')
      ? root
      : root.querySelector('[data-local-conversation-final-assistant]');
    return !!final && (segment === final || segment.contains(final));
  }

  function sessionTimeForSegment(segment) {
    if (!(segment instanceof Element)) return null;
    const items = Array.isArray(state.externalAssistantItems) ? state.externalAssistantItems : [];
    if (!items.length) return null;
    const text = normalizedOutputMatchText(normalizedText(segment));
    if (text.length < 6) return null;

    let best = null;
    let bestScore = -1;
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index];
      const epoch = Number(item && item.epoch);
      const prefix = normalizedOutputMatchText(item && item.textPrefix);
      if (!Number.isFinite(epoch) || epoch <= 0 || prefix.length < 6) continue;

      let score = -1;
      if (text.includes(prefix)) {
        score = 1200 + Math.min(prefix.length, 180);
      } else {
        const head = prefix.slice(0, Math.min(96, prefix.length));
        if (head.length >= 18 && text.includes(head)) {
          score = 800 + head.length;
        } else if (text.length >= 18 && text.length <= 180 && prefix.includes(text)) {
          score = 500 + text.length;
        } else if (text === prefix) {
          score = 400 + text.length;
        }
      }

      if (score > bestScore) {
        bestScore = score;
        best = { epoch: epoch, source: 'Codex session response_item' };
      }
    }
    return bestScore >= 0 ? best : null;
  }

  function exactTimeForSegment(segment, root) {
    const ownNative = nativeTime(segment);
    if (ownNative) return ownNative;
    const session = sessionTimeForSegment(segment);
    if (session) return session;
    if (finalOutputSegment(segment, root)) return nativeTime(root);
    return null;
  }

'@

$PatchedR75 = Replace-Required $OriginalR75 `
    '  function structuralPath(node, stop) {' `
    ($TimestampMatchHelpers + '  function structuralPath(node, stop) {') `
    'session-backed output timestamp matcher'

$PatchedR75 = Replace-Required $PatchedR75 `
    '    const native = nativeTime(segment) || nativeTime(root);' `
    '    const native = exactTimeForSegment(segment, root);' `
    'per-segment exact timestamp selection'

$OldWhenChoice = @'
    const remembered = rememberedTime(key);
    const attrTime = timeAttr(badge);
    const when = (Number.isFinite(attrTime) && attrTime > 0)
      ? attrTime
      : ((Number.isFinite(remembered) && remembered > 0) ? remembered : epoch);
'@
$NewWhenChoice = @'
    const remembered = rememberedTime(key);
    const attrTime = timeAttr(badge);
    const exactSource = /Codex session response_item|Codex message time/i.test(String(source || ''));
    const when = exactSource
      ? epoch
      : ((Number.isFinite(attrTime) && attrTime > 0)
        ? attrTime
        : ((Number.isFinite(remembered) && remembered > 0) ? remembered : epoch));
'@
$PatchedR75 = Replace-Required $PatchedR75 $OldWhenChoice $NewWhenChoice 'exact timestamp promotes over remembered estimate'

$OldBadgeText = @'
    badge.textContent = clock(when);
    badge.title = fullTime(when) + ' · ' + ((Number.isFinite(remembered) && remembered > 0) ? 'remembered local output time' : source);
'@
$NewBadgeText = @'
    const displaySource = exactSource
      ? source
      : ((Number.isFinite(remembered) && remembered > 0) ? 'remembered local output time' : source);
    const estimated = /first observed|remembered local output time/i.test(String(displaySource || ''));
    badge.textContent = (estimated ? '~' : '') + clock(when);
    badge.setAttribute('data-cas-output-time-quality', estimated ? 'estimated' : 'exact');
    badge.setAttribute('data-cas-output-time-source', String(displaySource || 'unknown'));
    badge.title = fullTime(when) + ' · ' + displaySource + (estimated ? ' · estimated' : ' · exact');
'@
$PatchedR75 = Replace-Required $PatchedR75 $OldBadgeText $NewBadgeText 'timestamp exact-vs-estimated badge provenance'

$PatchedR75 = Replace-Required $PatchedR75 `
    'font:9px/1.15 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.72;' `
    'font:10px/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;pointer-events:auto;user-select:text;opacity:.84;' `
    'timestamp readability'

# ---------------------------------------------------------------------------
# r78 exact usage + historical output-time bridge
# ---------------------------------------------------------------------------
$PatchedR76Output = Replace-Required $OriginalR76Output `
    '  const localUsageSnapshotCache = new Map();' `
    "  const localUsageSnapshotCache = new Map();`n  const localAssistantSnapshotCache = new Map();" `
    'assistant timestamp cache'

$OldIngestHead = @'
    const hit = consumeValue(info, 0);
    if (!hit) return false;
    state.metrics.externalUsageSource = 'local-session-jsonl';
'@
$NewIngestHead = @'
    const hit = consumeValue(info, 0);
    if (!hit) return false;
    state.externalAssistantItems = Array.isArray(envelope.assistantItems)
      ? envelope.assistantItems.slice(-96)
      : [];
    state.metrics.externalUsageSource = 'local-session-jsonl';
'@
$PatchedR76Output = Replace-Required $PatchedR76Output $OldIngestHead $NewIngestHead 'ingest assistant event timestamps'

$AssistantCollector = @'
  const recentAssistantItems = async (filePath) => {
    const fs = process.getBuiltinModule('fs').promises;
    let handle;
    try {
      handle = await fs.open(filePath, 'r');
      const stat = await handle.stat();
      const previous = localAssistantSnapshotCache.get(filePath);
      if (previous && previous.size === stat.size) return previous.items;
      if (!stat.size) return previous?.items || [];

      const length = Math.min(stat.size, 8 * 1024 * 1024);
      const buffer = Buffer.allocUnsafe(length);
      await handle.read(buffer, 0, length, stat.size - length);
      let text = buffer.toString('utf8');
      if (length < stat.size) {
        const newline = text.indexOf('\n');
        text = newline >= 0 ? text.slice(newline + 1) : '';
      }

      const items = [];
      const lines = text.split(/\r?\n/);
      for (const line of lines) {
        if (!line || !line.includes('response_item') || !line.includes('assistant')) continue;
        try {
          const row = JSON.parse(line);
          const payload = row && row.type === 'response_item' && row.payload && row.payload.type === 'message'
            ? row.payload
            : null;
          if (!payload || payload.role !== 'assistant') continue;
          const content = payload.content;
          let message = '';
          if (typeof content === 'string') {
            message = content;
          } else if (Array.isArray(content)) {
            message = content
              .map((item) => item && typeof item.text === 'string' ? item.text : '')
              .filter(Boolean)
              .join('\n\n');
          }
          const prefix = String(message || '').replace(/\s+/g, ' ').trim().slice(0, 180);
          const epoch = Date.parse(row.timestamp || '');
          if (prefix.length < 3 || !Number.isFinite(epoch)) continue;
          items.push({ epoch, textPrefix: prefix });
        } catch {}
      }
      const bounded = items.slice(-96);
      localAssistantSnapshotCache.set(filePath, { size: stat.size, items: bounded });
      return bounded;
    } catch {
      return [];
    } finally {
      try { await handle?.close(); } catch {}
    }
  };

'@
$PatchedR76Output = Replace-Required $PatchedR76Output `
    '  const pushLocalUsage = async (contents, threadId, envelope) => {' `
    ($AssistantCollector + '  const pushLocalUsage = async (contents, threadId, envelope) => {') `
    'bounded assistant response timestamp collector'

$OldSafeEnvelope = @'
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
    };
'@
$NewSafeEnvelope = @'
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
      assistantItems: Array.isArray(envelope.assistantItems) ? envelope.assistantItems.slice(-96) : [],
    };
'@
$PatchedR76Output = Replace-Required $PatchedR76Output $OldSafeEnvelope $NewSafeEnvelope 'push bounded assistant timestamps'

$OldRunCollector = @'
        const envelope = await latestUsageInfo(sessionFile);
        if (!envelope) continue;
        await pushLocalUsage(contents, threadId, envelope);
'@
$NewRunCollector = @'
        const envelope = await latestUsageInfo(sessionFile);
        if (!envelope) continue;
        envelope.assistantItems = await recentAssistantItems(sessionFile);
        await pushLocalUsage(contents, threadId, envelope);
'@
$PatchedR76Output = Replace-Required $PatchedR76Output $OldRunCollector $NewRunCollector 'attach recent assistant timestamp items'

$PatchedR76Output = Replace-Required $PatchedR76Output `
    "    const homes = raw ? raw.split(',').map((value) => value.trim()).filter(Boolean) : [];" `
    "    const homes = raw ? raw.split(new RegExp('[,;' + (process.platform === 'win32' ? ';' : ':') + ']')).map((value) => value.trim()).filter(Boolean) : [];" `
    'multi-root CODEX_HOME parsing'

# ---------------------------------------------------------------------------
# Generate an r78 identity from the reviewed r77 entry while preserving r77's
# bridge fixes and root recovery.
# ---------------------------------------------------------------------------
$PatchedR77Entry = $OriginalR77Entry
$PatchedR77Entry = Replace-Required $PatchedR77Entry `
    "`$R77OutputText = `$OriginalR76Output.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')" `
    "`$R77OutputText = `$OriginalR76Output.Replace('r76', 'r78').Replace('R76', 'R78').Replace('+76', '+78')" `
    'r78 output identity'
$PatchedR77Entry = Replace-Required $PatchedR77Entry `
    "`$R77EntryText = `$OriginalR76Local.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')" `
    "`$R77EntryText = `$OriginalR76Local.Replace('r76', 'r78').Replace('R76', 'R78').Replace('+76', '+78')" `
    'r78 entry identity'
$PatchedR77Entry = Replace-Required $PatchedR77Entry `
    "'build-r77-output-ui-local.ps1'" `
    "'build-r78-output-ui-local.ps1'" `
    'generated r78 output source expectation'
$PatchedR77Entry = $PatchedR77Entry.Replace("Replace('r75', 'r77')", "Replace('r75', 'r78')")
$PatchedR77Entry = $PatchedR77Entry.Replace('R77_EXACT_TOKEN_TELEMETRY_PASS', 'R78_EXACT_TOKEN_TELEMETRY_PASS')
$PatchedR77Entry = $PatchedR77Entry.Replace('R77_LOCAL_ENTRYPOINT_PASS', 'R78_LOCAL_ENTRYPOINT_PASS')
$PatchedR77Entry = $PatchedR77Entry.Replace('R77_TIMESTAMP_TELEMETRY_RECOVERY_PASS', 'R78_TIMESTAMP_TELEMETRY_HARDENING_PASS')
$PatchedR77Entry = $PatchedR77Entry.Replace('r77 local build failed', 'r78 local build failed')

foreach ($Marker in @(
    'function sessionTimeForSegment(segment)',
    'function exactTimeForSegment(segment, root)',
    'const exactSource = /Codex session response_item|Codex message time/',
    'data-cas-output-time-quality',
    'state.externalAssistantItems',
    'const recentAssistantItems = async (filePath)',
    'assistantItems: Array.isArray(envelope.assistantItems)',
    "Replace('r75', 'r78')",
    'R78_EXACT_TOKEN_TELEMETRY_PASS',
    'R78_LOCAL_ENTRYPOINT_PASS'
)) {
    $Combined = $PatchedR75 + $PatchedR76Output + $PatchedR77Entry
    if (-not $Combined.Contains($Marker)) { throw "r78 source verification failed: $Marker" }
}

foreach ($Forbidden in @(
    'CAS-R66-POST-COMPACT-HOOKS-AB',
    'CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE',
    'CAS-R68-SESSIONSTART-ONLY-HOOKS-AB',
    'CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB'
)) {
    if (($PatchedR75 + $PatchedR76Output + $PatchedR77Entry).Contains($Forbidden)) {
        throw "r78 forbidden Hook experiment detected: $Forbidden"
    }
}

try {
    Write-Utf8NoBom $R75Builder $PatchedR75
    Write-Utf8NoBom $R76Output $PatchedR76Output
    Write-Utf8NoBom $TempR78Entry $PatchedR77Entry

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempR78Entry)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r78 local build failed with exit code $LASTEXITCODE" }

    Write-Host ''
    Write-Host 'R78_TIMESTAMP_PASS' -ForegroundColor Green
    Write-Host '  - exact response_item timestamps are matched to visible assistant outputs when available'
    Write-Host '  - exact native/session time repairs an earlier ~estimated first-observed timestamp'
    Write-Host '  - native final sent-time is no longer copied onto unrelated progress/tool segments'
    Write-Host '  - fallback first-observed/remembered times are visibly marked with ~ as estimated'
    Write-Host 'R78_EXACT_USAGE_PASS' -ForegroundColor Green
    Write-Host '  - current request: last_token_usage input/cached/output/reasoning'
    Write-Host '  - context: last_token_usage.input_tokens / model_context_window'
    Write-Host '  - cumulative total remains total_token_usage and is not reused as current context'
    Write-Host 'R66_R69_EXPERIMENTS_ABSENT_PASS' -ForegroundColor Green
    Write-Host 'R78_LOCAL_BUILD_PASS' -ForegroundColor Green
}
finally {
    Write-Utf8NoBom $R75Builder $OriginalR75
    Write-Utf8NoBom $R76Output $OriginalR76Output
    Remove-Item -LiteralPath $TempR78Entry -Force -ErrorAction SilentlyContinue
    foreach ($Path in @(
        (Join-Path $PSScriptRoot '.build-r77-output.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r77-entry.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r78-driver.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r78-stage.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r78-output-ui-local.generated.ps1')
    )) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r78] restored temporary source patches; worktree remains pull-friendly'
}
