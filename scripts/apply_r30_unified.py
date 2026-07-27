from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r30 required overlay/composer missing: {rel}")
    print(f"r30 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# r30 starts from the validated r28 line, which already materializes the complete r27 stack first.
run("scripts/apply_r28_hybrid_direct.py")

# Restamp the standard visible/package identity before applying r29 UI/effectiveness on top.
REVISION.write_text("30\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

# Bring the r29 Auto Review UX + real transport/live-apply fixes without invoking the r29 composer
# itself (that composer intentionally starts again from r27 and would omit r28).
run("scripts/apply_auto_review_ui_r29_hardening.py")
run("scripts/apply_auto_review_ui_r29.py")
run("scripts/apply_auto_review_effective_r29.py")

# Resolve the one semantic collision between the sibling lines: r28 makes general desktop sync
# gateway-only while r29 expects that sync to rebuild the COW Auto Review catalog. The r30 bridge
# permits only an explicit model_catalog_json-only operation in Hybrid Direct.
run("scripts/apply_r30_hybrid_auto_review.py")

# Run both parent reviews plus the new cross-feature review. Parent reviews remain authoritative for
# their own invariants; r30 review checks the interaction and compile/import boundary.
run("scripts/review_hybrid_direct_r28.py")
run("scripts/review_hybrid_direct_r28_manual_guard.py")
run("scripts/review_auto_review_ui_r29.py")
run("scripts/review_r30_unified.py")

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
    "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue": ["CAS-AUTO-REVIEW-UI-R29"],
    "frontend/src/api/providers.ts": ["CAS-AUTO-REVIEW-R29-API-WIRE-WRITE"],
    "src-tauri/src/admin/services/desktop/snapshot.rs": [
        "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
        "CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY",
    ],
    "src-tauri/src/admin/handlers/providers/crud.rs": ["CAS-R30-HYBRID-AUTO-REVIEW-DISPATCH"],
}
for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r30 materialization missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r30 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=30" not in version or "app_version=2.4.5+30" not in version:
    raise SystemExit("r30 visible/package version stamp missing after composition")

lib_text = (ROOT / "crates/codex_integration/src/lib.rs").read_text(encoding="utf-8")
module_line = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"
if lib_text.count(module_line) != 1:
    raise SystemExit(
        f"r30 requires exactly one r24 Auto Review module registration, found {lib_text.count(module_line)}"
    )

print("r30 unified composition: COMPLETE (r24+r25+r26+r27+r28+r29+r30 bridge)")
