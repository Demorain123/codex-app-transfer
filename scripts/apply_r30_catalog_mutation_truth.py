from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/admin/services/desktop/snapshot.rs"
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r30 catalog mutation truth {label}: expected one anchor, found {count}")
    text = text.replace(old, new, 1)


if "CAS-R30-CATALOG-MUTATION-TRUTH" not in text:
    replace_once(
        '''    // Always restore first. If the last mapping was removed, this is the operation that returns
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
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {''',
        '''    // CAS-R30-CATALOG-MUTATION-TRUTH: restoring an old Transfer shadow pointer is itself a
    // Codex config mutation, even when the new override map is empty. Track it separately from
    // provider/auth ownership so diagnostics never claim zero mutation when model_catalog_json moved.
    let source_restored = match restore_source_if_overlay_active(&paths) {
        Ok(restored) => restored,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_catalog_only",
                "catalogOnly": true,
                "providerAuthMutated": false,
                "catalogMutated": false,
                "message": format!("restore Auto Review source catalog failed: {e}"),
            });
        }
    };
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {''',
        "source restore mutation tracking",
    )
    replace_once(
        '''                "providerAuthMutated": false,
                "overrideCount": override_count,
                "message": format!("apply Auto Review catalog overlay failed: {e}"),''',
        '''                "providerAuthMutated": false,
                "sourceRestored": source_restored,
                "catalogMutated": source_restored,
                "overrideCount": override_count,
                "message": format!("apply Auto Review catalog overlay failed: {e}"),''',
        "apply failure mutation report",
    )
    replace_once(
        '''        "catalogApplied": catalog_applied,
        "overrideCount": override_count,
        "providerAuthMutated": false,
        "codexConfigScope": "model_catalog_json_only",''',
        '''        "catalogApplied": catalog_applied,
        "sourceRestored": source_restored,
        "catalogMutated": source_restored || catalog_applied,
        "overrideCount": override_count,
        "providerAuthMutated": false,
        "codexConfigScope": "model_catalog_json_only",''',
        "catalog success mutation report",
    )

    # Restore-only success explicitly reports whether the pointer changed. Error paths omit the field;
    # all consumers use `unwrap_or(false)`, so an error can never be mistaken for a successful mutation.
    replace_once(
        '''            "catalogOnly": true,
            "sourceRestored": restored,
            "providerAuthMutated": false,
            "message": if restored {''',
        '''            "catalogOnly": true,
            "sourceRestored": restored,
            "catalogMutated": restored,
            "providerAuthMutated": false,
            "message": if restored {''',
        "restore-only success mutation report",
    )

    replace_once(
        '''        let catalog_sync = sync_auto_review_catalog_only_for_provider(provider_id);
        let port = read_proxy_port(&cfg);''',
        '''        let catalog_sync = sync_auto_review_catalog_only_for_provider(provider_id);
        let catalog_mutated = catalog_sync
            .get("catalogMutated")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let port = read_proxy_port(&cfg);''',
        "gateway mutation extraction",
    )

    # Restrict the telemetry replacement to the Hybrid Direct early-return branch, rather than
    # replacing unrelated `codexMutated=false` fields later in the file.
    marker_pos = text.index("CAS-R30-HYBRID-CATALOG-REFRESH")
    branch_end = text.index("    let target_result = with_config_write", marker_pos)
    gateway = text[marker_pos:branch_end]
    count = gateway.count('"codexMutated": false,')
    if count != 2:
        raise SystemExit(f"r30 catalog mutation truth expected exactly two gateway codexMutated=false fields, found {count}")
    gateway = gateway.replace('"codexMutated": false,', '"codexMutated": catalog_mutated,')
    text = text[:marker_pos] + gateway + text[branch_end:]

PATH.write_text(text, encoding="utf-8")

text = PATH.read_text(encoding="utf-8")
for required in (
    "CAS-R30-CATALOG-MUTATION-TRUTH",
    "let source_restored = match restore_source_if_overlay_active(&paths)",
    '"catalogMutated": source_restored || catalog_applied',
    '"catalogMutated": restored',
    "let catalog_mutated = catalog_sync",
    '"codexMutated": catalog_mutated',
):
    if required not in text:
        raise SystemExit(f"r30 catalog mutation truth missing: {required}")

print("r30 catalog mutation telemetry truth: PASS")
