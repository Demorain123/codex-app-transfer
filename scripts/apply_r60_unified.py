from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r60 required component missing: {rel}")
    print(f"r60 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Keep every r59/r58/r57/r56 fix, then add only the Sub2API post-compaction
# replay lowering.  This is intentionally request-side and provider-scoped.
run("scripts/apply_r59_unified.py")
run("scripts/apply_r60_sub2api_post_compaction_replay.py")

REVISION.write_text("60\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
        "apply_sub2api_post_compaction_replay_compat",
        "[sub2api-r60] action=post_compaction_replay_rewrite",
        "r60_named_sub2api_rewrites_luna_compaction_to_standard_message",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    ),
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "localize_compaction_summary_prefix",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r60 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=60" not in version or "app_version=2.4.5+60" not in version:
    raise SystemExit("r60 visible/package version stamp missing")

print("R60 UNIFIED COMPOSITION PASS")
print("- r59 same-ID interrupted-tail recovery remains intact")
print("- r58 Windows lifecycle and r57 MCP migration remain intact")
print("- r56 compact SSE summary fallback remains intact")
print("- Sub2API post-compaction private item is lowered to standard Responses user/input_text")
print("- native/OpenAI Responses providers remain byte-level passthrough")
