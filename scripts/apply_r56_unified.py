from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r56 required component missing: {rel}")
    print(f"r56 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r55_unified.py")
run("scripts/apply_r56_compact_sse_summary_fallback.py")

REVISION.write_text("56\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "[compact-r56] action=sse_summary_fallback",
        "r56_completed_response_without_text_uses_output_text_done",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "detached_web_fetch_exe_r55",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r56 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=56" not in version or "app_version=2.4.5+56" not in version:
    raise SystemExit("r56 visible/package version stamp missing")

print("R56 UNIFIED COMPOSITION PASS")
print("- r55 detached MCP helper behavior remains intact")
print("- r54 Responses SSE reassembly now preserves public summary text even when response.completed.output omits it")
print("- same-model Terra/Luna compaction and cross-model compaction use the same corrected response parser")
print("- ordinary model turns, session/thread identity, r49 TEMP, and provider routing remain unchanged")
