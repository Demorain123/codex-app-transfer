param(
    [switch]$RunFocusedTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R76Local = Join-Path $PSScriptRoot 'build-r76-local.ps1'
$R76Output = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$TempR77Output = Join-Path $PSScriptRoot '.build-r77-output.generated.ps1'
$TempR77Entry = Join-Path $PSScriptRoot '.build-r77-entry.generated.ps1'

foreach ($Path in @($R76Local, $R76Output, $R75Builder)) {
    if (-not (Test-Path $Path)) { throw "r77 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR76Local = [System.IO.File]::ReadAllText($R76Local)
$OriginalR76Output = [System.IO.File]::ReadAllText($R76Output)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Required([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r77 expected text missing: $Label" }
    return $Text.Replace($Old, $New)
}

# ---------------------------------------------------------------------------
# Timestamp recovery
# ---------------------------------------------------------------------------
# r75 already carries the reviewed per-output timestamp renderer, but its root
# discovery still depends mainly on older Codex/ChatGPT wrapper attributes.
# Current Codex Desktop keeps stable assistant sent-time markers and the thread
# footer / above-composer portal even when those older wrappers are remounted.
# Add a fallback root resolver around those stable anchors while retaining the
# existing segmentation and first-seen cache logic.
$OldAssistantRoots = @'
  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    document.querySelectorAll(ASSISTANT_ROOT_SELECTOR).forEach(function(node) {
      const root = assistantRootFor(node) || (node instanceof Element ? node : null);
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root)) return;
      seen.add(root);
      roots.push(root);
    });
    return roots;
  }
'@

$NewAssistantRoots = @'
  function fallbackAssistantRoot(node) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!(element instanceof Element) || insideComposer(element) || insideOwnUi(element)) return null;

    const authored = element.closest('[data-message-author-role="assistant"]');
    if (authored) return authored;

    const sent = element.closest('[data-assistant-message-sent-time]') ||
      element.querySelector && element.querySelector('[data-assistant-message-sent-time]');
    if (sent) {
      const turn = sent.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"],[data-content-search-assistant-turn-key]');
      return turn || sent.parentElement || sent;
    }

    const semantic = element.closest('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"],[data-message-id]');
    if (semantic) {
      const turn = semantic.closest('[data-turn-key],[data-chatgpt-conversation-turn="true"],[data-content-search-assistant-turn-key]');
      if (turn) return turn;
      if (!semantic.closest('[data-thread-scroll-footer="true"]')) return semantic.parentElement || semantic;
    }

    const footer = document.querySelector('[data-thread-scroll-footer="true"]');
    const threadHost = footer && footer.parentElement;
    if (threadHost && threadHost.contains(element)) {
      let current = element;
      while (current && current.parentElement && current.parentElement !== threadHost) current = current.parentElement;
      if (current && current !== footer && !current.matches('[data-thread-scroll-footer="true"]')) {
        const assistantMarker = current.querySelector('[data-assistant-message-sent-time],[data-message-author-role="assistant"],[data-local-conversation-final-assistant],[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
        if (assistantMarker) return current;
      }
    }
    return null;
  }

  function assistantRootForAny(node) {
    return assistantRootFor(node) || fallbackAssistantRoot(node);
  }

  function assistantRootsNow() {
    const roots = [];
    const seen = new Set();
    const selector = ASSISTANT_ROOT_SELECTOR +
      ',[data-message-author-role="assistant"],[data-assistant-message-sent-time],' +
      '[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]';
    document.querySelectorAll(selector).forEach(function(node) {
      const root = assistantRootForAny(node);
      if (!(root instanceof Element) || seen.has(root) || insideComposer(root) || insideOwnUi(root)) return;
      seen.add(root);
      roots.push(root);
    });
    return roots;
  }
'@

$PatchedR75 = Replace-Required $OriginalR75 $OldAssistantRoots $NewAssistantRoots 'timestamp fallback assistant roots'
$PatchedR75 = Replace-Required $PatchedR75 `
    '    const root = assistantRootFor(node);' `
    '    const root = assistantRootForAny(node);' `
    'timestamp mutation fallback root'

# ---------------------------------------------------------------------------
# Exact telemetry recovery
# ---------------------------------------------------------------------------
# Generate an r77 variant of the r76 builder and fix two independent breakages:
# 1. r76 defined ingestExternalUsage() but never exposed it on the runtime state,
#    while the Electron collector calls state.ingestExternalUsage(...).
# 2. active-thread lookup favored sidebar attributes that are not guaranteed on
#    current builds. Prefer Codex's stable above-composer conversation id, then
#    the /thread/<id> route, before retaining the old sidebar fallbacks.
$R77OutputText = $OriginalR76Output.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')

$OldIngestTail = @'
    state.metrics.externalUpdatedAt = Number(envelope.updatedAt) || Date.now();
    try { refreshUi(); } catch {}
    return true;
  }

'@
$NewIngestTail = @'
    state.metrics.externalUpdatedAt = Number(envelope.updatedAt) || Date.now();
    if (typeof envelope.model === 'string' && envelope.model.trim()) {
      state.metrics.model = envelope.model.trim();
    }
    try { refreshUi(); } catch {}
    return true;
  }
  state.ingestExternalUsage = ingestExternalUsage;

'@
$R77OutputText = Replace-Required $R77OutputText $OldIngestTail $NewIngestTail 'expose external usage ingestion bridge'

$OldActiveThread = @'
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
'@
$NewActiveThread = @'
  const activeThreadExpression = "(() => {" +
    "const a=(e,n)=>e&&e.getAttribute?e.getAttribute(n):null;" +
    "const p=document.querySelector('[data-above-composer-portal][data-above-composer-conversation-id]')||document.querySelector('[data-above-composer-conversation-id]');" +
    "const pid=a(p,'data-above-composer-conversation-id');" +
    "const href=decodeURIComponent(String(location.href||''));" +
    "const m=href.match(/(?:^|[\\/#])thread\\/([^/?#]+)/i);" +
    "const rid=m&&m[1]?m[1]:null;" +
    "const r=document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][aria-current=\"page\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-active=\"true\"]')||" +
      "document.querySelector('[data-app-action-sidebar-thread-row][data-app-action-sidebar-thread-active]:not([data-app-action-sidebar-thread-active=\"false\"])');" +
    "return pid||rid||a(r,'data-app-action-sidebar-thread-id')||" +
      "a(r&&r.querySelector('[data-app-action-sidebar-thread-id]'),'data-app-action-sidebar-thread-id')||" +
      "a(document.querySelector('[data-conversation-id]'),'data-conversation-id')||null;" +
  "})()";
'@
$R77OutputText = Replace-Required $R77OutputText $OldActiveThread $NewActiveThread 'stable active thread resolver'

$R77OutputText = Replace-Required $R77OutputText `
    '            if (!info || !info.last_token_usage || !info.total_token_usage) continue;' `
    '            if (!info || !info.last_token_usage) continue;' `
    'accept last usage even when cumulative total is temporarily absent'

# Attach the latest turn_context model when it is present in the same bounded
# tail. This makes the model label independent of transient picker DOM.
$OldEnvelope = @'
            const envelope = {
              info,
              updatedAt: Date.parse(row.timestamp || '') || Date.now(),
            };
'@
$NewEnvelope = @'
            let model = null;
            for (let probe = index; probe >= 0; probe -= 1) {
              const candidateLine = lines[probe];
              if (!candidateLine || !candidateLine.includes('turn_context') || !candidateLine.includes('model')) continue;
              try {
                const candidate = JSON.parse(candidateLine);
                const candidateModel = candidate && candidate.type === 'turn_context' && candidate.payload && candidate.payload.model;
                if (typeof candidateModel === 'string' && candidateModel.trim()) {
                  model = candidateModel.trim();
                  break;
                }
              } catch {}
            }
            const envelope = {
              info,
              model,
              updatedAt: Date.parse(row.timestamp || '') || Date.now(),
            };
'@
$R77OutputText = Replace-Required $R77OutputText $OldEnvelope $NewEnvelope 'bounded turn_context model lookup'

# ---------------------------------------------------------------------------
# r77 identity / entrypoint generation
# ---------------------------------------------------------------------------
$R77EntryText = $OriginalR76Local.Replace('r76', 'r77').Replace('R76', 'R77').Replace('+76', '+77')
$R77EntryText = Replace-Required $R77EntryText `
    "`$Source = Join-Path `$PSScriptRoot 'build-r77-output-ui-local.ps1'" `
    "`$Source = Join-Path `$PSScriptRoot '.build-r77-output.generated.ps1'" `
    'generated r77 output source path'

foreach ($Marker in @(
    'state.ingestExternalUsage = ingestExternalUsage;',
    'data-above-composer-conversation-id',
    'assistantRootForAny(node)',
    "Replace('r75', 'r77')",
    'R77_EXACT_TOKEN_TELEMETRY_PASS',
    'R77_LOCAL_ENTRYPOINT_PASS'
)) {
    $Combined = $PatchedR75 + $R77OutputText + $R77EntryText
    if (-not $Combined.Contains($Marker)) { throw "r77 generated source verification failed: $Marker" }
}

try {
    Write-Utf8NoBom $R75Builder $PatchedR75
    Write-Utf8NoBom $TempR77Output $R77OutputText
    Write-Utf8NoBom $TempR77Entry $R77EntryText

    $Args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TempR77Entry)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r77 local build failed with exit code $LASTEXITCODE" }

    Write-Host ''
    Write-Host 'R77_TIMESTAMP_TELEMETRY_RECOVERY_PASS' -ForegroundColor Green
    Write-Host '  - exact JSONL usage bridge is now callable from the Electron collector'
    Write-Host '  - active thread prefers the stable above-composer conversation id / thread route'
    Write-Host '  - ctx/in/out/cache/total can populate from last_token_usage without the native Usage panel'
    Write-Host '  - assistant timestamp discovery falls back to sent-time, semantic output, and thread-scroll anchors'
    Write-Host '  - model label can fall back to the latest bounded turn_context record'
}
finally {
    Write-Utf8NoBom $R75Builder $OriginalR75
    foreach ($Path in @(
        $TempR77Output,
        $TempR77Entry,
        (Join-Path $PSScriptRoot '.build-r77-driver.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r77-stage.generated.ps1'),
        (Join-Path $PSScriptRoot '.build-r77-output-ui-local.generated.ps1')
    )) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r77] restored temporary source patches; worktree remains pull-friendly'
}
