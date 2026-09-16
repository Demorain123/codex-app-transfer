param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$R84Builder = Join-Path $PSScriptRoot 'build-r84-local.ps1'
$TempR85Builder = Join-Path $PSScriptRoot '.build-r85-from-r84.generated.ps1'

if (-not (Test-Path -LiteralPath $R84Builder)) {
    throw "r85 requires r84 builder: $R84Builder"
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$OriginalR84 = [System.IO.File]::ReadAllText($R84Builder)

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Replace-BlockRequired([string]$Text,[string]$StartMarker,[string]$EndMarker,[string]$Replacement,[string]$Label) {
    $Start = $Text.IndexOf($StartMarker)
    if ($Start -lt 0) { throw "r85 block start missing: $Label" }
    $End = $Text.IndexOf($EndMarker,$Start + $StartMarker.Length)
    if ($End -le $Start) { throw "r85 block end missing: $Label" }
    return $Text.Substring(0,$Start) + $Replacement + "`r`n`r`n" + $Text.Substring($End)
}

# r84 fixed the giant-turn collapse, but it recursed all the way into Markdown
# paragraphs/list items. A single streamed assistant output therefore became
# several timestamp surfaces discovered in the same sweep, producing repeated
# times and visual noise. r85 keeps semantic tool/agent/status rows independent
# while treating a real Markdown/prose renderer subtree as one visible output
# block. Adjacent generic output wrappers are deliberately NOT merged.
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

  function isTextFlowTag(node) {
    if (!(node instanceof Element)) return false;
    const tag = String(node.tagName || '').toLowerCase();
    return [
      'p','span','strong','em','b','i','a','code','pre','blockquote',
      'ul','ol','li','dl','dt','dd','table','thead','tbody','tfoot','tr','td','th',
      'h1','h2','h3','h4','h5','h6','figure','figcaption','details','summary'
    ].includes(tag);
  }

  function isPureProseSubtree(node, depth) {
    if (!(node instanceof Element) || !isVisible(node) || insideComposer(node) || insideOwnUi(node)) return false;
    if (isStrongSemanticOutputSurface(node)) return false;
    if (node.querySelector('[role="status"],[data-testid*="agent"],[data-testid*="tool"],[data-testid*="command"],[data-testid*="integration"]')) return false;
    if (isTextFlowTag(node)) return true;
    if (depth >= 4) return false;
    const children = directVisualChildren(node).filter(function(child) {
      return normalizedText(child).length >= 2;
    });
    if (!children.length) return normalizedText(node).length >= 2;
    return children.every(function(child) { return isPureProseSubtree(child, depth + 1); });
  }

  function maxVerticalGap(children) {
    const rects = [];
    for (const child of children) {
      if (!(child instanceof Element) || !isVisible(child)) continue;
      try {
        const rect = child.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        rects.push({ top: rect.top, bottom: rect.bottom });
      } catch {}
    }
    rects.sort(function(a,b) { return a.top - b.top; });
    let maxGap = 0;
    for (let i = 1; i < rects.length; i += 1) {
      maxGap = Math.max(maxGap, Math.max(0, rects[i].top - rects[i - 1].bottom));
    }
    return maxGap;
  }

  function shouldKeepAsProseGroup(node, children) {
    if (!(node instanceof Element) || children.length < 2) return false;
    if (!children.every(function(child) { return isPureProseSubtree(child, 0); })) return false;

    // Do not merge multiple sibling output wrappers just because they all
    // contain text. A real Markdown/prose renderer normally exposes its text
    // flow nodes (p/ul/pre/etc.) directly. Requiring direct text-flow children
    // keeps separate streamed output wrappers independent.
    const directTextFlowCount = children.filter(function(child) { return isTextFlowTag(child); }).length;
    const minimumDirectTextFlow = Math.max(2, Math.ceil(children.length * 0.6));
    if (!isTextFlowTag(node) && directTextFlowCount < minimumDirectTextFlow) return false;

    // Paragraphs/list/code within one renderer are normally close together;
    // a large vertical gap is treated as a real output boundary.
    return maxVerticalGap(children) <= 40;
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
    if (isStrongSemanticOutputSurface(node)) return [node];
    if (depth >= 12) return [node];

    const children = directVisualChildren(node).filter(function(child) {
      return normalizedText(child).length >= 2 || isStrongSemanticOutputSurface(child);
    });
    if (!children.length) return [node];

    // Wrapper-only chains are unwrapped until a real output boundary appears.
    if (children.length === 1) return collectVisualSegments(children[0], root, depth + 1);

    // Critical r85 correction: one Markdown/prose output is one timestamp
    // surface even when it contains multiple paragraphs, list items or code
    // blocks. Separate sibling output wrappers are not merged.
    if (shouldKeepAsProseGroup(node, children)) return [node];

    // Horizontal icon/label/action rows stay atomic.
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
$NewSegmentation = '$SegmentationBody = @''' + "`r`n" + $SegmentationBody + "`r`n'@"

# Retarget the already working r84 packaging chain to r85, then replace only
# the timestamp segmentation body. Provider/model routing, telemetry and the
# r43-r65 materialization chain remain byte-for-byte inherited from r84.
$R85BuilderText = $OriginalR84.Replace('r84','r85').Replace('R84','R85').Replace('+84','+85')
$R85BuilderText = Replace-BlockRequired `
    $R85BuilderText `
    '$SegmentationBody = @''' `
    '$NewSegmentation = ' `
    $NewSegmentation `
    'group Markdown/prose into one visible output timestamp surface'

foreach ($Marker in @(
    'function isPureProseSubtree(node, depth) {',
    'function shouldKeepAsProseGroup(node, children) {',
    'const minimumDirectTextFlow = Math.max(2, Math.ceil(children.length * 0.6));',
    'if (shouldKeepAsProseGroup(node, children)) return [node];',
    'R85_TIMESTAMP_SEGMENTATION_PREFLIGHT_PASS',
    'R85_TIMESTAMP_ACTIONROW_V4_PASS',
    'R85_EXACT_TOKEN_TELEMETRY_PASS',
    'R85_R43_R65_CARRY_FORWARD_PACKAGE_PASS',
    'visible/package identity is r85 / 2.4.5+85'
)) {
    if (-not $R85BuilderText.Contains($Marker)) { throw "r85 generated builder verification failed: $Marker" }
}

if ($R85BuilderText.Contains("return ['p','li','pre','blockquote','table','tr','details','summary'].includes(tag);")) {
    throw 'r85 still contains the r84 paragraph-per-timestamp atomic split'
}

$ParseTokens = $null
$ParseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($R85BuilderText,[ref]$ParseTokens,[ref]$ParseErrors)
if ($ParseErrors.Count -gt 0) {
    throw "r85 generated PowerShell parse failed: $($ParseErrors[0].Message)"
}

Write-Host 'R85_TIMESTAMP_GROUPING_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - one Markdown/prose renderer maps to one timestamp surface'
Write-Host '  - adjacent generic output wrappers are not merged'
Write-Host '  - tool/agent/status/error rows remain independent timestamp surfaces'
Write-Host '  - r78 exact-vs-estimated timestamp confidence and action-row anchoring are preserved'
Write-Host '  - r83 exact telemetry and r43-r65 carry-forward package are unchanged'
Write-Host '  - provider/model routing is not modified by r85'

try {
    Write-Utf8NoBom $TempR85Builder $R85BuilderText

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempR85Builder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }
    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r85 nested builder failed with exit code $LASTEXITCODE" }

    if ($PreflightOnly) {
        Write-Host 'R85_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
    } else {
        Write-Host ''
        Write-Host 'R85_OUTPUT_TIMESTAMP_GROUPING_PASS' -ForegroundColor Green
        Write-Host '  - paragraphs/lists/code within one assistant output no longer receive duplicate sibling timestamps'
        Write-Host '  - separate output wrappers and semantic progress/tool/agent/error outputs keep independent times'
        Write-Host '  - final assistant timestamp still anchors after the native Codex action row when available'
    }
}
finally {
    Remove-Item -LiteralPath $TempR85Builder -Force -ErrorAction SilentlyContinue
    Write-Host '[r85] removed temporary generated builder; tracked worktree stays pull-friendly'
}
