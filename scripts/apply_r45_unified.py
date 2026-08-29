from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r45 required component missing: {rel}")
    print(f"r45 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve the r43 verified health/MCP composition, then add only the runtime
# continuity + semantic-terminal transform.
run("scripts/apply_r43_unified.py")
run("scripts/apply_r45_model_switch_continuity.py")

REVISION.write_text("45\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "effective-models-r45.json",
        "rebind_compaction_model",
        "CAS-R45-RESPONSES-SEMANTIC-TERMINAL",
        "response_eof_without_terminal",
        "r45_compaction_helper_detection_is_structural",
        "r45_semantic_terminal_detector_handles_chunk_boundaries",
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R43-REWRITE-HEALTH-MCP",
        "fault_compaction_transition",
        "verified_generation_helpers",
    ),
    "crates/adapters/src/mapper/grok_build.rs": (
        "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD",
        "grok_effective_tool_name",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r45 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=45" not in version or "app_version=2.4.5+45" not in version:
    raise SystemExit("r45 visible/package version stamp missing")

print("R45 UNIFIED COMPOSITION PASS")
print("- r43 health/MCP base preserved")
print("- cross-model effective-model continuity added")
print("- stale compaction helper model rebound before resolver routing")
print("- subagent/memgen helpers cannot overwrite main-session effective model")
print("- Responses semantic terminal events now outrank transport EOF/Drop")
