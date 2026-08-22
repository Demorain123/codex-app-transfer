from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r43 required overlay/composer missing: {rel}")
    print(f"r43 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r43 inherited successful no-op: {rel}")


run("scripts/apply_r42_unified.py")
run("scripts/apply_r43_semantic_anchor_prep.py")
run("scripts/apply_r43_health_mcp_hardening.py")
REVISION.write_text("43\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/review_r43_health_mcp_hardening.py")

chain = (ROOT / "src-tauri/src/admin/handlers/chain_health.rs").read_text(encoding="utf-8")
runtime = (ROOT / "src-tauri/src/runtime_diag.rs").read_text(encoding="utf-8")
grok = (ROOT / "crates/adapters/src/mapper/grok_build.rs").read_text(encoding="utf-8")
for marker, source in (
    ("CAS-R43-HEALTH-MCP-HARDENING", chain),
    ("fault_compaction_transition", chain),
    ("CAS-R43-MODEL-SWITCH-COMPACTION-DIAG", runtime),
    ("CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD", grok),
):
    if marker not in source:
        raise SystemExit(f"r43 materialization missing invariant marker: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=43" not in version or "app_version=2.4.5+43" not in version:
    raise SystemExit("r43 visible/package version stamp missing after composition")

print("r43 unified composition: COMPLETE (r42 preserved + semantic anchor prep + health/compaction/MCP hardening)")
