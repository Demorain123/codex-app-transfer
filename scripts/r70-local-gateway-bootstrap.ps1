param(
    [switch]$Apply,
    [switch]$RunChecks,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBase = '34a398f7976b7cba0b267d3bc6ed31d0c7bf27e9'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $enc = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Path, $Text, $enc)
}

function Replace-Once([string]$Text, [string]$Old, [string]$New, [string]$Label) {
    $first = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw "r70 bootstrap anchor missing: $Label"
    }
    $second = $Text.IndexOf($Old, $first + $Old.Length, [StringComparison]::Ordinal)
    if ($second -ge 0) {
        throw "r70 bootstrap anchor is not unique: $Label"
    }
    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

Push-Location $RepoRoot
try {
    $inside = (& git rev-parse --is-inside-work-tree 2>$null).Trim()
    if ($inside -ne 'true') { throw 'Run this script from the codex-app-transfer checkout.' }

    & git cat-file -e "$ExpectedBase^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Expected r69 base commit is missing: $ExpectedBase" }

    & git merge-base --is-ancestor $ExpectedBase HEAD
    if ($LASTEXITCODE -ne 0) { throw "Current HEAD is not descended from the expected r69 base $ExpectedBase" }

    $dirty = @(& git status --porcelain)
    if ($dirty.Count -gt 0 -and -not $Force) {
        throw "Worktree is not clean. Commit/stash unrelated changes, or rerun with -Force after reviewing them.`n$($dirty -join "`n")"
    }

    if (-not $Apply) {
        Write-Host 'r70 bootstrap preflight PASS.' -ForegroundColor Green
        Write-Host 'Re-run with -Apply to patch the local checkout; add -RunChecks to run focused Rust tests.'
        exit 0
    }

    # ---------------------------------------------------------------------
    # 1) Built-in provider: formal daily path is Transfer -> Sub2API -> llama.cpp.
    #    The six existing model slots are reused; no parallel alias database/UI.
    # ---------------------------------------------------------------------
    $presetPath = Join-Path $RepoRoot 'crates/registry/src/presets_data.json'
    $presetText = Read-Normalized $presetPath
    if ($presetText -notmatch '"id"\s*:\s*"sub2api-local"') {
        $preset = @'
  {
    "id": "sub2api-local",
    "name": "Sub2API Local Gateway",
    "baseUrl": "http://127.0.0.1:8089/v1",
    "docsUrl": "https://github.com/Demorain123/sub2api-xray",
    "authScheme": "bearer",
    "apiFormat": "openai_chat",
    "models": {
      "default": "q36-35b-a3b",
      "gpt_5_5": "q38-dt-iq3xxs",
      "gpt_5_4": "q38-dt-iq2s",
      "gpt_5_4_mini": "q38-gsq-iq3s",
      "gpt_5_3_codex": "q38-efficient-q2",
      "gpt_5_2": "q38-unsloth-iq3xxs"
    },
    "modelCapabilities": {
      "q38-dt-iq3xxs": {
        "context_window": 131072,
        "display_name": "Qwen3.8 DT-IQ3 MTP3 128K",
        "supports_vision": false
      },
      "q38-dt-iq2s": {
        "context_window": 131072,
        "display_name": "Qwen3.8 DT-IQ2 MTP2 128K",
        "supports_vision": false
      },
      "q38-gsq-iq3s": {
        "context_window": 131072,
        "display_name": "Qwen3.8 GSQ IQ3S Ngram 128K",
        "supports_vision": false
      },
      "q38-efficient-q2": {
        "context_window": 131072,
        "display_name": "Qwen3.8 Efficient Q2 Ngram 128K",
        "supports_vision": false
      },
      "q38-unsloth-iq3xxs": {
        "context_window": 131072,
        "display_name": "Qwen3.8 Unsloth IQ3 Vanilla 128K",
        "supports_vision": false
      },
      "q36-35b-a3b": {
        "context_window": 131072,
        "display_name": "Qwen3.6 35B-A3B MoE 128K",
        "supports_vision": false
      }
    },
    "notices": [
      {
        "type": "info",
        "text": "Local model runtime stays in llama.cpp Router. Sub2API is the canonical local gateway/catalog; Transfer only performs Codex protocol/tool adaptation."
      }
    ],
    "isBuiltin": true
  }
'@
        $trimmed = $presetText.TrimEnd()
        if (-not $trimmed.EndsWith(']')) { throw 'presets_data.json is not a JSON array.' }
        $prefix = $trimmed.Substring(0, $trimmed.Length - 1).TrimEnd()
        $comma = if ($prefix.EndsWith('[')) { '' } else { ',' }
        $presetText = $prefix + $comma + "`n" + $preset.TrimEnd() + "`n]`n"
        Write-Utf8NoBom $presetPath $presetText
    }

    $presetsRsPath = Join-Path $RepoRoot 'crates/registry/src/presets.rs'
    $presetsRs = Read-Normalized $presetsRsPath
    if ($presetsRs -match 'assert_eq!\(builtin_presets\(\)\.len\(\), 22\);') {
        $presetsRs = $presetsRs.Replace(
            'assert_eq!(builtin_presets().len(), 22);',
            'assert_eq!(builtin_presets().len(), 23);'
        )
        Write-Utf8NoBom $presetsRsPath $presetsRs
    } elseif ($presetsRs -notmatch 'assert_eq!\(builtin_presets\(\)\.len\(\), 23\);') {
        throw 'Could not locate builtin preset count assertion (expected 22 or already-patched 23).'
    }

    # ---------------------------------------------------------------------
    # 2) Codex catalog: retain the existing five GPT routing slots, but expose
    #    an intentionally-distinct provider default as a sixth entry.
    #    Also let generic modelCapabilities supply display_name, mirroring the
    #    metadata-first patterns used by llama-swap / OMP without a new DB.
    # ---------------------------------------------------------------------
    $catalogPath = Join-Path $RepoRoot 'crates/codex_integration/src/model_catalog.rs'
    $catalog = Read-Normalized $catalogPath

    if ($catalog -notmatch 'CAS-R70-SIXTH-DEFAULT-CATALOG') {
        $oldCall = @'
            display_names,
            review_override.clone(),
            is_qoder,
'@
        $newCall = @'
            display_names,
            model_capabilities,
            review_override.clone(),
            is_qoder,
'@
        $catalog = Replace-Once $catalog $oldCall $newCall 'catalog_model slot call'

        $oldTail = @'
    // [MOC-154] 去掉旧 fallback entry(slug = default_model 实际模型名)。列表式下
    // Codex `model` 字段统一锚到 gpt-5.5 slot(见 apply.rs `ensure_default_model_slot`),
    // 不再出现 `model = 实际模型名` → 无需该 entry;且它与 gpt-5.5(空槽时 display =
    // default)的 display 相同,会造成"默认模型显示两次"的重复。
    models
}
'@
        $newTail = @'
    // CAS-R70-SIXTH-DEFAULT-CATALOG:
    // Keep the existing five Codex routing slots, but when `default` is intentionally
    // a sixth *different* upstream model, expose it with its real model id as the slug.
    // The proxy resolver already falls back unknown slugs to provider.models.default,
    // therefore a raw default slug routes to the same raw upstream id without a new
    // alias table. Existing providers are unchanged when gpt-5.5 already represents
    // the default target (the common case).
    if !default_model.is_empty() {
        let default_already_exposed = MODEL_SLOTS
            .iter()
            .filter_map(|slot| {
                slot.openai_id?;
                let mapped = mappings.get(slot.key).map(|s| s.trim()).unwrap_or("");
                let target = if mapped.is_empty() {
                    if slot.key == "gpt_5_5" {
                        default_model
                    } else {
                        return None;
                    }
                } else {
                    mapped
                };
                Some(strip_internal_model_suffix(target))
            })
            .any(|target| target.trim() == default_model);

        if !default_already_exposed {
            let context_window = context_window_for_model(
                default_model,
                default_model,
                default_model,
                supports_1m,
                model_capabilities,
                is_qoder,
            );
            models.push(catalog_model(
                default_model,
                provider_name,
                default_model,
                context_window,
                display_names,
                model_capabilities,
                review_override.clone(),
                is_qoder,
            ));
        }
    }
    models
}
'@
        $catalog = Replace-Once $catalog $oldTail $newTail 'catalog default tail'

        $oldSig = @'
    context_window: u64,
    display_names: Option<&Value>,
    auto_review_model_override: Option<String>,
'@
        $newSig = @'
    context_window: u64,
    display_names: Option<&Value>,
    model_capabilities: Option<&Value>,
    auto_review_model_override: Option<String>,
'@
        $catalog = Replace-Once $catalog $oldSig $newSig 'catalog_model signature'

        $catalog = Replace-Once $catalog `
            'display_name: resolve_display_label(target, display_names),' `
            'display_name: resolve_display_label(target, display_names, model_capabilities),' `
            'catalog_model display label call'

        $oldResolve = @'
fn resolve_display_label(model_id: &str, display_names: Option<&Value>) -> String {
    display_names
        .and_then(|v| v.get(model_id))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| model_id.to_owned())
}
'@
        $newResolve = @'
fn resolve_display_label(
    model_id: &str,
    display_names: Option<&Value>,
    model_capabilities: Option<&Value>,
) -> String {
    // Provider-specific display-name tables remain highest priority. Generic
    // providers/gateways can declare the same metadata once beside context_window,
    // avoiding another Transfer-only alias registry.
    display_names
        .and_then(|v| v.get(model_id))
        .and_then(Value::as_str)
        .or_else(|| {
            model_capabilities
                .and_then(|v| v.get(model_id))
                .and_then(|v| v.get("display_name"))
                .and_then(Value::as_str)
        })
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| model_id.to_owned())
}
'@
        $catalog = Replace-Once $catalog $oldResolve $newResolve 'resolve_display_label'
        Write-Utf8NoBom $catalogPath $catalog
    }

    # ---------------------------------------------------------------------
    # 3) Focused regression test: six distinct catalog choices, 128K effective
    #    context, and metadata-driven friendly names.
    # ---------------------------------------------------------------------
    $testsDir = Join-Path $RepoRoot 'crates/codex_integration/tests'
    [IO.Directory]::CreateDirectory($testsDir) | Out-Null
    $testPath = Join-Path $testsDir 'r70_local_gateway_catalog.rs'
    if (-not (Test-Path $testPath)) {
        $test = @'
use codex_app_transfer_codex_integration::catalog_models_for_provider_with_display_names;
use serde_json::json;

#[test]
fn r70_local_gateway_exposes_six_distinct_128k_choices() {
    let mappings = json!({
        "default": "q36-35b-a3b",
        "gpt_5_5": "q38-dt-iq3xxs",
        "gpt_5_4": "q38-dt-iq2s",
        "gpt_5_4_mini": "q38-gsq-iq3s",
        "gpt_5_3_codex": "q38-efficient-q2",
        "gpt_5_2": "q38-unsloth-iq3xxs"
    });
    let caps = json!({
        "q38-dt-iq3xxs": {"context_window": 131072, "display_name": "Qwen3.8 DT-IQ3 MTP3 128K"},
        "q38-dt-iq2s": {"context_window": 131072, "display_name": "Qwen3.8 DT-IQ2 MTP2 128K"},
        "q38-gsq-iq3s": {"context_window": 131072, "display_name": "Qwen3.8 GSQ IQ3S Ngram 128K"},
        "q38-efficient-q2": {"context_window": 131072, "display_name": "Qwen3.8 Efficient Q2 Ngram 128K"},
        "q38-unsloth-iq3xxs": {"context_window": 131072, "display_name": "Qwen3.8 Unsloth IQ3 Vanilla 128K"},
        "q36-35b-a3b": {"context_window": 131072, "display_name": "Qwen3.6 35B-A3B MoE 128K"}
    });

    let models = catalog_models_for_provider_with_display_names(
        "Sub2API Local Gateway",
        "q36-35b-a3b",
        false,
        Some(&mappings),
        Some(&caps),
        None,
        None,
        false,
    );

    assert_eq!(models.len(), 6, "five Codex slots + distinct default must produce six choices");
    assert!(models.iter().all(|m| m.context_window == 131072));

    let primary = models.iter().find(|m| m.slug == "gpt-5.5").expect("primary gpt-5.5 slot");
    assert_eq!(primary.display_name, "Qwen3.8 DT-IQ3 MTP3 128K");

    let sixth = models.iter().find(|m| m.slug == "q36-35b-a3b").expect("raw default sixth model");
    assert_eq!(sixth.display_name, "Qwen3.6 35B-A3B MoE 128K");
    assert_eq!(sixth.context_window, 131072);
}
'@
        Write-Utf8NoBom $testPath ($test.TrimStart() + "`n")
    }

    # Validate JSON before touching formatter/build.
    Get-Content -Raw $presetPath | ConvertFrom-Json | Out-Null

    Write-Host 'r70 local source patch applied.' -ForegroundColor Green
    & git diff --stat

    if ($RunChecks) {
        Write-Host 'Running local focused checks...' -ForegroundColor Cyan
        & cargo fmt --all
        if ($LASTEXITCODE -ne 0) { throw 'cargo fmt failed' }

        & cargo test -p codex-app-transfer-registry presets_count_matches_python
        if ($LASTEXITCODE -ne 0) { throw 'registry preset test failed' }

        & cargo test -p codex-app-transfer-codex-integration --test r70_local_gateway_catalog
        if ($LASTEXITCODE -ne 0) { throw 'r70 catalog regression test failed' }

        & cargo check -p codex-app-transfer-codex-integration -p codex-app-transfer-registry
        if ($LASTEXITCODE -ne 0) { throw 'focused cargo check failed' }

        Write-Host 'r70 focused checks PASS.' -ForegroundColor Green
    } else {
        Write-Host 'Patch only. Re-run with -Apply -RunChecks (idempotent) for focused local checks.'
    }
}
finally {
    Pop-Location
}
