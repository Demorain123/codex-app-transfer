#!/usr/bin/env python3
"""r24: per-model auto-review overrides with copy-on-write model catalog overlays.

Design constraints:
- Never modify a user-owned `model_catalog_json` source file.
- Unspecified models inherit their existing source-catalog metadata byte-for-byte at
  the semantic JSON level (all fields are cloned; only explicitly targeted entries
  get `auto_review_model_override` patched in the shadow copy).
- A configured reviewer slug must exist in the same final catalog; fail closed if not.
- If the current config points at our shadow from a previous run, restore the recorded
  source path before deciding whether the catalog is external/Transfer-owned.
- Rebuild the shadow from the current source on every Apply, so upstream/source catalog
  edits are picked up automatically.

This is a thin, replayable overlay intended to compose on top of the r23 branch.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-AUTO-REVIEW-R24"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"r24 anchor not found: {label}")
    return text.replace(old, new, 1)


RUST_MODULE = r'''//! CAS-AUTO-REVIEW-R24: copy-on-write model-catalog overlay for per-model guardian overrides.
//!
//! A user-supplied `model_catalog_json` is authoritative and is NEVER edited in place.
//! When overrides are configured, we clone the complete source JSON into a Transfer-owned
//! shadow catalog and only patch explicitly selected model entries. On the next Apply we
//! first restore the recorded source path, then rebuild from source, so source updates are
//! never hidden behind a stale shadow.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::model_catalog::CODEX_MODEL_CATALOG_KEY;
use crate::residual::parse_root_string_value;
use crate::toml_sync::{sync_root_value, toml_string_literal};
use crate::{CodexError, CodexPaths};

const OVERLAY_REL: &str = "model-catalog-overlays/auto-review/model-catalog.json";
const META_REL: &str = "model-catalog-overlays/auto-review/source.json";

fn overlay_path(paths: &CodexPaths) -> PathBuf {
    paths.app_home.join(OVERLAY_REL)
}

fn meta_path(paths: &CodexPaths) -> PathBuf {
    paths.app_home.join(META_REL)
}

fn normalized_path(path: &Path) -> String {
    let raw = path.to_string_lossy().replace('\\', "/");
    #[cfg(target_os = "windows")]
    {
        raw.to_ascii_lowercase()
    }
    #[cfg(not(target_os = "windows"))]
    {
        raw.into_owned()
    }
}

fn same_path(a: &Path, b: &Path) -> bool {
    normalized_path(a) == normalized_path(b)
}

fn configured_catalog_path(paths: &CodexPaths) -> Result<Option<PathBuf>, CodexError> {
    let content = match std::fs::read_to_string(&paths.config_toml) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(err.into()),
    };
    let configured = content
        .lines()
        .take_while(|line| !line.trim_start().starts_with('['))
        .find_map(|line| parse_root_string_value(line.trim_start(), CODEX_MODEL_CATALOG_KEY));
    Ok(configured.map(|raw| {
        let path = PathBuf::from(raw);
        if path.is_absolute() {
            path
        } else {
            paths.codex_home.join(path)
        }
    }))
}

fn source_from_meta(paths: &CodexPaths) -> Result<PathBuf, CodexError> {
    let meta = codex_app_transfer_registry::load_raw_config(&meta_path(paths))?;
    let source = meta
        .get("source_path")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| CodexError::Other("auto-review overlay metadata has no source_path".into()))?;
    Ok(PathBuf::from(source))
}

/// If a previous Apply left `model_catalog_json` pointing at our shadow, restore the
/// user/Transfer source before normal catalog ownership detection runs.
pub fn restore_source_if_overlay_active(paths: &CodexPaths) -> Result<(), CodexError> {
    let Some(current) = configured_catalog_path(paths)? else {
        return Ok(());
    };
    if !same_path(&current, &overlay_path(paths)) {
        return Ok(());
    }
    let source = source_from_meta(paths)?;
    if !source.is_file() {
        return Err(CodexError::Other(format!(
            "auto-review source catalog no longer exists: {}",
            source.display()
        )));
    }
    let literal = toml_string_literal(&source.to_string_lossy().replace('\\', "/"));
    sync_root_value(&paths.config_toml, CODEX_MODEL_CATALOG_KEY, Some(&literal))?;
    Ok(())
}

fn normalized_overrides(value: Option<&Value>) -> Result<Vec<(String, String)>, CodexError> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let Some(map) = value.as_object() else {
        return Err(CodexError::Other(
            "autoReviewModelOverrides must be a JSON object of main_model -> reviewer_model".into(),
        ));
    };
    let mut out = Vec::with_capacity(map.len());
    for (main, reviewer) in map {
        let main = main.trim();
        let reviewer = reviewer
            .as_str()
            .map(str::trim)
            .ok_or_else(|| {
                CodexError::Other(format!(
                    "autoReviewModelOverrides[{main:?}] must be a string model slug"
                ))
            })?;
        if main.is_empty() || reviewer.is_empty() {
            return Err(CodexError::Other(
                "autoReviewModelOverrides keys and reviewer slugs must be non-empty".into(),
            ));
        }
        out.push((main.to_owned(), reviewer.to_owned()));
    }
    Ok(out)
}

/// Build a Transfer-owned shadow catalog and point Codex at it. The source file is read-only.
pub fn apply_auto_review_overrides(
    paths: &CodexPaths,
    overrides: Option<&Value>,
) -> Result<bool, CodexError> {
    let overrides = normalized_overrides(overrides)?;
    if overrides.is_empty() {
        return Ok(false);
    }

    let source = configured_catalog_path(paths)?.ok_or_else(|| {
        CodexError::Other(
            "per-model Auto Review overrides require an active model_catalog_json".into(),
        )
    })?;
    if same_path(&source, &overlay_path(paths)) {
        return Err(CodexError::Other(
            "auto-review overlay was not restored to its source before rebuild".into(),
        ));
    }
    if !source.is_file() {
        return Err(CodexError::Other(format!(
            "model_catalog_json does not exist: {}",
            source.display()
        )));
    }

    let mut catalog = codex_app_transfer_registry::load_raw_config(&source)?;
    let models = catalog
        .get_mut("models")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| CodexError::Other("model_catalog_json has no models array".into()))?;

    let slugs: HashSet<String> = models
        .iter()
        .filter_map(|entry| entry.get("slug").and_then(Value::as_str))
        .map(str::to_owned)
        .collect();

    for (main, reviewer) in &overrides {
        if !slugs.contains(main) {
            return Err(CodexError::Other(format!(
                "Auto Review main model {main:?} is not present in model_catalog_json"
            )));
        }
        if !slugs.contains(reviewer) {
            return Err(CodexError::Other(format!(
                "Auto Review reviewer model {reviewer:?} is not present in model_catalog_json"
            )));
        }
    }

    for (main, reviewer) in &overrides {
        let entry = models
            .iter_mut()
            .find(|entry| entry.get("slug").and_then(Value::as_str) == Some(main.as_str()))
            .and_then(Value::as_object_mut)
            .ok_or_else(|| CodexError::Other(format!("catalog entry for {main:?} is not an object")))?;
        entry.insert(
            "auto_review_model_override".into(),
            Value::String(reviewer.clone()),
        );
    }

    let overlay = overlay_path(paths);
    if let Some(parent) = overlay.parent() {
        std::fs::create_dir_all(parent)?;
    }
    codex_app_transfer_registry::save_raw_config(&overlay, &catalog)?;
    codex_app_transfer_registry::save_raw_config(
        &meta_path(paths),
        &json!({
            "source_path": source.to_string_lossy().replace('\\', "/"),
            "overrides": overrides.iter().cloned().collect::<serde_json::Map<String, Value>>()
        }),
    )?;

    let literal = toml_string_literal(&overlay.to_string_lossy().replace('\\', "/"));
    sync_root_value(&paths.config_toml, CODEX_MODEL_CATALOG_KEY, Some(&literal))?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seed_source(paths: &CodexPaths) -> PathBuf {
        std::fs::create_dir_all(&paths.codex_home).unwrap();
        let source = paths.codex_home.join("custom-models.json");
        let source_json = json!({
            "models": [
                {
                    "slug": "grok-4.5",
                    "display_name": "Grok 4.5",
                    "custom_field": {"keep": true}
                },
                {
                    "slug": "gpt-5.6-luna",
                    "display_name": "GPT-5.6 Luna",
                    "auto_review_model_override": "codex-auto-review"
                }
            ],
            "top_level_custom": "preserve-me"
        });
        std::fs::write(
            &source,
            format!("{}\n", serde_json::to_string_pretty(&source_json).unwrap()),
        )
        .unwrap();
        let literal = toml_string_literal(&source.to_string_lossy().replace('\\', "/"));
        sync_root_value(&paths.config_toml, CODEX_MODEL_CATALOG_KEY, Some(&literal)).unwrap();
        source
    }

    #[test]
    fn external_catalog_is_never_modified_and_only_target_entry_is_overridden() {
        let temp = tempfile::tempdir().unwrap();
        let paths = CodexPaths::from_home_dir(temp.path());
        let source = seed_source(&paths);
        let before = std::fs::read(&source).unwrap();

        apply_auto_review_overrides(
            &paths,
            Some(&json!({"grok-4.5": "gpt-5.6-luna"})),
        )
        .unwrap();

        assert_eq!(before, std::fs::read(&source).unwrap(), "source must stay byte-identical");
        let overlay = codex_app_transfer_registry::load_raw_config(&overlay_path(&paths)).unwrap();
        assert_eq!(overlay["top_level_custom"], "preserve-me");
        let grok = overlay["models"]
            .as_array().unwrap().iter()
            .find(|m| m["slug"] == "grok-4.5").unwrap();
        assert_eq!(grok["auto_review_model_override"], "gpt-5.6-luna");
        assert_eq!(grok["custom_field"]["keep"], true);
        let luna = overlay["models"]
            .as_array().unwrap().iter()
            .find(|m| m["slug"] == "gpt-5.6-luna").unwrap();
        assert_eq!(luna["auto_review_model_override"], "codex-auto-review");
    }

    #[test]
    fn restore_returns_config_to_original_source_path() {
        let temp = tempfile::tempdir().unwrap();
        let paths = CodexPaths::from_home_dir(temp.path());
        let source = seed_source(&paths);
        apply_auto_review_overrides(
            &paths,
            Some(&json!({"grok-4.5": "gpt-5.6-luna"})),
        )
        .unwrap();
        restore_source_if_overlay_active(&paths).unwrap();
        assert_eq!(configured_catalog_path(&paths).unwrap().unwrap(), source);
    }

    #[test]
    fn missing_reviewer_fails_closed_before_switching_catalog_path() {
        let temp = tempfile::tempdir().unwrap();
        let paths = CodexPaths::from_home_dir(temp.path());
        let source = seed_source(&paths);
        let err = apply_auto_review_overrides(
            &paths,
            Some(&json!({"grok-4.5": "does-not-exist"})),
        )
        .unwrap_err();
        assert!(err.to_string().contains("not present"));
        assert_eq!(configured_catalog_path(&paths).unwrap().unwrap(), source);
    }
}
'''


def patch_lib() -> None:
    path = "crates/codex_integration/src/lib.rs"
    text = read(path)
    text = replace_once(text, "pub mod apply;\n", "pub mod apply;\npub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24\n", "lib module")
    write(path, text)


def patch_apply() -> None:
    path = "crates/codex_integration/src/apply.rs"
    text = read(path)
    text = replace_once(
        text,
        "    pub review_model_slot: Option<&'a str>,\n",
        "    pub review_model_slot: Option<&'a str>,\n"
        "    /// CAS-AUTO-REVIEW-R24: explicit main-model slug -> guardian reviewer slug.\n"
        "    /// Unspecified models inherit their source catalog metadata unchanged.\n"
        "    #[serde(skip)]\n"
        "    pub auto_review_model_overrides: Option<&'a serde_json::Value>,\n",
        "ApplyConfig field",
    )
    text = replace_once(
        text,
        "    snapshot_codex_state(\n",
        "    snapshot_codex_state(\n",
        "snapshot anchor",
    )
    # Install restore immediately after the snapshot call block, before config mutation.
    anchor = "    )?;\n\n    // 2. config.toml: openai_base_url\n"
    replacement = (
        "    )?;\n\n"
        "    // CAS-AUTO-REVIEW-R24: if the previous Apply pointed config.toml at our shadow,\n"
        "    // restore the recorded source first so external-catalog ownership detection sees the\n"
        "    // user's real catalog rather than mistaking the Transfer shadow for a new source.\n"
        "    crate::auto_review_overlay::restore_source_if_overlay_active(paths)?;\n\n"
        "    // 2. config.toml: openai_base_url\n"
    )
    text = replace_once(text, anchor, replacement, "restore before apply")
    auth_anchor = "\n    // 4. auth.json: auth_mode + OPENAI_API_KEY\n"
    auth_replacement = (
        "\n    // CAS-AUTO-REVIEW-R24: only after the normal catalog path has been resolved/generated,\n"
        "    // build a copy-on-write shadow if explicit per-model overrides exist.\n"
        "    crate::auto_review_overlay::apply_auto_review_overrides(\n"
        "        paths,\n"
        "        cfg.auto_review_model_overrides,\n"
        "    )?;\n"
        "\n    // 4. auth.json: auth_mode + OPENAI_API_KEY\n"
    )
    text = replace_once(text, auth_anchor, auth_replacement, "overlay after catalog")
    write(path, text)


def patch_provider_helpers() -> None:
    path = "src-tauri/src/admin/handlers/providers/mod.rs"
    text = read(path)
    anchor = '''pub(crate) fn provider_review_model_slot(provider: &Value) -> Option<String> {
    provider
        .get("reviewModelSlot")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}
'''
    addition = anchor + '''
/// CAS-AUTO-REVIEW-R24: provider-scoped per-model guardian overrides.
/// Object keys/values are catalog slugs. Missing/invalid shape is treated as empty here;
/// CRUD validation rejects malformed user input before it reaches this read path.
pub(crate) fn provider_auto_review_model_overrides(provider: &Value) -> Value {
    provider
        .get("autoReviewModelOverrides")
        .filter(|v| v.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}))
}
'''
    text = replace_once(text, anchor, addition, "provider helper")
    write(path, text)


def patch_snapshot() -> None:
    path = "src-tauri/src/admin/services/desktop/snapshot.rs"
    text = read(path)
    text = replace_once(
        text,
        "    provider_model_capabilities, provider_model_mappings, provider_review_model_slot,\n",
        "    provider_auto_review_model_overrides, provider_model_capabilities, provider_model_mappings,\n"
        "    provider_review_model_slot,\n",
        "snapshot imports",
    )
    text = replace_once(
        text,
        "    pub review_model_slot: Option<String>,\n",
        "    pub review_model_slot: Option<String>,\n"
        "    /// CAS-AUTO-REVIEW-R24: main-model slug -> reviewer slug.\n"
        "    pub auto_review_model_overrides: Value,\n",
        "target field",
    )
    text = replace_once(
        text,
        "        review_model_slot: provider_review_model_slot(provider),\n",
        "        review_model_slot: provider_review_model_slot(provider),\n"
        "        auto_review_model_overrides: provider_auto_review_model_overrides(provider),\n",
        "target init",
    )
    text = replace_once(
        text,
        "            review_model_slot: target.review_model_slot.as_deref(),\n",
        "            review_model_slot: target.review_model_slot.as_deref(),\n"
        "            auto_review_model_overrides: Some(&target.auto_review_model_overrides),\n",
        "ApplyConfig init",
    )
    write(path, text)


def patch_crud() -> None:
    path = "src-tauri/src/admin/handlers/providers/crud.rs"
    text = read(path)
    # validator after grok validator formatter
    anchor = '''fn format_grok_web_errs(errs: &[String]) -> String {
    let lines: Vec<String> = errs.iter().map(|e| format!("• {e}")).collect();
    format!("grokWeb 校验失败({} 项):\\n{}", errs.len(), lines.join("\\n"))
}
'''
    addition = anchor + '''
/// CAS-AUTO-REVIEW-R24: validate main-model -> reviewer-model slug map at save time.
fn validate_auto_review_model_overrides_input(value: &Value) -> Result<(), String> {
    if value.is_null() {
        return Ok(());
    }
    let Some(map) = value.as_object() else {
        return Err("autoReviewModelOverrides 必须是 JSON object".into());
    };
    if map.len() > 128 {
        return Err("autoReviewModelOverrides 条目过多(最多 128)".into());
    }
    for (main, reviewer) in map {
        if main.trim().is_empty() {
            return Err("autoReviewModelOverrides 不允许空模型名".into());
        }
        let reviewer = reviewer
            .as_str()
            .ok_or_else(|| format!("autoReviewModelOverrides[{main}] 必须是 string"))?;
        if reviewer.trim().is_empty() {
            return Err(format!("autoReviewModelOverrides[{main}] reviewer 不能为空"));
        }
    }
    Ok(())
}
'''
    text = replace_once(text, anchor, addition, "CRUD validator")
    text = replace_once(
        text,
        '''    #[serde(rename = "reviewModelSlot")]
    pub review_model_slot: Option<String>,
''',
        '''    #[serde(rename = "reviewModelSlot")]
    pub review_model_slot: Option<String>,
    /// CAS-AUTO-REVIEW-R24: per-model guardian override map; empty object clears.
    #[serde(rename = "autoReviewModelOverrides")]
    pub auto_review_model_overrides: Option<Value>,
''',
        "CRUD input field",
    )
    # validate in add before mutation
    add_anchor = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }

    // silent-failure-hunter H2 + chatgpt-codex P2:grokWeb 结构在 save 时校验,
'''
    add_repl = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }
    if let Some(overrides) = input.auto_review_model_overrides.as_ref() {
        if let Err(message) = validate_auto_review_model_overrides_input(overrides) {
            return err(StatusCode::BAD_REQUEST, message).into_response();
        }
    }

    // silent-failure-hunter H2 + chatgpt-codex P2:grokWeb 结构在 save 时校验,
'''
    text = replace_once(text, add_anchor, add_repl, "add validation")
    # persist on add after reviewModelSlot
    add_persist_anchor = '''        if let Some(slot) = input
            .review_model_slot
            .clone()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
        {
            new_provider.insert("reviewModelSlot".into(), Value::String(slot));
        }
'''
    add_persist_repl = add_persist_anchor + '''        if let Some(overrides) = input.auto_review_model_overrides.clone() {
            if overrides.as_object().is_some_and(|map| !map.is_empty()) {
                new_provider.insert("autoReviewModelOverrides".into(), overrides);
            }
        }
'''
    text = replace_once(text, add_persist_anchor, add_persist_repl, "add persistence")
    # update validation
    update_anchor = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }

    let result = with_config_write(|cfg| {
'''
    update_repl = '''    if let Some(gw) = input.grok_web.as_ref() {
        if let Err(errs) = validate_grok_web_input(gw) {
            return err(StatusCode::BAD_REQUEST, format_grok_web_errs(&errs)).into_response();
        }
    }
    if let Some(overrides) = input.auto_review_model_overrides.as_ref() {
        if let Err(message) = validate_auto_review_model_overrides_input(overrides) {
            return err(StatusCode::BAD_REQUEST, message).into_response();
        }
    }

    let result = with_config_write(|cfg| {
'''
    text = replace_once(text, update_anchor, update_repl, "update validation")
    update_persist_anchor = '''        if let Some(slot) = input.review_model_slot.clone() {
            let slot = slot.trim();
            if slot.is_empty() {
                updated.remove("reviewModelSlot");
            } else {
                updated.insert("reviewModelSlot".into(), Value::String(slot.to_string()));
            }
        }
'''
    update_persist_repl = update_persist_anchor + '''        if let Some(overrides) = input.auto_review_model_overrides.clone() {
            if overrides.as_object().is_some_and(|map| map.is_empty()) {
                updated.remove("autoReviewModelOverrides");
            } else {
                updated.insert("autoReviewModelOverrides".into(), overrides);
            }
        }
'''
    text = replace_once(text, update_persist_anchor, update_persist_repl, "update persistence")
    write(path, text)


def patch_types() -> None:
    path = "frontend/src/api/types.ts"
    text = read(path)
    text = replace_once(
        text,
        "  reviewModelSlot: string\n",
        "  reviewModelSlot: string\n  autoReviewModelOverrides?: Record<string, string>\n",
        "Provider type",
    )
    text = replace_once(
        text,
        "  reviewModelSlot?: string | null\n",
        "  reviewModelSlot?: string | null\n  autoReviewModelOverrides?: Record<string, string>\n",
        "ProviderPayload type",
    )
    write(path, text)


def patch_provider_form() -> None:
    path = "frontend/src/components/provider/ProviderFormModal.vue"
    text = read(path)
    text = replace_once(
        text,
        "  reviewModelSlot: '',\n",
        "  reviewModelSlot: '',\n  autoReviewModelOverrides: '', // CAS-AUTO-REVIEW-R24 JSON map: main slug -> reviewer slug\n",
        "form field",
    )
    # reset and preset: the same literal appears twice; replace all remaining exact anchors intentionally.
    text = text.replace("  form.reviewModelSlot = ''\n", "  form.reviewModelSlot = ''\n  form.autoReviewModelOverrides = ''\n")
    text = replace_once(
        text,
        "  form.reviewModelSlot = p.reviewModelSlot || ''\n",
        "  form.reviewModelSlot = p.reviewModelSlot || ''\n"
        "  form.autoReviewModelOverrides = stringifyIfAny(p.autoReviewModelOverrides)\n",
        "edit load",
    )
    # Parse the new JSON field alongside advanced objects.
    text = replace_once(
        text,
        "  let requestOptions: Record<string, unknown> | undefined\n",
        "  let requestOptions: Record<string, unknown> | undefined\n"
        "  let autoReviewModelOverrides: Record<string, unknown> | undefined\n",
        "save local",
    )
    text = replace_once(
        text,
        "    requestOptions = parseJsonObj(t('providerForm.requestOptions'), form.requestOptions)\n",
        "    requestOptions = parseJsonObj(t('providerForm.requestOptions'), form.requestOptions)\n"
        "    autoReviewModelOverrides = parseJsonObj(\n"
        "      t('providerForm.autoReviewModelOverrides'),\n"
        "      form.autoReviewModelOverrides,\n"
        "    )\n",
        "parse overrides",
    )
    text = replace_once(
        text,
        "    reviewModelSlot: form.reviewModelSlot.trim() || null,\n",
        "    reviewModelSlot: form.reviewModelSlot.trim() || null,\n"
        "    // Empty object is intentional on update: it clears a previously saved map.\n"
        "    autoReviewModelOverrides: (autoReviewModelOverrides || {}) as Record<string, string>,\n",
        "payload field",
    )
    ui_anchor = '''      <SettingsRow :title="t('providerForm.reviewModelSlot')">
        <AppInput v-model="form.reviewModelSlot" placeholder="default" />
      </SettingsRow>
'''
    ui_repl = ui_anchor + '''      <SettingsRow :title="t('providerForm.autoReviewModelOverrides')">
        <div class="pf__auto-review">
          <textarea
            v-model="form.autoReviewModelOverrides"
            class="pf__json"
            spellcheck="false"
            placeholder='{"grok-4.5":"gpt-5.6-luna"}'
          ></textarea>
          <small>{{ t('providerForm.autoReviewModelOverridesHint') }}</small>
        </div>
      </SettingsRow>
'''
    text = replace_once(text, ui_anchor, ui_repl, "UI row")
    write(path, text)


def patch_i18n() -> None:
    for path, label, hint in [
        (
            "frontend/src/i18n/zh.ts",
            "按模型覆盖 Auto Review",
            "JSON：主模型 slug → 审查模型 slug。未列出的模型完全继承当前 model_catalog_json；外部目录只读，Transfer 仅生成 shadow 副本。修改后需重启 Codex。",
        ),
        (
            "frontend/src/i18n/en.ts",
            "Per-model Auto Review overrides",
            "JSON: main model slug → reviewer slug. Unlisted models inherit the current model_catalog_json unchanged. External catalogs are read-only; Transfer only creates a shadow copy. Restart Codex after changing this.",
        ),
    ]:
        text = read(path)
        if '"providerForm.autoReviewModelOverrides"' not in text:
            anchor = '  "providerForm.reviewModelSlot"'
            idx = text.find(anchor)
            if idx < 0:
                # fallback: insert before a stable providerForm key
                anchor = '  "providerForm.advancedToggle"'
                idx = text.find(anchor)
            if idx < 0:
                raise SystemExit(f"r24 i18n anchor not found: {path}")
            text = text[:idx] + (
                f'  "providerForm.autoReviewModelOverrides": "{label}",\n'
                f'  "providerForm.autoReviewModelOverridesHint": "{hint}",\n'
            ) + text[idx:]
        write(path, text)


def main() -> None:
    module_path = ROOT / "crates/codex_integration/src/auto_review_overlay.rs"
    if not module_path.exists() or MARKER not in module_path.read_text(encoding="utf-8"):
        write("crates/codex_integration/src/auto_review_overlay.rs", RUST_MODULE)
    patch_lib()
    patch_apply()
    patch_provider_helpers()
    patch_snapshot()
    patch_crud()
    patch_types()
    patch_provider_form()
    patch_i18n()
    print("r24 per-model Auto Review catalog overlay applied")


if __name__ == "__main__":
    main()
