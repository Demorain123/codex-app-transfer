from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r31 required overlay/composer missing: {rel}")
    print(f"r31 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# Keep the validated r30 stack authoritative. r31 is intentionally only a UI layout
# hotfix for the r29 Auto Review editor inside the provider modal.
run("scripts/apply_r30_unified.py")

REVISION.write_text("31\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_auto_review_layout_r31.py")
run("scripts/review_auto_review_layout_r31.py")

required = {
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-UI-R29-EDITOR",
        "CAS-AUTO-REVIEW-LAYOUT-R31",
        'class="pf__auto-review-row"',
    ],
    "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue": [
        "CAS-AUTO-REVIEW-UI-R29",
        "CAS-AUTO-REVIEW-LAYOUT-R31",
        "grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr) auto;",
    ],
    "src-tauri/src/admin/services/desktop/snapshot.rs": [
        "CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY",
        "CAS-R30-CATALOG-MUTATION-TRUTH",
    ],
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs": ["CAS-HYBRID-DIRECT-R28"],
    "crates/proxy/src/forward.rs": [
        "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
        "CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK",
    ],
    "src-tauri/src/runtime_diag.rs": ["CAS-RUNTIME-DIAG-R26"],
    "src-tauri/src/admin/handlers/proxy.rs": ["CAS-PROXY-LIFECYCLE-R27"],
}
for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r31 materialization missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r31 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=31" not in version or "app_version=2.4.5+31" not in version:
    raise SystemExit("r31 visible/package version stamp missing after composition")

print("r31 unified composition: COMPLETE (r30 unchanged + Auto Review provider-modal layout hotfix)")
