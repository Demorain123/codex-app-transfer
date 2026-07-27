from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r29 required overlay missing: {rel}")
    print(f"r29 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# r29 is intentionally based on the last validated unified line, r27. Another conversation owns
# r28. Once that r28 is final, this branch can be rebased/retargeted without changing r29 UI logic.
run("scripts/apply_r27_unified.py")

# r27 stamps itself as 27. Restamp the standard visible/package identity as 29, replay the standard
# compat revision, then apply the UI overlay last so an r24 replay cannot resurrect the raw JSON UI.
REVISION.write_text("29\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_auto_review_ui_r29.py")
run("scripts/review_auto_review_ui_r29.py")

checks = {
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-UI-R29-EDITOR",
        "CAS-AUTO-REVIEW-UI-R29-SILENT-FETCH",
        "CAS-AUTO-REVIEW-UI-R29-AUTO-FETCH",
        "AutoReviewModelOverridesEditor",
    ],
    "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue": [
        "CAS-AUTO-REVIEW-UI-R29",
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
        raise SystemExit(f"r29 materialization missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r29 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=29" not in version or "app_version=2.4.5+29" not in version:
    raise SystemExit("r29 visible/package version stamp missing after composition")

# r24 remains the sole Auto Review catalog implementation and must stay registered exactly once.
lib_text = (ROOT / "crates/codex_integration/src/lib.rs").read_text(encoding="utf-8")
module_line = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"
if lib_text.count(module_line) != 1:
    raise SystemExit(
        f"r29 requires exactly one r24 module registration, found {lib_text.count(module_line)}"
    )

# Scope freeze: r29 must not add provider-identity routing logic. The r27 built-in openai fallback
# remains unchanged until a later, separately testable provider-identity option is implemented.
for rel in ("scripts/apply_auto_review_ui_r29.py", "scripts/review_auto_review_ui_r29.py"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for forbidden in ("openai_base_url", "chatgpt_base_url", "model_providers.OpenAi"):
        if forbidden in text:
            raise SystemExit(f"r29 scope leak in {rel}: {forbidden}")

print("r29 unified materialization gate: PASS (r27 unified + provider-model Auto Review UI)")
