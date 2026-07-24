from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


# Keep this behavior in the thin overlay rather than changing upstream's normal
# provider/catalog policy. When the explicit Sub2API Grok compat switch is on,
# a user-supplied model_catalog_json (for example a Codex Desktop catalog with
# grok-4.5 added) is authoritative and must survive Transfer apply/restart.
path = "src-tauri/src/admin/services/desktop/snapshot.rs"
text = read(path)
text = replace_once(
    text,
    '''    pub is_qoder: bool,\n}''',
    '''    pub is_qoder: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep an existing external Codex model catalog.\n    pub preserve_external_model_catalog: bool,\n}''',
    "DesktopConfigTarget preserve external catalog flag",
)
text = replace_once(
    text,
    '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n    }''',
    '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n        // CAS-SUB2API-GROK-COMPAT-HOOK: this provider is a wire shim, not a model-catalog owner.\n        preserve_external_model_catalog: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n    }''',
    "derive preserve external catalog from compat provider",
)
text = replace_once(
    text,
    '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n        },''',
    '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n            // CAS-SUB2API-GROK-COMPAT-HOOK\n            preserve_external_model_catalog: target.preserve_external_model_catalog,\n        },''',
    "pass preserve external catalog into ApplyConfig",
)
write(path, text)

path = "crates/codex_integration/src/apply.rs"
text = read(path)
text = replace_once(
    text,
    '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n}''',
    '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: do not replace/remove a user-owned\n    /// `model_catalog_json` while this provider is only acting as a wire shim.\n    #[serde(default)]\n    pub preserve_external_model_catalog: bool,\n}''',
    "ApplyConfig preserve external catalog flag",
)
anchor = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n    if models.is_empty() {'''
replacement = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n\n    // CAS-SUB2API-GROK-COMPAT-HOOK: the compat provider is intentionally a\n    // transparent mixed-model Responses wire shim. If the user already points\n    // Codex at an external catalog, preserve that exact path and its contents.\n    // Do not confuse Transfer's own generated catalog with an external one.\n    let preserve_external_model_catalog = if cfg.preserve_external_model_catalog {\n        let transfer_catalog = paths\n            .model_catalog_json\n            .to_string_lossy()\n            .replace('\\\\', "/")\n            .to_ascii_lowercase();\n        std::fs::read_to_string(&paths.config_toml)\n            .ok()\n            .and_then(|content| {\n                content\n                    .lines()\n                    .take_while(|line| !line.trim_start().starts_with('['))\n                    .find_map(|line| {\n                        crate::residual::parse_root_string_value(line.trim_start(), CODEX_MODEL_CATALOG_KEY)\n                    })\n            })\n            .is_some_and(|configured| {\n                let configured = configured\n                    .replace('\\\\', "/")\n                    .to_ascii_lowercase();\n                !configured.trim().is_empty() && configured != transfer_catalog\n            })\n    } else {\n        false\n    };\n\n    if preserve_external_model_catalog {\n        // Leave both model_catalog_json and model_context_window untouched. The\n        // external catalog is authoritative and may carry per-model windows.\n    } else if models.is_empty() {'''
text = replace_once(text, anchor, replacement, "preserve user model catalog before provider catalog policy")
text = replace_once(
    text,
    '''        model_catalog_json_set: !models.is_empty(),''',
    '''        model_catalog_json_set: preserve_external_model_catalog || !models.is_empty(),''',
    "ApplyResult catalog state",
)
write(path, text)
