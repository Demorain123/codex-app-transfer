from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")
    print(f"r30 patched {rel}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r30 {label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. Hybrid Direct owns the network/provider/auth boundary, but an explicit
#    Auto Review mapping still needs a safe way to rebuild r24's COW catalog.
#    Add a catalog-only service that is deliberately unable to call
#    apply_provider / rewrite auth / change provider/base URLs.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/services/desktop/snapshot.rs"
text = read(path)
if "CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY" not in text:
    text = replace_once(
        text,
        "use codex_app_transfer_codex_integration::{\n"
        "    apply_provider, ensure_file_store_mode, has_snapshot, has_stale_active_snapshot,\n"
        "    restore_codex_state, sync_mcp_credentials, ApplyConfig, CodexPaths,\n"
        "};",
        "use codex_app_transfer_codex_integration::{\n"
        "    apply_auto_review_overrides, apply_provider, ensure_file_store_mode, has_snapshot,\n"
        "    has_stale_active_snapshot, restore_codex_state, restore_source_if_overlay_active,\n"
        "    sync_mcp_credentials, ApplyConfig, CodexPaths,\n"
        "};",
        "catalog-only codex integration imports",
    )

    anchor = "\n/// [MOC-257 三态] 应用插件解锁三态:设活动 auth.json + 驱动 proxy 伪造 atomic + apply(relay/非relay)。\n"
    if text.count(anchor) != 1:
        raise SystemExit(f"r30 catalog-only insertion anchor: expected 1, found {text.count(anchor)}")
    function = r'''
/// CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY
///
/// Explicit Auto Review exception for Hybrid Direct. CC Switch remains the sole owner of
/// provider/auth/network routing; this path may only restore/rebuild r24's copy-on-write model
/// catalog and update the `model_catalog_json` pointer. It never starts/stops the proxy and never
/// calls `apply_provider`.
pub fn sync_auto_review_catalog_only_for_provider(expected_provider_id: &str) -> Value {
    let cfg = match load_registry() {
        Ok(cfg) => cfg,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_catalog_only",
                "catalogOnly": true,
                "providerAuthMutated": false,
                "message": e,
            })
        }
    };
    let Some(provider) = active_provider(&cfg) else {
        return json!({
            "attempted": false,
            "success": false,
            "mode": "hybrid_direct_catalog_only",
            "catalogOnly": true,
            "providerAuthMutated": false,
            "message": "no active provider",
        });
    };
    let active_id = provider.get("id").and_then(Value::as_str).unwrap_or("");
    if active_id != expected_provider_id {
        return json!({
            "attempted": false,
            "success": false,
            "mode": "hybrid_direct_catalog_only",
            "catalogOnly": true,
            "providerAuthMutated": false,
            "message": format!(
                "active provider changed during Auto Review save (expected {expected_provider_id}, now {active_id}); catalog not touched"
            ),
        });
    }

    let overrides = provider_auto_review_model_overrides(&provider);
    let override_count = overrides.as_object().map(|m| m.len()).unwrap_or(0);
    let paths = match CodexPaths::from_home_env() {
        Ok(paths) => paths,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_catalog_only",
                "catalogOnly": true,
                "providerAuthMutated": false,
                "message": e.to_string(),
            })
        }
    };

    // Always restore first. If the last mapping was removed, this is the operation that returns
    // Codex to the user's original/external catalog; apply_auto_review_overrides({}) then no-ops.
    if let Err(e) = restore_source_if_overlay_active(&paths) {
        return json!({
            "attempted": true,
            "success": false,
            "mode": "hybrid_direct_catalog_only",
            "catalogOnly": true,
            "providerAuthMutated": false,
            "message": format!("restore Auto Review source catalog failed: {e}"),
        });
    }
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {
        Ok(applied) => applied,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_catalog_only",
                "catalogOnly": true,
                "providerAuthMutated": false,
                "overrideCount": override_count,
                "message": format!("apply Auto Review catalog overlay failed: {e}"),
            })
        }
    };

    json!({
        "attempted": true,
        "success": true,
        "mode": "hybrid_direct_catalog_only",
        "catalogOnly": true,
        "catalogApplied": catalog_applied,
        "overrideCount": override_count,
        "providerAuthMutated": false,
        "codexConfigScope": "model_catalog_json_only",
        "message": if catalog_applied {
            "Hybrid Direct: Auto Review shadow catalog rebuilt; provider/auth/network remain CC Switch-owned"
        } else {
            "Hybrid Direct: Auto Review override cleared/defaulted; source catalog restored when needed"
        },
    })
}
'''
    text = text.replace(anchor, "\n" + function + anchor, 1)
    write(path, text)
else:
    print("r30 catalog-only service already materialized")


# ---------------------------------------------------------------------------
# 2. r29's provider-save path expected a normal desktop sync. In Hybrid Direct,
#    r28 intentionally turns that sync into gateway-only behavior, which would
#    falsely report success without rebuilding the Auto Review catalog. Select
#    the catalog-only path explicitly, and fix r29's handler import at the same
#    time so full Windows compilation does not depend on a nonexistent re-export.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/handlers/providers/crud.rs"
text = read(path)
if "CAS-R30-HYBRID-AUTO-REVIEW-DISPATCH" not in text:
    text = replace_once(
        text,
        "use super::super::desktop::{switch_provider_and_sync, sync_desktop_for_active_provider};",
        "use super::super::desktop::switch_provider_and_sync;\n"
        "use crate::admin::services::desktop::snapshot::{\n"
        "    sync_auto_review_catalog_only_for_provider, sync_desktop_for_active_provider,\n"
        "};",
        "r29 desktop sync import",
    )
    text = replace_once(
        text,
        "    if auto_review_changed && edited_active_provider {\n"
        "        let desktop_sync = sync_desktop_for_active_provider(&state).await;",
        "    if auto_review_changed && edited_active_provider {\n"
        "        // CAS-R30-HYBRID-AUTO-REVIEW-DISPATCH: Hybrid Direct must not call the normal\n"
        "        // provider/auth apply path. It gets one explicit catalog-only exception.\n"
        "        let desktop_sync = if crate::admin::services::desktop::hybrid_direct::enabled() {\n"
        "            sync_auto_review_catalog_only_for_provider(&id)\n"
        "        } else {\n"
        "            sync_desktop_for_active_provider(&state).await\n"
        "        };",
        "Hybrid Direct Auto Review dispatch",
    )
    write(path, text)
else:
    print("r30 Hybrid Direct Auto Review dispatch already materialized")


# Final semantic gates.
snapshot = read("src-tauri/src/admin/services/desktop/snapshot.rs")
crud = read("src-tauri/src/admin/handlers/providers/crud.rs")
for marker in (
    "CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY",
    "sync_auto_review_catalog_only_for_provider",
    "restore_source_if_overlay_active(&paths)",
    "apply_auto_review_overrides(&paths, Some(&overrides))",
    '"codexConfigScope": "model_catalog_json_only"',
):
    if marker not in snapshot:
        raise SystemExit(f"r30 catalog-only marker missing: {marker}")
for marker in (
    "CAS-R30-HYBRID-AUTO-REVIEW-DISPATCH",
    "hybrid_direct::enabled()",
    "sync_auto_review_catalog_only_for_provider(&id)",
    "sync_desktop_for_active_provider(&state).await",
):
    if marker not in crud:
        raise SystemExit(f"r30 provider dispatch marker missing: {marker}")

print("r30 Hybrid Direct × Auto Review catalog-only integration: PASS")
