from pathlib import Path
import runpy

LEGACY_PATCHER = Path("scripts/apply_sub2api_grok_compat_ui.py")


def contains(path: str, *needles: str) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


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


def overlay_complete() -> bool:
    """Semantic, formatting-insensitive completeness check for the UI/backend overlay."""
    return all(
        [
            Path("frontend/src/components/provider/Sub2ApiGrokCompatControls.vue").is_file(),
            contains(
                "src-tauri/src/admin/handlers/providers/crud.rs",
                "pub sub2api_grok_compat: Option<bool>",
                "pub sub2api_grok_free_cache_compat: Option<bool>",
                '"sub2apiGrokCompat".into()',
                '"sub2apiGrokFreeCacheCompat".into()',
                "input.sub2api_grok_compat",
                "input.sub2api_grok_free_cache_compat",
            ),
            contains(
                "frontend/src/api/types.ts",
                "sub2apiGrokCompat?: boolean",
                "sub2apiGrokFreeCacheCompat?: boolean",
            ),
            contains(
                "frontend/src/api/providers.ts",
                "sub2apiGrokCompat: !!provider.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!provider.sub2apiGrokFreeCacheCompat",
                "sub2apiGrokCompat: !!payload.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!payload.sub2apiGrokFreeCacheCompat",
            ),
            contains(
                "frontend/src/components/provider/ProviderFormModal.vue",
                "Sub2ApiGrokCompatControls",
                'v-model:enabled="form.sub2apiGrokCompat"',
                'v-model:cache-enabled="form.sub2apiGrokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/layout/TopTabBar.vue",
                "compat-build-badge",
                "compat.buildBadge",
            ),
            contains(
                "frontend/src/layout/AppLayout.vue",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            contains(
                "src-tauri/tauri.conf.json",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            contains(
                "frontend/src/i18n/zh.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/i18n/en.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
        ]
    )


def apply_codex_config_preservation() -> None:
    """Install compat-only guards around upstream Codex config ownership.

    The Sub2API Grok provider is a mixed-model Responses wire shim. It must not
    silently replace a user-owned model catalog or erase a user-owned sandbox
    policy. The only routing keys that must change are handled by upstream
    apply_provider (openai_base_url/model_provider and optional relay keys).
    """
    path = Path("src-tauri/src/admin/services/desktop/snapshot.rs")
    text = path.read_text(encoding="utf-8")

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
        '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: when Transfer network access is off,\n    /// keep the user's existing sandbox/approval policy unchanged.\n    pub preserve_user_sandbox_policy: bool,\n''',
        "pub preserve_user_sandbox_policy: bool,",
        "DesktopConfigTarget preserve sandbox policy flag",
    )

    if "preserve_external_model_catalog: api_format_lower" not in text:
        text = replace_once(
            text,
            '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n    }''',
            '''        review_model_slot: provider_review_model_slot(provider),\n        is_qoder: provider_is_qoder(provider),\n        // CAS-SUB2API-GROK-COMPAT-HOOK: wire shim, not a model-catalog owner.\n        preserve_external_model_catalog: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n    }''',
            "derive preserve external catalog from compat provider",
        )
    # Anchor on the just-installed compat field, not a generic bool expression.
    text = insert_after_once(
        text,
        '''        preserve_external_model_catalog: api_format_lower == "responses"\n            && provider\n                .get("sub2apiGrokCompat")\n                .and_then(Value::as_bool)\n                .unwrap_or(false),\n''',
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
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")

    path = Path("crates/codex_integration/src/apply.rs")
    text = path.read_text(encoding="utf-8")
    if "pub preserve_external_model_catalog: bool," not in text:
        text = replace_once(
            text,
            '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n}''',
            '''    #[serde(default)]\n    pub preserve_chatgpt_auth: bool,\n    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep user-owned model_catalog_json.\n    #[serde(default)]\n    pub preserve_external_model_catalog: bool,\n}''',
            "ApplyConfig preserve external catalog flag",
        )
    text = insert_after_once(
        text,
        '''    pub preserve_external_model_catalog: bool,\n''',
        '''    /// CAS-SUB2API-GROK-COMPAT-HOOK: keep user sandbox/approval policy when\n    /// the Transfer-specific network-access override is disabled.\n    #[serde(default)]\n    pub preserve_user_sandbox_policy: bool,\n''',
        "pub preserve_user_sandbox_policy: bool,",
        "ApplyConfig preserve sandbox policy flag",
    )

    text = replace_once(
        text,
        '''    } else {\n        sync_root_value(&paths.config_toml, "sandbox_mode", None)?;\n        sync_root_value(&paths.config_toml, "approval_policy", None)?;\n        sync_table_field(\n            &paths.config_toml,\n            "sandbox_workspace_write",\n            "network_access",\n            None,\n        )?;\n    }\n\n    // 3. config.toml: model_context_window''',
        '''    } else if !cfg.preserve_user_sandbox_policy {\n        sync_root_value(&paths.config_toml, "sandbox_mode", None)?;\n        sync_root_value(&paths.config_toml, "approval_policy", None)?;\n        sync_table_field(\n            &paths.config_toml,\n            "sandbox_workspace_write",\n            "network_access",\n            None,\n        )?;\n    }\n\n    // 3. config.toml: model_context_window''',
        "preserve existing sandbox policy when compat network override is off",
    )

    anchor = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n    if models.is_empty() {'''
    replacement = '''    let models = catalog_models_for_provider_with_display_names(\n        cfg.provider_name,\n        cfg.default_model,\n        cfg.supports_1m,\n        cfg.model_mappings,\n        cfg.model_capabilities,\n        cfg.model_display_names,\n        cfg.review_model_slot,\n        cfg.is_qoder,\n    );\n\n    // CAS-SUB2API-GROK-COMPAT-HOOK: preserve a user-owned external catalog.\n    let preserve_external_model_catalog = if cfg.preserve_external_model_catalog {\n        let transfer_catalog = paths\n            .model_catalog_json\n            .to_string_lossy()\n            .replace('\\\\', "/")\n            .to_ascii_lowercase();\n        std::fs::read_to_string(&paths.config_toml)\n            .ok()\n            .and_then(|content| {\n                content\n                    .lines()\n                    .take_while(|line| !line.trim_start().starts_with('['))\n                    .find_map(|line| {\n                        crate::residual::parse_root_string_value(line.trim_start(), CODEX_MODEL_CATALOG_KEY)\n                    })\n            })\n            .is_some_and(|configured| {\n                let configured = configured.replace('\\\\', "/").to_ascii_lowercase();\n                !configured.trim().is_empty() && configured != transfer_catalog\n            })\n    } else {\n        false\n    };\n\n    if preserve_external_model_catalog {\n        // External catalog is authoritative: keep its path and model_context_window.\n    } else if models.is_empty() {'''
    if "let preserve_external_model_catalog = if cfg.preserve_external_model_catalog" not in text:
        text = replace_once(
            text,
            anchor,
            replacement,
            "preserve user model catalog before provider catalog policy",
        )

    if "model_catalog_json_set: preserve_external_model_catalog || !models.is_empty()," not in text:
        text = replace_once(
            text,
            '''        model_catalog_json_set: !models.is_empty(),''',
            '''        model_catalog_json_set: preserve_external_model_catalog || !models.is_empty(),''',
            "ApplyResult catalog state",
        )
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def config_preservation_complete() -> bool:
    return all(
        [
            contains(
                "src-tauri/src/admin/services/desktop/snapshot.rs",
                "preserve_external_model_catalog",
                "preserve_user_sandbox_policy",
                'get("sub2apiGrokCompat")',
            ),
            contains(
                "crates/codex_integration/src/apply.rs",
                "pub preserve_external_model_catalog: bool",
                "pub preserve_user_sandbox_policy: bool",
                "if preserve_external_model_catalog {",
                "else if !cfg.preserve_user_sandbox_policy",
            ),
        ]
    )


if overlay_complete():
    print("[ok] Sub2API Grok UI/backend overlay already complete; no-op")
else:
    if not LEGACY_PATCHER.is_file():
        raise SystemExit(f"missing first-install UI patcher: {LEGACY_PATCHER}")
    print("[info] UI/backend overlay incomplete; running first-install patcher")
    runpy.run_path(str(LEGACY_PATCHER), run_name="__main__")
    if not overlay_complete():
        raise SystemExit(
            "UI/backend patcher exited without producing a complete overlay; "
            "upstream source likely changed and needs a reviewed anchor update"
        )
    print("[ok] Sub2API Grok UI/backend overlay installed and verified")

apply_codex_config_preservation()
if not config_preservation_complete():
    raise SystemExit("Codex config preservation overlay did not produce the required invariants")
print("[ok] Codex external catalog + sandbox policy preservation installed and verified")
