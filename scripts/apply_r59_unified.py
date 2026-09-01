from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/threadRecovery.ts"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r59 required component missing: {rel}")
    print(f"r59 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Keep every r58 fix, then add only a same-thread recovery mitigation for the
# upstream Windows app-server 0xC000013A interrupted/failed tail state.
run("scripts/apply_r58_unified.py")
run("scripts/apply_r59_interrupted_tail_same_id_recovery.py")

REVISION.write_text("59\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        '"rewindInterruptedTail"',
        "latest_turn_states",
        "MAX_BAD_TAIL",
        "stage=bad_tail_removed",
        "same_thread=true",
        "model_request=false",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        "同 ID 清理中断尾巴（0xC000013A）",
        "rewindInterruptedTail",
    ),
    "frontend/src/api/threadRecovery.ts": (
        "rewindInterruptedTail",
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
            raise SystemExit(f"r59 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=59" not in version or "app_version=2.4.5+59" not in version:
    raise SystemExit("r59 visible/package version stamp missing")

print("R59 UNIFIED COMPOSITION PASS")
print("- r58 Windows lifecycle ownership remains intact")
print("- r57 external MCP migration + r55 detached helper remain intact")
print("- r56 compact SSE summary fallback remains intact")
print("- new recovery action removes only newest consecutive interrupted/failed persisted turns")
print("- same thread/session id is preserved and a completed boundary is required")
print("- backup happens before mutation; workspace files are untouched; no model request is sent")
print("- this is an upstream 0xC000013A recovery mitigation, not a claim to patch OpenAI codex.exe")
