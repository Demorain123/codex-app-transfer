//! CAS-AUTO-REVIEW-R24: copy-on-write model-catalog overlay for per-model guardian overrides.
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
        raw
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
    let meta = codex_app_transfer_registry::load_raw_config(meta_path(paths))?;
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
            .ok_or_else(|| {
                CodexError::Other(format!("catalog entry for {main:?} is not an object"))
            })?;
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
        meta_path(paths),
        &json!({
            "source_path": source.to_string_lossy().replace('\\', "/"),
            "overrides": overrides
                .iter()
                .map(|(main, reviewer)| (main.clone(), Value::String(reviewer.clone())))
                .collect::<serde_json::Map<String, Value>>()
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

        assert_eq!(
            before,
            std::fs::read(&source).unwrap(),
            "source must stay byte-identical"
        );
        let overlay = codex_app_transfer_registry::load_raw_config(overlay_path(&paths)).unwrap();
        assert_eq!(overlay["top_level_custom"], "preserve-me");
        let grok = overlay["models"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["slug"] == "grok-4.5")
            .unwrap();
        assert_eq!(grok["auto_review_model_override"], "gpt-5.6-luna");
        assert_eq!(grok["custom_field"]["keep"], true);
        let luna = overlay["models"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["slug"] == "gpt-5.6-luna")
            .unwrap();
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

    #[test]
    fn reapply_rebuilds_shadow_from_updated_source() {
        let temp = tempfile::tempdir().unwrap();
        let paths = CodexPaths::from_home_dir(temp.path());
        let source = seed_source(&paths);
        let overrides = json!({"grok-4.5": "gpt-5.6-luna"});

        apply_auto_review_overrides(&paths, Some(&overrides)).unwrap();
        restore_source_if_overlay_active(&paths).unwrap();

        let mut updated = codex_app_transfer_registry::load_raw_config(&source).unwrap();
        updated["source_revision"] = Value::String("v2".into());
        codex_app_transfer_registry::save_raw_config(&source, &updated).unwrap();

        apply_auto_review_overrides(&paths, Some(&overrides)).unwrap();
        let overlay = codex_app_transfer_registry::load_raw_config(overlay_path(&paths)).unwrap();
        assert_eq!(overlay["source_revision"], "v2");
        assert_eq!(overlay["models"][0]["auto_review_model_override"], "gpt-5.6-luna");
    }
}
