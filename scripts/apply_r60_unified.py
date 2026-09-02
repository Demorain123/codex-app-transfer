from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
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


# Keep the complete r59 composition, then add only the Sub2API native Responses
# post-compaction replay compatibility shim.  Official/non-compat providers are
# intentionally outside the new rewrite gate.
run("scripts/apply_r59_unified.py")
run("scripts/apply_r60_sub2api_post_compaction_replay.py")
run("scripts/apply_r60_post_compaction_compile_safety.py")

REVISION.write_text("60\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-CALL",
        "CAS-R60-POST-COMPACTION-BORROW-SAFETY",
        "translate_sub2api_post_compaction_replay_r60",
        "translate_compaction_for_sub2api",
        "official_or_non_compat_responses_provider_is_byte_identical",
        "content_logged=false",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    ),
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
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

forward = FORWARD.read_text(encoding="utf-8")
if "let after = input.len();" not in forward or "input_items_after: after" not in forward:
    raise SystemExit("r60 generated-source borrow-safety invariant missing")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=60" not in version or "app_version=2.4.5+60" not in version:
    raise SystemExit("r60 visible/package version stamp missing")

print("R60 UNIFIED COMPOSITION PASS")
print("- r59 same-ID interrupted-tail recovery remains intact")
print("- r58 Windows lifecycle, r57 MCP migration and r56 compact SSE fallback remain intact")
print("- Sub2API Responses compat path translates native post-compaction artifacts in-place")
print("- official/non-compat Responses providers remain outside the r60 rewrite gate")
print("- blank/unrecognized compaction artifacts are preserved, never silently dropped")
print("- telemetry records counts only; compact content is not logged")
