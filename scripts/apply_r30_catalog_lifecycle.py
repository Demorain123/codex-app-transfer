from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/snapshot.rs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r30 catalog lifecycle {label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


text = PATH.read_text(encoding="utf-8")

# CAS-R30-HYBRID-CATALOG-RESTORE-ONLY
# Hybrid Direct deliberately blocks full snapshot restore because CC Switch owns provider/auth.
# Auto Review is the one narrower Transfer-owned config mutation; restore only that pointer when the
# active config still points at our shadow. r24 helper is already fail-safe when CC Switch/user has
# moved the pointer elsewhere.
if "CAS-R30-HYBRID-CATALOG-RESTORE-ONLY" not in text:
    anchor = "\n/// [MOC-257 三态] 应用插件解锁三态:设活动 auth.json + 驱动 proxy 伪造 atomic + apply(relay/非relay)。\n"
    if text.count(anchor) != 1:
        raise SystemExit("r30 catalog lifecycle restore helper insertion anchor drifted")
    helper = r'''
/// CAS-R30-HYBRID-CATALOG-RESTORE-ONLY
/// Restore only Transfer's r24 Auto Review source pointer. This is safe under Hybrid Direct because
/// `restore_source_if_overlay_active` is a no-op unless config currently points to Transfer's exact
/// shadow path; it never replays provider/auth/base-URL snapshots.
pub fn restore_auto_review_source_catalog_only() -> Value {
    let paths = match CodexPaths::from_home_env() {
        Ok(paths) => paths,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "catalogOnly": true,
                "providerAuthMutated": false,
                "message": e.to_string(),
            })
        }
    };
    match restore_source_if_overlay_active(&paths) {
        Ok(restored) => json!({
            "attempted": true,
            "success": true,
            "catalogOnly": true,
            "sourceRestored": restored,
            "providerAuthMutated": false,
            "message": if restored {
                "Transfer Auto Review source catalog restored"
            } else {
                "Auto Review source restore not needed"
            },
        }),
        Err(e) => json!({
            "attempted": true,
            "success": false,
            "catalogOnly": true,
            "providerAuthMutated": false,
            "message": format!("restore Auto Review source catalog failed: {e}"),
        }),
    }
}
'''
    text = text.replace(anchor, "\n" + helper + anchor, 1)

# CAS-R30-HYBRID-CATALOG-REFRESH
# Every Hybrid Direct provider/gateway sync (including startup auto-apply and provider switch) must
# rebase the shadow on the current source catalog. This prevents a shadow generated in an earlier
# Transfer session from hiding a newer external catalog.
if "CAS-R30-HYBRID-CATALOG-REFRESH" not in text:
    old = '''        let port = read_proxy_port(&cfg);
        crate::codex_real_account::reset_applied_mode();
        codex_app_transfer_proxy::set_fake_account_mode(false);
        return match start_proxy_for_provider_if_needed(&state.proxy_manager, port, provider_id).await {
            Ok(started) => json!({
                "attempted": false,
                "success": true,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": started,
                "codexMutated": false,
                "provider": provider_id,
                "message": "Hybrid Direct gateway ready; CC Switch owns Codex provider/auth and official OAuth stays outside Transfer",
            }),
            Err(e) => json!({
                "attempted": false,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": false,
                "codexMutated": false,
                "provider": provider_id,
                "message": e,
            }),
        };'''
    new = '''        // CAS-R30-HYBRID-CATALOG-REFRESH: catalog is the only permitted Codex config
        // surface in Hybrid Direct. Restore/rebase the r24 shadow on every gateway sync so a
        // previous-session shadow never hides a newer external model catalog.
        let catalog_sync = sync_auto_review_catalog_only_for_provider(provider_id);
        let port = read_proxy_port(&cfg);
        crate::codex_real_account::reset_applied_mode();
        codex_app_transfer_proxy::set_fake_account_mode(false);
        return match start_proxy_for_provider_if_needed(&state.proxy_manager, port, provider_id).await {
            Ok(started) => json!({
                "attempted": false,
                "success": true,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": started,
                "codexMutated": false,
                "providerAuthMutated": false,
                "catalogSync": catalog_sync,
                "provider": provider_id,
                "message": "Hybrid Direct gateway ready; CC Switch owns Codex provider/auth and official OAuth stays outside Transfer",
            }),
            Err(e) => json!({
                "attempted": false,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": false,
                "codexMutated": false,
                "providerAuthMutated": false,
                "catalogSync": catalog_sync,
                "provider": provider_id,
                "message": e,
            }),
        };'''
    text = replace_once(text, old, new, "gateway catalog refresh")

# CAS-R30-HYBRID-CATALOG-EXIT-RESTORE
# r28 correctly blocks full restore under Hybrid Direct, but that must not leave Transfer's own
# shadow pointer behind forever. Restore only the r24 pointer before returning the r28 no-restore
# result; CC Switch-owned provider/auth/base URL remain untouched.
if "CAS-R30-HYBRID-CATALOG-EXIT-RESTORE" not in text:
    old = '''    if super::hybrid_direct::enabled_from_config(&cfg) {
        return json!({"attempted": false, "restored": false, "success": true, "reason": reason, "message": "Hybrid Direct: restore skipped; CC Switch owns Codex provider/auth"});
    }'''
    new = '''    if super::hybrid_direct::enabled_from_config(&cfg) {
        // CAS-R30-HYBRID-CATALOG-EXIT-RESTORE: full snapshot restore stays blocked, but remove our
        // own Auto Review shadow pointer when it is still active. The helper is exact-path gated.
        let catalog_restore = restore_auto_review_source_catalog_only();
        return json!({
            "attempted": false,
            "restored": false,
            "success": true,
            "reason": reason,
            "providerAuthMutated": false,
            "catalogRestore": catalog_restore,
            "message": "Hybrid Direct: provider/auth restore skipped; CC Switch owns them; Transfer Auto Review catalog pointer restored when applicable",
        });
    }'''
    text = replace_once(text, old, new, "Hybrid Direct exit catalog restore")

PATH.write_text(text, encoding="utf-8")

text = PATH.read_text(encoding="utf-8")
for marker in (
    "CAS-R30-HYBRID-CATALOG-RESTORE-ONLY",
    "CAS-R30-HYBRID-CATALOG-REFRESH",
    "CAS-R30-HYBRID-CATALOG-EXIT-RESTORE",
    "let catalog_sync = sync_auto_review_catalog_only_for_provider(provider_id);",
    "let catalog_restore = restore_auto_review_source_catalog_only();",
):
    if marker not in text:
        raise SystemExit(f"r30 catalog lifecycle missing marker: {marker}")

print("r30 Hybrid Direct Auto Review catalog lifecycle: PASS")
