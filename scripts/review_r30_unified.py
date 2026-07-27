from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r30 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


snapshot = read("src-tauri/src/admin/services/desktop/snapshot.rs")
crud = read("src-tauri/src/admin/handlers/providers/crud.rs")
hybrid = read("src-tauri/src/admin/services/desktop/hybrid_direct.rs")
provider_form = read("frontend/src/components/provider/ProviderFormModal.vue")
provider_api = read("frontend/src/api/providers.ts")
version = read("SUB2API_GROK_COMPAT_VERSION.txt")

# 1) All parent layers must survive composition.
required = {
    "crates/codex_integration/src/auto_review_overlay.rs": ["CAS-AUTO-REVIEW-R24"],
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

# 2) r28 zero-proxy invariant must stay intact. Startup/general provider sync in Hybrid Direct is
# gateway-only and must still report that it did not mutate Codex provider/auth state.
for marker in (
    "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
    '"mode": "hybrid_direct_gateway"',
    '"codexMutated": false',
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

# 3) Isolate the r30 catalog-only function and prove its scope is narrow. It may touch the COW
# catalog + model_catalog_json pointer only; provider/auth/network/proxy operations are forbidden.
start = snapshot.find("/// CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY")
end = snapshot.find("\n/// [MOC-257 三态]", start)
if start < 0 or end <= start:
    raise SystemExit("r30 review could not isolate catalog-only function")
catalog_only = snapshot[start:end]
for marker in (
    "sync_auto_review_catalog_only_for_provider",
    "expected_provider_id",
    "active provider changed during Auto Review save",
    "restore_source_if_overlay_active(&paths)",
    "apply_auto_review_overrides(&paths, Some(&overrides))",
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
restore_pos = catalog_only.find("restore_source_if_overlay_active(&paths)")
apply_pos = catalog_only.find("apply_auto_review_overrides(&paths, Some(&overrides))")
if not (0 <= restore_pos < apply_pos):
    raise SystemExit("r30 review requires source restore before shadow rebuild")

# r24 intentionally exposes these helpers through its public module, not crate-root re-exports.
# Validate the generated Rust uses that authoritative API boundary so a full compile cannot be
# accidentally bypassed by static markers alone.
for marker in (
    "CAS-R30-AUTO-REVIEW-MODULE-IMPORT",
    "codex_app_transfer_codex_integration::auto_review_overlay::{",
    "apply_auto_review_overrides, restore_source_if_overlay_active",
):
    if marker not in snapshot:
        raise SystemExit(f"r30 review authoritative COW import missing: {marker}")
if '''use codex_app_transfer_codex_integration::{\n    apply_auto_review_overrides,'''.replace("\\n", "\n") in snapshot:
    raise SystemExit("r30 review: stale invalid crate-root Auto Review import remains")

# 4) Hybrid Direct gets the catalog-only exception only when an explicit active-provider mapping
# changed. Normal mode keeps r29's full desktop sync. This also fixes r29's missing handler re-export
# assumption by importing both functions from the real service module.
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

# 5) Explicit empty mappings still travel through the provider API, because clearing the last row
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

# 6) r30 is the first package that intentionally combines the two sibling lines.
if "compat_revision=30" not in version or "app_version=2.4.5+30" not in version:
    raise SystemExit("r30 review visible/package version is not v2.4.5+30")

print("r30 deep unified review: PASS (r28 Hybrid Direct + r29 Auto Review with catalog-only bridge)")
