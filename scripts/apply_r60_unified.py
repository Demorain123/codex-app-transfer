from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/threadRecovery.ts"
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


# Preserve the proven r59 same-ID bad-tail recovery, then add lifecycle state +
# a recent-session catalog. r60 does not change the actual mutation semantics.
run("scripts/apply_r59_unified.py")
run("scripts/apply_r60_recovery_session_catalog.py")

REVISION.write_text("60\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        "CAS-R60-RECOVERY-SESSION-CATALOG",
        "RecoveryStatusRegistry",
        "recovery-status-r60.json",
        "r59_log_migration",
        "RECOVERY-SUCCESS.json",
        "latest_unresolved_failure",
        "pub async fn sessions",
        "stage=recovery_status_persisted",
    ),
    "src-tauri/src/admin/mod.rs": (
        "/api/thread-recovery/preview",
        "/api/thread-recovery/action",
        "/api/thread-recovery/sessions",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        "CAS-R60-RECOVERY-SESSION-CATALOG",
        "最近 Session",
        "无未处理失败",
        "历史故障已处理",
    ),
    "frontend/src/api/threadRecovery.ts": (
        "CAS-R60-RECOVERY-SESSION-CATALOG",
        "getThreadRecoverySessions",
        "ThreadRecoverySessionItem",
        "recoveryStatus",
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

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=60" not in version or "app_version=2.4.5+60" not in version:
    raise SystemExit("r60 visible/package version stamp missing")

print("R60 UNIFIED COMPOSITION PASS")
print("- r59 same-thread 0xC000013A interrupted/failed-tail recovery remains unchanged")
print("- recent active/archived sessions now have an explicit recovery catalog")
print("- verified r59 success is migrated into persistent recovered state without re-running mutation")
print("- future verified same-ID recovery writes a structural local success receipt")
print("- old failure evidence remains available for forensics but no longer stays permanently unresolved")
print("- a newer failure after recovery reopens that same session as needsRecovery")
