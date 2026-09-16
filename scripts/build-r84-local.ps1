param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R75Builder = Join-Path $PSScriptRoot 'build-r75-output-ui-local.ps1'
$R83Builder = Join-Path $PSScriptRoot 'build-r83-local.ps1'
$TempR84Builder = Join-Path $PSScriptRoot '.build-r84-from-r83.generated.ps1'

foreach ($Path in @($R75Builder,$R83Builder)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r84 required file missing: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR75 = [System.IO.File]::ReadAllText($R75Builder)
$OriginalR83 = [System.IO.File]::ReadAllText($R83Builder)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Replace-BlockRequired([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Replacement,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r84 block start missing: $Label" }
    $End = $Text.IndexOf($EndMarker,$Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r84 block end missing: $Label" }
    return $Text.Substring(0,$Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

# r75 treated generic turn/message identity containers as semantic output
# surfaces. On current Codex Desktop the whole assistant turn often owns
# data-turn-key, so every mutation collapsed to that one giant container and a
# single timestamp appeared only at its bottom. r84 separates identity from
# segmentation: only strong tool/agent/status markers are semantic; otherwise
# vertically stacked visual blocks are recursively split into independent
# output surfaces.
$SegmentationBody = @'
  function isStrongSemanticOutputSurface(node) {
    if (!(node instanceof Element)) return false;
    if (node.matches('[data-local-conversation-final-assistant]')) return true;
    return node.matches('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]');
  }

  function isSemanticOutputSurface(node) {
    return isStrongSemanticOutputSurface(node);
  }

  function directVisualChildren(parent) {
    return meaningfulDirectChildren(parent).filter(function(child) {
      if (!(child instanceof Element)) return false;
      if (child.hasAttribute(BADGE_ATTR)) return false;
      if (insideOwnUi(child) || insideComposer(child)) return false;
      return true;
    });
  }

  function isAtomicTextSurface(node) {
    if (!(node instanceof Element)) return false;
    if (isStrongSemanticOutputSurface(node)) return true;
    const tag = String(node.tagName || '').toLowerCase();
    return ['p','li','pre','blockquote','table','tr','details','summary'].includes(tag);
  }

  function verticalRowCount(children) {
    const rects = [];
    for (const child of children) {
      if (!(child instanceof Element) || !isVisible(child)) continue;
      if (normalizedText(child).length < 2 && !isStrongSemanticOutputSurface(child)) continue;
      try {
        const rect = child.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        rects.push({ top: rect.top, bottom: rect.bottom });
      } catch {}
    }
    rects.sort(function(a,b) { return a.top - b.top; });
    if (!rects.length) return 0;
    let rows = 1;
    let bottom = rects[0].bottom;
    for (let i = 1; i < rects.length; i += 1) {
      const rect = rects[i];
      if (rect.top > bottom + 2) rows += 1;
      bottom = Math.max(bottom, rect.bottom);
    }
    return rows;
  }

  function collectVisualSegments(node, root, depth) {
    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node)) return [];
    if (normalizedText(node).length < 2 && !isStrongSemanticOutputSurface(node)) return [];
    if (node.matches('[data-local-conversation-final-assistant]')) return [node];
    if (isAtomicTextSurface(node)) return [node];
    if (depth >= 12) return [node];

    const children = directVisualChildren(node).filter(function(child) {
      return normalizedText(child).length >= 2 || isStrongSemanticOutputSurface(child);
    });
    if (!children.length) return [node];

    // Wrapper-only chains are always unwrapped. This is the critical fix for
    // turn roots carrying data-turn-key/data-message-id identity attributes.
    if (children.length === 1) return collectVisualSegments(children[0], root, depth + 1);

    // Split only real vertical stacks. Horizontal icon/label rows remain one
    // timestamp surface instead of being fragmented into spans/icons.
    if (verticalRowCount(children) < 2) return [node];

    const out = [];
    for (const child of children) {
      const nested = collectVisualSegments(child, root, depth + 1);
      for (const item of nested) out.push(item);
    }
    return out.length ? out : [node];
  }

  function topLevelSegments(root) {
    if (!(root instanceof Element)) return [];
    if (root.matches('[data-local-conversation-final-assistant]')) return [root];

    let candidates = collectVisualSegments(root, root, 0);
    const final = root.querySelector('[data-local-conversation-final-assistant]');
    if (final) {
      candidates = candidates.filter(function(candidate) {
        return candidate === final || !candidate.contains(final);
      });
      candidates.push(final);
    }

    const unique = [];
    const seen = new Set();
    for (const candidate of candidates) {
      if (!(candidate instanceof Element) || seen.has(candidate)) continue;
      if (!root.contains(candidate) && candidate !== root) continue;
      if (!isVisible(candidate) || insideComposer(candidate) || insideOwnUi(candidate)) continue;
      if (normalizedText(candidate).length < 2 && !isStrongSemanticOutputSurface(candidate)) continue;
      seen.add(candidate);
      unique.push(candidate);
    }
    return unique;
  }

  function semanticProgressSurface(node, root) {
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || !(root instanceof Element)) return null;
    const selector = '[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]';
    const candidate = element.closest(selector);
    if (candidate && candidate !== root && root.contains(candidate) && !insideComposer(candidate)) return candidate;
    return null;
  }

  function segmentForMutation(node, root) {
    if (!(root instanceof Element)) return null;
    const element = node instanceof Element ? node : node && node.parentElement;
    if (!element || insideComposer(element) || insideOwnUi(element)) return null;

    const final = finalSurfaceFor(element, root);
    if (final) return final;
    const semantic = semanticProgressSurface(element, root);
    if (semantic) return semantic;

    const candidates = topLevelSegments(root);
    const containing = candidates
      .filter(function(candidate) { return candidate === element || candidate.contains(element); })
      .sort(function(a,b) {
        try { return a.getBoundingClientRect().height - b.getBoundingClientRect().height; }
        catch { return 0; }
      });
    return containing[0] || null;
  }

  function structuralPath(node, stop) {
    const parts = [];
    let current = node;
    for (let depth = 0; depth < 18 && current && current !== stop; depth += 1) {
      const parent = current.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children || []).filter(function(child) {
        return !(child instanceof Element && child.hasAttribute(BADGE_ATTR));
      });
      const index = siblings.indexOf(current);
      parts.unshift(index >= 0 ? index : 0);
      current = parent;
    }
    return parts.join('.');
  }

  function segmentKey(segment, root) {
    if (!(segment instanceof Element) || !(root instanceof Element)) return '';
    const turn = root.closest('[data-turn-key]') || root;
    const rootId =
      root.getAttribute('data-content-search-assistant-turn-key') ||
      turn.getAttribute('data-turn-key') ||
      root.getAttribute('data-message-id') ||
      structuralPath(root, document.body);
    const semanticId =
      segment.getAttribute('data-turn-key') ||
      segment.getAttribute('data-message-id') ||
      segment.getAttribute('data-testid') ||
      segment.getAttribute('role') || '';
    const kind = segment.matches('[data-local-conversation-final-assistant]') ? 'final' : 'segment';
    return simpleHash(String(location.pathname || '') + '|' + String(location.hash || '') + '|' + rootId + '|' + structuralPath(segment, root) + '|' + semanticId + '|' + kind);
  }
'@
$NewSegmentation = '$NewSegmentation = @''' + "`r`n" + $SegmentationBody + "`r`n'@"

$PatchedR75 = Replace-BlockRequired `
    $OriginalR75 `
    '$NewSegmentation = @''' `
    '$NewStamp = @''' `
    $NewSegmentation `
    'per-output visual segmentation'

foreach ($Marker in @(
    'function isStrongSemanticOutputSurface(node) {',
    'function collectVisualSegments(node, root, depth) {',
    'if (children.length === 1) return collectVisualSegments(children[0], root, depth + 1);',
    'if (verticalRowCount(children) < 2) return [node];',
    'candidate !== root',
    "const selector = '[role=\"status\"],[data-testid*=\"agent\"],[data-testid*=\"tool\"],[data-testid*=\"command\"],[data-testid*=\"integration\"]';"
)) {
    if (-not $PatchedR75.Contains($Marker)) { throw "r84 segmentation verification failed: $Marker" }
}
if ($PatchedR75.Contains("return node.matches('[role=\"status\"],[data-testid*=\"agent\"],[data-testid*=\"tool\"],[data-testid*=\"command\"],[data-testid*=\"integration\"],[data-turn-key],[data-message-id]');")) {
    throw 'r84 old whole-turn semantic segmentation is still present'
}

# Retarget the already-preflighted r83 package chain to r84. No carry-forward,
# telemetry or provider logic is changed here; only the timestamp segmentation
# source is replaced above.
$R84BuilderText = $OriginalR83.Replace('r83','r84').Replace('R83','R84').Replace('+83','+84')
foreach ($Marker in @(
    'R84_STATIC_PIPELINE_PREFLIGHT_PASS',
    'R84_TIMESTAMP_ACTIONROW_V4_PASS',
    'R84_EXACT_TOKEN_TELEMETRY_PASS',
    'R84_R43_R65_CARRY_FORWARD_PACKAGE_PASS',
    'visible/package identity is r84 / 2.4.5+84'
)) {
    if (-not $R84BuilderText.Contains($Marker)) { throw "r84 retarget verification failed: $Marker" }
}

# Parse both PowerShell layers before touching the worktree.
$ParseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($PatchedR75,[ref]$null,[ref]$ParseErrors)
if ($ParseErrors.Count -gt 0) { throw "r84 patched r75 parse failed: $($ParseErrors[0].Message)" }
$ParseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($R84BuilderText,[ref]$null,[ref]$ParseErrors)
if ($ParseErrors.Count -gt 0) { throw "r84 generated builder parse failed: $($ParseErrors[0].Message)" }

Write-Host 'R84_TIMESTAMP_SEGMENTATION_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - generic data-turn-key/data-message-id containers are identity only, not timestamp surfaces'
Write-Host '  - wrapper-only chains unwrap until real visual output blocks'
Write-Host '  - vertically stacked assistant/tool/agent blocks become independent timestamp surfaces'
Write-Host '  - horizontal icon/label rows remain atomic'
Write-Host '  - r83 exact telemetry and r43-r65 carry-forward chain are unchanged'

try {
    Write-Utf8NoBom $R75Builder $PatchedR75
    Write-Utf8NoBom $TempR84Builder $R84BuilderText

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR84Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r84 nested builder failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R84_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R84_PER_OUTPUT_TIMESTAMP_SEGMENTATION_PASS' -ForegroundColor Green
        Write-Host '  - each new vertically distinct assistant/progress/tool/agent block receives its own first-observed timestamp'
        Write-Host '  - a turn-level data-turn-key can no longer collapse the whole visible turn to one bottom timestamp'
        Write-Host '  - final-answer action-row timestamp behavior from r78/r83 remains intact'
    }
}
finally {
    Write-Utf8NoBom $R75Builder $OriginalR75
    Remove-Item -LiteralPath $TempR84Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r84] restored temporary timestamp source patches; worktree remains pull-friendly'
}
