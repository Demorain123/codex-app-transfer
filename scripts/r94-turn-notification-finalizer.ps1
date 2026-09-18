# R94_TURN_NOTIFICATION_FINALIZER
# Offers only relevant parsed Codex lifecycle/token notifications to the
# bounded r94 TurnCapability. Existing token accounting remains intact.

if (-not (Get-Variable -Name Patched -Scope 0 -ErrorAction SilentlyContinue)) {
    throw 'r94 notification finalizer requires $Patched'
}

$R94ConsumeText = @'
  function consumeText(text) {
    if (!text || typeof text !== 'string') return;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.replace(/^data:\s*/, '').trim();
      if (!line || line === '[DONE]') continue;
      const isToken = /token_count|last_token_usage|total_token_usage|model_context_window|thread\/tokenUsage\/updated|thread_token_usage_updated|usage/i.test(line);
      const isLifecycle = /turn\/(?:started|completed)|turn_(?:started|completed)|task_(?:started|complete)/i.test(line);
      if (!isToken && !isLifecycle) continue;

      let parsed = null;
      try { parsed = JSON.parse(line); } catch { parsed = null; }
      if (!parsed) continue;

      if (isLifecycle || /thread\/tokenUsage\/updated|thread_token_usage_updated/i.test(line)) {
        try {
          const capability = window.__casR94TurnCapability;
          if (capability && typeof capability.ingestNotification === 'function') {
            capability.ingestNotification(parsed);
          }
        } catch {}
      }

      if (isLifecycle && /turn\/completed|turn_completed|task_complete/i.test(line)) {
        state.metrics.done = true;
      }
      if (isToken) {
        try { consumeValue(parsed, 0); } catch {}
      }
    }
  }
'@

$Patched = Replace-BlockRequired $Patched '  function consumeText(text) {' '  function installFetchObserver() {' $R94ConsumeText 'r94 passive exact turn notification ingestion'

foreach ($Marker in @(
    'window.__casR94TurnCapability',
    "typeof capability.ingestNotification === 'function'",
    'thread\/tokenUsage\/updated',
    'turn\/(?:started|completed)',
    'task_(?:started|complete)'
)) {
    if (-not $Patched.Contains($Marker)) {
        throw "r94 notification finalizer marker missing: $Marker"
    }
}

Write-Host 'R94_PASSIVE_TURN_NOTIFICATION_INGEST_PASS' -ForegroundColor Green
