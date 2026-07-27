from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r28 required overlay missing: {rel}")
    print(f"r28 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# Keep the already-validated r24+r25+r26+r27 implementation as the base. r28 is a thin
# frontend/UX layer only; it must not fork the catalog/auth/runtime/proxy behavior.
run("scripts/apply_r27_unified.py")

# r27 intentionally stamps itself as 27. Restamp the standard application/package identity as 28,
# then apply the UI overlay last so any r24 replay cannot resurrect the raw JSON editor.
REVISION.write_text("28\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_auto_review_ui_r28.py")
run("scripts/review_auto_review_ui_r28.py")

checks = {
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-UI-R28-EDITOR",
        "CAS-AUTO-REVIEW-UI-R28-SILENT-FETCH",
        "CAS-AUTO-REVIEW-UI-R28-AUTO-FETCH",
        "AutoReviewModelOverridesEditor",
    ],
    "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue": [
        "CAS-AUTO-REVIEW-UI-R28",
        "mergedOptions",
        "usedByOthers",
    ],
    "crates/codex_integration/src/auto_review_overlay.rs": ["CAS-AUTO-REVIEW-R24"],
    "crates/proxy/src/forward.rs": [
        "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
        "CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK",
    ],
    "src-tauri/src/runtime_diag.rs": ["CAS-RUNTIME-DIAG-R26"],
    "src-tauri/src/admin/handlers/proxy.rs": ["CAS-PROXY-LIFECYCLE-R27"],
}
for rel, markers in checks.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r28 materialization missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r28 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=28" not in version or "app_version=" not in version:
    raise SystemExit("r28 version stamp missing after composition")

# r24 remains the only catalog implementation and its registration must still be singular.
lib_text = (ROOT / "crates/codex_integration/src/lib.rs").read_text(encoding="utf-8")
module_line = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"
if lib_text.count(module_line) != 1:
    raise SystemExit(
        f"r28 requires exactly one r24 module registration, found {lib_text.count(module_line)}"
    )

print("r28 unified materialization gate: PASS (r27 unified + model-list Auto Review UI)")
