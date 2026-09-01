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
        raise SystemExit(f"r55 required component missing: {rel}")
    print(f"r55 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r54_unified.py")
run("scripts/apply_r55_detached_mcp_helper.py")

REVISION.write_text("55\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
        "reassemble_responses_sse_to_response_json_r54",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "detached_web_fetch_exe_r55",
        "detached_mcp_helper_name_r55",
        "[mcp-r55] action=detached_helper_ready",
        "r55_detached_helper_name_is_content_addressed",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r55 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=55" not in version or "app_version=2.4.5+55" not in version:
    raise SystemExit("r55 visible/package version stamp missing")

print("R55 UNIFIED COMPOSITION PASS")
print("- r54 cross-model compact/SSE compatibility remains intact")
print("- Windows cat-webfetch registration uses a content-addressed detached helper in user data")
print("- OMP/Codex can keep MCP alive without locking the installed main Transfer executable")
print("- running old helper versions do not block creating/registering a new helper version")
print("- stale unlocked helper versions are cleaned best-effort")
print("- exact Codex session/thread identity, r49 TEMP behavior, and non-Windows MCP behavior remain unchanged")
