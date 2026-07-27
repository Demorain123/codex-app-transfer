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
# Patch only the Hybrid Direct early-return region. The r28 source exists in both pre-rustfmt and
# rustfmt-normalized forms; anchoring on `let port` + the JSON field pair is stable in both.
if "CAS-R30-HYBRID-CATALOG-REFRESH" not in text:
    sync_start = text.find("async fn sync_desktop_for_active_provider_impl")
    sync_end = text.find("    let target_result = with_config_write", sync_start)
    if sync_start < 0 or sync_end <= sync_start:
        raise SystemExit("r30 catalog lifecycle could not isolate Hybrid Direct gateway sync")
    region = text[sync_start:sync_end]

    port_anchor = "        let port = read_proxy_port(&cfg);"
    if region.count(port_anchor) != 1:
        raise SystemExit(
            f"r30 catalog lifecycle gateway port anchor expected one in Hybrid Direct region, found {region.count(port_anchor)}"
        )
    region = region.replace(
        port_anchor,
        "        // CAS-R30-HYBRID-CATALOG-REFRESH: catalog is the only permitted Codex config\n"
        "        // surface in Hybrid Direct. Restore/rebase the r24 shadow on every gateway sync so a\n"
        "        // previous-session shadow never hides a newer external model catalog.\n"
        "        let catalog_sync = sync_auto_review_catalog_only_for_provider(provider_id);\n"
        + port_anchor,
        1,
    )

    field_pair = '                "codexMutated": false,\n                "provider": provider_id,'
    count = region.count(field_pair)
    if count != 2:
        raise SystemExit(
            f"r30 catalog lifecycle expected two gateway provider JSON branches, found {count}"
        )
    region = region.replace(
        field_pair,
        '                "codexMutated": false,\n'
        '                "providerAuthMutated": false,\n'
        '                "catalogSync": catalog_sync,\n'
        '                "provider": provider_id,',
    )
    text = text[:sync_start] + region + text[sync_end:]

# CAS-R30-HYBRID-CATALOG-EXIT-RESTORE
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
