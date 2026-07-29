from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r32 required overlay/composer missing: {rel}")
    print(f"r32 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# Preserve the exact validated r31 stack. r32 adds only the No Lagging compatibility
# layer: Micro/Accessory guard semantics + exit-only MCP/helper generation cleanup.
run("scripts/apply_r31_unified.py")

REVISION.write_text("32\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_no_lagging_r32.py")
run("scripts/review_no_lagging_r32.py")

required = {
    "src-tauri/src/admin/services/desktop/no_micro.rs": [
        "CAS-NO-MICRO-R23-LAUNCH-ARGS",
        "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD",
        "CAS-NO-LAGGING-R32-ACCESSORY-GUARD",
    ],
    "src-tauri/resources/codex_no_micro_launcher.mjs": [
        "CAS-NO-LAGGING-R32-MICRO-ACCESSORY-GUARD",
        "codex-micro-disabled-worker-safe",
    ],
    "src-tauri/resources/codex_no_lagging_janitor.ps1": [
        "CAS-NO-LAGGING-R32-MCP-EXIT-GUARD",
        "Same-Identity",
    ],
    "frontend/src/components/codex/NoMicroPanel.vue": [
        "CAS-NO-LAGGING-R32-UI",
        "Codex No Lagging A/B",
    ],
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-LAYOUT-R31",
    ],
    "src-tauri/src/admin/services/desktop/snapshot.rs": [
        "CAS-R30-HYBRID-AUTO-REVIEW-CATALOG-ONLY",
    ],
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs": ["CAS-HYBRID-DIRECT-R28"],
    "src-tauri/src/runtime_diag.rs": ["CAS-RUNTIME-DIAG-R26"],
    "src-tauri/src/admin/handlers/proxy.rs": ["CAS-PROXY-LIFECYCLE-R27"],
}
for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r32 materialization missing file: {rel}")
    body = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r32 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=32" not in version or "app_version=2.4.5+32" not in version:
    raise SystemExit("r32 visible/package version stamp missing after composition")

print("r32 unified composition: COMPLETE (r31 preserved + No Lagging Micro/Accessory + MCP Exit Guard)")
