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


def insert_after_once(text: str, anchor: str, addition: str, marker: str, label: str) -> str:
    if marker in text:
        print(f"[ok] {label}: already applied")
        return text
    if anchor not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(anchor, anchor + addition, 1)


# Keep these behaviors in the thin overlay rather than changing upstream's normal
# provider policy. The Sub2API Grok compat provider is a transparent mixed-model
# Responses wire shim: it must not silently take ownership of unrelated Codex user
# preferences merely because traffic is routed through Transfer.
path = "src-tauri/src/admin/services/desktop/snapshot.rs"
text = read(path)

# r6 first-install or migration from pristine upstream.
if "pub preserve_external_model_catalog: bool," not in text:
    text = replace_once(
        text,
        '''    pub is_qoder: bool,\n}''',
        '''    pub is_qoder: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep an existing external Codex model catalog.\n    pub preserve_external_model_catalog: bool,\n}''',
        "DesktopConfigTarget preserve external catalog flag",
    )

text = insert_after_once(
    text,
    '''    pub preserve_external_model_catalog: bool,\n''',
    '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: when the Transfer network-access toggle is off,\n    /// preserve the user's existing sandbox_mode / approval_policy / workspace-write network setting.\n    pub preserve_user_sandbox_policy: bool,\n''',
    "pub preserve_user_sandbox_policy: bool,",
    "DesktopConfigTarget preserve sandbox policy flag",
)

# The same explicit provider switch drives both preservation rules.
if "preserve_external_model_catalog: api_format_lower" not in text:
    text = replace_once(
        text,
        '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n    }''',
        '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n        // CAS-SUB2API-GROK-COMPAT-HOOK: this provider is a wire shim, not a model-catalog owner.\n        preserve_external_model_catalog: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n    }''',
        "derive preserve external catalog from compat provider",
    )
text = insert_after_once(
    text,
    '''                .and_then(Value::as_bool)\n                .unwrap_or(false),\n''',
    '''        preserve_user_sandbox_policy: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n''',
    "preserve_user_sandbox_policy: api_format_lower",
    "derive preserve sandbox policy from compat provider",
)

if "preserve_external_model_catalog: target.preserve_external_model_catalog" not in text:
    text = replace_once(
        text,
        '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n        },''',
        '''            codex_network_access: target.codex_network_access,\n            preserve_chatgpt_auth,\n            // CAS-SUB2API-GROK-COMPAT-HOOK\n            preserve_external_model_catalog: target.preserve_external_model_catalog,\n        },''',
        "pass preserve external catalog into ApplyConfig",
    )
text = insert_after_once(
    text,
    '''            preserve_external_model_catalog: target.preserve_external_model_catalog,\n''',
    '''            preserve_user_sandbox_policy: target.preserve_user_sandbox_policy,\n''',
    "preserve_user_sandbox_policy: target.preserve_user_sandbox_policy",
    "pass preserve sandbox policy into ApplyConfig",
)
write(path, text)

path = "crates/codex_integration/src/apply.rs"
text = read(path)
if "pub preserve_external_model_catalog: bool," not in text:
    text = replace_once(
        text,
        '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n}''',
        '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: do not replace/remove a user-owned\n    /// `model_catalog_json` while this provider is only acting as a wire shim.\n    #[serde(default)]\n    pub preserve_external_model_catalog: bool,\n}''',
        "ApplyConfig preserve external catalog flag",
    )
text = insert_after_once(
    text,
    '''    pub preserve_external_model_catalog: bool,\n''',
    '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: do not erase the user's sandbox policy when\n    /// the Transfer-specific network-access override is disabled.\n    #[serde(default)]\n    pub preserve_user_sandbox_policy: bool,\n''',
    "pub preserve_user_sandbox_policy: bool,",
    "ApplyConfig preserve sandbox policy flag",
)

# Upstream behavior for codexNetworkAccess=false is to delete sandbox_mode and
# approval_policy. For this compat provider that is unnecessarily destructive: the
# user's pre-existing workspace-write/on-request policy should remain authoritative.
text = replace_once(
    text,
    '''    } else {\n        sync_root_value(&paths.config_toml, "sandbox_mode", None)?;\n        sync_root_value(&paths.config_toml, "approval_policy", None)?;\n        sync_table_field(\n            &paths.config_toml,\n            "sandbox_workspace_write",\n            "network_access",\n            None,\n        )?;\n    }\n\n    // 3. config.toml: model_context_window''',
    '''    } else if !cfg.preserve_user_sandbox_policy {\n        sync_root_value(&paths.config_toml, "sandbox_mode", None)?;\n        sync_root_value(&paths.config_toml, "approval_policy", None)?;\n        sync_table_field(\n            &paths.config_toml,\n            "sandbox_workspace_write",\n            "network_access",\n            None,\n        )?;\n    }\n\n    // 3. config.toml: model_context_window''',
    "preserve existing sandbox policy when compat network override is off",
)

anchor = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n    if models.is_empty() {'''
replacement = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n\n    // CAS-SUB2API-GROK-COMPAT-HOOK: the compat provider is intentionally a\n    // transparent mixed-model Responses wire shim. If the user already points\n    // Codex at an external catalog, preserve that exact path and its contents.\n    // Do not confuse Transfer's own generated catalog with an external one.\n    let preserve_external_model_catalog = if cfg.preserve_external_model_catalog {\n        let transfer_catalog = paths\n            .model_catalog_json\n            .to_string_lossy()\n            .replace('\\\\', "/")\n            .to_ascii_lowercase();\n        std::fs::read_to_string(&paths.config_toml)\n            .ok()\n            .and_then(|content| {\n                content\n                    .lines()\n                    .take_while(|line| !line.trim_start().starts_with('['))\n                    .find_map(|line| {\n                        crate::residual::parse_root_string_value(line.trim_start(), CODEX_MODEL_CATALOG_KEY)\n                    })\n            })\n            .is_some_and(|configured| {\n                let configured = configured\n                    .replace('\\\\', "/")\n                    .to_ascii_lowercase();\n                !configured.trim().is_empty() && configured != transfer_catalog\n            })\n    } else {\n        false\n    };\n\n    if preserve_external_model_catalog {\n        // Leave both model_catalog_json and model_context_window untouched. The\n        // external catalog is authoritative and may carry per-model windows.\n    } else if models.is_empty() {'''
if "let preserve_external_model_catalog = if cfg.preserve_external_model_catalog" not in text:
    text = replace_once(text, anchor, replacement, "preserve user model catalog before provider catalog policy")

text = replace_once(
    text,
    '''        model_catalog_json_set: !models.is_empty(),''',
    '''        model_catalog_json_set: preserve_external_model_catalog || !models.is_empty(),''',
    "ApplyResult catalog state",
)
write(path, text)
