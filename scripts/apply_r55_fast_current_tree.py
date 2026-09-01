from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r55 fast-current-tree required component missing: {rel}")
    print(f"r55 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r54_generated_baseline() -> bool:
    if not all(path.is_file() for path in (FORWARD, COMPACT, MCP_SERVERS, NO_MICRO)):
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R51-COMPACTION-ROLE-TRUTH" in forward
        and "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY" in compact
        and "reassemble_responses_sse_to_response_json_r54" in compact
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX" in no_micro
    )


if has_complete_r54_generated_baseline():
    print("R55 FAST BASELINE: complete generated r54 tree detected; R54 COMPOSITION SKIP")
else:
    print("R55 FAST BASELINE: r54 generated markers incomplete; repairing r54 baseline once")
    run("scripts/apply_r54_fast_current_tree.py")
    if not has_complete_r54_generated_baseline():
        raise SystemExit("r55 fast baseline repair completed but required r54 markers are still missing")

run("scripts/apply_r55_detached_mcp_helper.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=55" not in version_before or "app_version=2.4.5+55" not in version_before:
    REVISION.write_text("55\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R55 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "detached_web_fetch_exe_r55",
        "[mcp-r55] action=detached_helper_ready",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r55 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=55" not in version or "app_version=2.4.5+55" not in version:
    raise SystemExit("r55 fast-current-tree version stamp missing")

print("R55 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r54 tree is reused without replay when warm")
print("- Windows MCP registration is detached from the installed main executable")
print("- ordinary model turns, compact SSE handling, session identity, and r49 launch TEMP remain unchanged")
