from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r30 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


snapshot = read("src-tauri/src/admin/services/desktop/snapshot.rs")
overlay = read("crates/codex_integration/src/auto_review_overlay.rs")
crud = read("src-tauri/src/admin/handlers/providers/crud.rs")
hybrid = read("src-tauri/src/admin/services/desktop/hybrid_direct.rs")
provider_form = read("frontend/src/components/provider/ProviderFormModal.vue")
provider_api = read("frontend/src/api/providers.ts")
version = read("SUB2API_GROK_COMPAT_VERSION.txt")

# 1) All parent layers must survive composition.
required = {
    "crates/codex_integration/src/auto_review_overlay.rs": [
        "CAS-AUTO-REVIEW-R24",
        "CAS-R30-AUTO-REVIEW-OVERLAY-ACTIVE-PROBE",
    ],
    "crates/proxy/src/forward.rs": [
        "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
        "CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK",
    ],
    "src-tauri/src/runtime_diag.rs": ["CAS-RUNTIME-DIAG-R26"],
    "src-tauri/src/admin/handlers/proxy.rs": [
        "CAS-PROXY-LIFECYCLE-R27",
        "CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH",
    ],
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs": ["CAS-HYBRID-DIRECT-R28"],
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-UI-R29-EDITOR",
        "CAS-AUTO-REVIEW-R29-SAVE-FEEDBACK",
    ],
    "frontend/src/api/providers.ts": [
        "CAS-AUTO-REVIEW-R29-API-WIRE-READ",
        "CAS-AUTO-REVIEW-R29-API-WIRE-WRITE",
    ],
}
for rel, markers in required.items():
    text = read(rel)
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r30 review parent marker missing in {rel}: {marker}")

# The read-only probe must reuse r24's private ownership/path comparison and perform no writes.
probe_start = overlay.find("/// CAS-R30-AUTO-REVIEW-OVERLAY-ACTIVE-PROBE")
probe_end = overlay.find("/// If a previous Apply left `model_catalog_json`", probe_start)
if probe_start < 0 or probe_end <= probe_start:
    raise SystemExit("r30 review could not isolate overlay-active probe")
probe = overlay[probe_start:probe_end]
for marker in (
    "pub fn auto_review_overlay_active",
    "configured_catalog_path(paths)?",
    "same_path(current, &overlay_path(paths))",
):
    if marker not in probe:
        raise SystemExit(f"r30 review overlay-active probe invariant missing: {marker}")
for forbidden in ("sync_root_value(", "save_raw_config(", "std::fs::write", "remove_file("):
    if forbidden in probe:
        raise SystemExit(f"r30 review overlay-active probe is not read-only: {forbidden}")

# 2) r28 zero-proxy ownership must remain intact. Hybrid Direct may now mutate only the model catalog
# pointer through the r30 exception; provider/auth/network ownership is still CC Switch's.
for marker in (
    "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
    '"mode": "hybrid_direct_gateway"',
    "start_proxy_for_provider_if_needed",
):
    if marker not in snapshot:
        raise SystemExit(f"r30 review r28 gateway invariant missing: {marker}")
for marker in (
    "CC Switch",
    "official ChatGPT/OAuth route",
    "mutation_blocked",
):
    if marker not in hybrid:
        raise SystemExit(f"r30 review Hybrid Direct safety helper missing: {marker}")

# 3) Isolate the provider-specific r30 catalog-only function. It may touch only r24 COW state and
# model_catalog_json; provider/auth/network/proxy operations are forbidden.
start = snapshot.find("/// CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY")
end = snapshot.find("\n/// CAS-R30-HYBRID-CATALOG-RESTORE-ONLY", start)
if start < 0 or end <= start:
    raise SystemExit("r30 review could not isolate provider catalog-only function")
catalog_only = snapshot[start:end]
for marker in (
    "sync_auto_review_catalog_only_for_provider",
    "expected_provider_id",
    "active provider changed during Auto Review save",
    "auto_review_overlay_active(&paths)",
    "Ok(active) => active",
    "restore_source_if_overlay_active(&paths)",
    "apply_auto_review_overrides(&paths, Some(&overrides))",
    "CAS-R30-CATALOG-MUTATION-TRUTH",
    '"catalogMutated": source_restored || catalog_applied',
    '"providerAuthMutated": false',
    '"codexConfigScope": "model_catalog_json_only"',
):
    if marker not in catalog_only:
        raise SystemExit(f"r30 review catalog-only invariant missing: {marker}")
for forbidden in (
    "apply_provider(",
    "ensure_gateway_key(",
    "start_proxy_if_needed(",
    "start_proxy_for_provider_if_needed(",
    "activate_real_account(",
    "activate_fake_account(",
    "clear_active_auth_file(",
    "openai_base_url",
    "chatgpt_base_url",
):
    if forbidden in catalog_only:
        raise SystemExit(f"r30 review catalog-only scope leak: {forbidden}")
probe_pos = catalog_only.find("auto_review_overlay_active(&paths)")
restore_pos = catalog_only.find("restore_source_if_overlay_active(&paths)")
apply_pos = catalog_only.find("apply_auto_review_overrides(&paths, Some(&overrides))")
if not (0 <= probe_pos < restore_pos < apply_pos):
    raise SystemExit("r30 review requires read-only probe before source restore before shadow rebuild")
if "Ok(restored) => restored" in catalog_only:
    raise SystemExit("r30 review: Result<()> restore is still being treated as bool")

# r24 intentionally exposes these helpers through its public module, not crate-root re-exports.
for marker in (
    "CAS-R30-AUTO-REVIEW-MODULE-IMPORT",
    "codex_app_transfer_codex_integration::auto_review_overlay::{",
    "auto_review_overlay_active",
    "restore_source_if_overlay_active",
):
    if marker not in snapshot:
        raise SystemExit(f"r30 review authoritative COW import missing: {marker}")
if "use codex_app_transfer_codex_integration::{\n    apply_auto_review_overrides," in snapshot:
    raise SystemExit("r30 review: stale invalid crate-root Auto Review import remains")

# 4) Restore-only helper must be even narrower than apply: probe exact shadow state, then restore only.
restore_start = snapshot.find("/// CAS-R30-HYBRID-CATALOG-RESTORE-ONLY")
restore_end = snapshot.find("\n/// [MOC-257 三态]", restore_start)
if restore_start < 0 or restore_end <= restore_start:
    raise SystemExit("r30 review could not isolate restore-only catalog helper")
restore_only = snapshot[restore_start:restore_end]
for marker in (
    "restore_auto_review_source_catalog_only",
    "auto_review_overlay_active(&paths)",
    "Ok(active) => active",
    "restore_source_if_overlay_active(&paths)",
    "Ok(()) => json!({",
    '"sourceRestored": source_restored',
    '"catalogMutated": source_restored',
    '"providerAuthMutated": false',
):
    if marker not in restore_only:
        raise SystemExit(f"r30 review restore-only invariant missing: {marker}")
for forbidden in (
    "apply_auto_review_overrides(",
    "apply_provider(",
    "start_proxy",
    "activate_real_account",
    "activate_fake_account",
    "clear_active_auth_file",
):
    if forbidden in restore_only:
        raise SystemExit(f"r30 review restore-only scope leak: {forbidden}")
if '"message": if restored {' in restore_only or "Ok(restored)" in restore_only:
    raise SystemExit("r30 review: restore-only helper still treats Result<()> payload as bool")

# 5) Hybrid Direct gateway sync must refresh/rebase the Auto Review shadow on every active-provider
# sync, while truthfully reporting that catalog mutation is different from provider/auth mutation.
sync_start = snapshot.find("async fn sync_desktop_for_active_provider_impl")
sync_end = snapshot.find("    let target_result = with_config_write", sync_start)
if sync_start < 0 or sync_end <= sync_start:
    raise SystemExit("r30 review could not isolate Hybrid Direct gateway sync")
gateway_sync = snapshot[sync_start:sync_end]
for marker in (
    "CAS-R30-HYBRID-CATALOG-REFRESH",
    "sync_auto_review_catalog_only_for_provider(provider_id)",
    "let catalog_mutated = catalog_sync",
    '"catalogSync": catalog_sync',
    '"codexMutated": catalog_mutated',
    '"providerAuthMutated": false',
):
    if marker not in gateway_sync:
        raise SystemExit(f"r30 review gateway catalog lifecycle missing: {marker}")
for forbidden in ("apply_provider(", "ensure_gateway_key(", "write_auth("):
    if forbidden in gateway_sync:
        raise SystemExit(f"r30 review Hybrid Direct gateway gained forbidden mutation: {forbidden}")

# 6) r28 full snapshot restore remains blocked, but r30 restores only Transfer's shadow pointer first.
exit_marker = snapshot.find("CAS-R30-HYBRID-CATALOG-EXIT-RESTORE")
full_restore = snapshot.find("restore_codex_state(", exit_marker)
if exit_marker < 0 or full_restore < 0 or exit_marker >= full_restore:
    raise SystemExit("r30 review catalog-only exit restore is not before full restore path")
exit_window = snapshot[exit_marker:full_restore]
for marker in (
    "restore_auto_review_source_catalog_only()",
    '"providerAuthMutated": false',
    '"catalogRestore": catalog_restore',
):
    if marker not in exit_window:
        raise SystemExit(f"r30 review exit catalog restore invariant missing: {marker}")

# 7) Hybrid Direct gets the catalog-only exception only when an explicit active-provider mapping
# changed. Normal mode keeps r29's full desktop sync. Also reject r29's stale handler re-export import.
for marker in (
    "CAS-R30-HYBRID-AUTO-REVIEW-DISPATCH",
    "if auto_review_changed && edited_active_provider",
    "crate::admin::services::desktop::hybrid_direct::enabled()",
    "sync_auto_review_catalog_only_for_provider(&id)",
    "sync_desktop_for_active_provider(&state).await",
    "crate::admin::services::desktop::snapshot::{",
):
    if marker not in crud:
        raise SystemExit(f"r30 review dispatch invariant missing: {marker}")
if "use super::super::desktop::{switch_provider_and_sync, sync_desktop_for_active_provider};" in crud:
    raise SystemExit("r30 review: r29 stale/non-reexported desktop sync import resurfaced")

# 8) Explicit empty mappings still travel through the provider API, because clearing the last row
# must restore the original source catalog rather than leave a stale shadow override.
for marker in (
    "if (payload.autoReviewModelOverrides !== undefined)",
    "body.autoReviewModelOverrides = payload.autoReviewModelOverrides",
):
    if marker not in provider_api:
        raise SystemExit(f"r30 review clear-override transport missing: {marker}")
if "updateResult?.autoReviewChanged" not in provider_form:
    raise SystemExit("r30 review save/apply feedback missing")
if "restartCodexApp(" in provider_form:
    raise SystemExit("r30 review provider save must not auto-restart Codex")

# 9) Final identity.
if "compat_revision=30" not in version or "app_version=2.4.5+30" not in version:
    raise SystemExit("r30 review visible/package version is not v2.4.5+30")

print("r30 deep unified review: PASS (r28 Hybrid Direct + r29 Auto Review + probed catalog lifecycle)")
