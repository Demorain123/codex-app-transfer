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


# ---------------------------------------------------------------------------
# Provider-specific catalog-only apply.
# restore_source_if_overlay_active() returns Result<(), _>, so mutation truth
# must come from the read-only r30 state probe *before* restore.
# ---------------------------------------------------------------------------
legacy_bad = '''    // CAS-R30-CATALOG-MUTATION-TRUTH: restoring an old Transfer shadow pointer is itself a
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
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {'''

fresh_old = '''    // Always restore first. If the last mapping was removed, this is the operation that returns
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
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {'''

correct = '''    // CAS-R30-CATALOG-MUTATION-TRUTH: restore_source_if_overlay_active returns (), so detect
    // whether our exact shadow is active *before* restore. The probe reuses r24's path normalization.
    let source_restored = match auto_review_overlay_active(&paths) {
        Ok(active) => active,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_catalog_only",
                "catalogOnly": true,
                "providerAuthMutated": false,
                "catalogMutated": false,
                "message": format!("inspect Auto Review catalog state failed: {e}"),
            });
        }
    };
    if let Err(e) = restore_source_if_overlay_active(&paths) {
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
    let catalog_applied = match apply_auto_review_overrides(&paths, Some(&overrides)) {'''

if legacy_bad in text:
    text = text.replace(legacy_bad, correct, 1)
elif fresh_old in text:
    text = text.replace(fresh_old, correct, 1)
elif correct not in text:
    raise SystemExit("r30 catalog mutation truth provider restore block not recognized")

# Add success/failure mutation fields if this is a fresh materialization that has not yet received them.
if '"sourceRestored": source_restored,' not in text:
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
if '"catalogMutated": source_restored || catalog_applied,' not in text:
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


# ---------------------------------------------------------------------------
# Restore-only helper. Repair both the fresh lifecycle form and the already-
# materialized broken `Ok(restored)` form from the first r30 attempt.
# ---------------------------------------------------------------------------
restore_marker = "/// CAS-R30-HYBRID-CATALOG-RESTORE-ONLY"
restore_start = text.find(restore_marker)
restore_end = text.find("\n/// [MOC-257 三态]", restore_start)
if restore_start < 0 or restore_end <= restore_start:
    raise SystemExit("r30 catalog mutation truth could not isolate restore-only helper")
restore = text[restore_start:restore_end]

if "let source_restored = match auto_review_overlay_active(&paths)" not in restore:
    match_anchor = "    match restore_source_if_overlay_active(&paths) {"
    if restore.count(match_anchor) != 1:
        raise SystemExit("r30 restore-only helper restore match anchor drifted")
    probe = '''    let source_restored = match auto_review_overlay_active(&paths) {
        Ok(active) => active,
        Err(e) => {
            return json!({
                "attempted": true,
                "success": false,
                "catalogOnly": true,
                "providerAuthMutated": false,
                "catalogMutated": false,
                "message": format!("inspect Auto Review catalog state failed: {e}"),
            })
        }
    };
'''
    restore = restore.replace(match_anchor, probe + match_anchor, 1)

# Result<()> success variant and all fields must use the pre-restore probe bool.
restore = restore.replace("        Ok(restored) => json!({", "        Ok(()) => json!({", 1)
restore = restore.replace('            "sourceRestored": restored,', '            "sourceRestored": source_restored,', 1)
if '            "catalogMutated": restored,' in restore:
    restore = restore.replace('            "catalogMutated": restored,', '            "catalogMutated": source_restored,', 1)
elif '            "catalogMutated": source_restored,' not in restore:
    restore = restore.replace(
        '            "sourceRestored": source_restored,',
        '            "sourceRestored": source_restored,\n            "catalogMutated": source_restored,',
        1,
    )
restore = restore.replace('            "message": if restored {', '            "message": if source_restored {', 1)
text = text[:restore_start] + restore + text[restore_end:]


# ---------------------------------------------------------------------------
# Gateway-level telemetry: Hybrid Direct provider/auth remains untouched while
# codexMutated truthfully reflects the narrow catalog exception.
# ---------------------------------------------------------------------------
if "let catalog_mutated = catalog_sync" not in text:
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

marker_pos = text.index("CAS-R30-HYBRID-CATALOG-REFRESH")
branch_end = text.index("    let target_result = with_config_write", marker_pos)
gateway = text[marker_pos:branch_end]
if '"codexMutated": catalog_mutated,' not in gateway:
    count = gateway.count('"codexMutated": false,')
    if count != 2:
        raise SystemExit(
            f"r30 catalog mutation truth expected exactly two gateway codexMutated=false fields, found {count}"
        )
    gateway = gateway.replace('"codexMutated": false,', '"codexMutated": catalog_mutated,')
    text = text[:marker_pos] + gateway + text[branch_end:]

PATH.write_text(text, encoding="utf-8")

text = PATH.read_text(encoding="utf-8")
for required in (
    "CAS-R30-CATALOG-MUTATION-TRUTH",
    "let source_restored = match auto_review_overlay_active(&paths)",
    "Ok(active) => active",
    '"catalogMutated": source_restored || catalog_applied',
    '"catalogMutated": source_restored',
    "let catalog_mutated = catalog_sync",
    '"codexMutated": catalog_mutated',
):
    if required not in text:
        raise SystemExit(f"r30 catalog mutation truth missing: {required}")
if "Ok(restored) => restored" in text or '"message": if restored {' in text:
    raise SystemExit("r30 catalog mutation truth: stale Result<()>-as-bool code remains")

print("r30 catalog mutation telemetry truth: PASS")
