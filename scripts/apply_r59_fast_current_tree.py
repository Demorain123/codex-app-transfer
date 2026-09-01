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
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r59 fast-current-tree required component missing: {rel}")
    print(f"r59 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r58_generated_baseline() -> bool:
    paths = (BACKEND, PAGE, API, PROCESS, COMPACT, MCP_SERVERS, NO_MICRO, CARGO)
    if not all(path.is_file() for path in paths):
        return False
    backend = BACKEND.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")
    process = PROCESS.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    mcp = MCP_SERVERS.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    cargo = CARGO.read_text(encoding="utf-8")
    return (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY" in backend
        and "CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX" in backend
        and "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI" in page
        and "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD" in process
        and "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK" in compact
        and "CAS-R55-DETACHED-MCP-HELPER" in mcp
        and "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION" in mcp
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and 'rusqlite = { version = "0.40", features = ["bundled"] }' in cargo
        and 'rusqlite = { version = "0.31", features = ["bundled"] }' not in cargo
    )


if has_complete_r58_generated_baseline():
    print("R59 FAST BASELINE: complete generated r58 tree detected; R58 COMPOSITION SKIP")
else:
    print("R59 FAST BASELINE: r58 generated markers incomplete; repairing r58 baseline once")
    run("scripts/apply_r58_fast_current_tree.py")
    if not has_complete_r58_generated_baseline():
        raise SystemExit("r59 fast baseline repair completed but required r58 markers are still missing")

run("scripts/apply_r59_interrupted_tail_same_id_recovery.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=59" not in version_before or "app_version=2.4.5+59" not in version_before:
    REVISION.write_text("59\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R59 version already stamped; revision materializer SKIP")

checks = {
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        '"rewindInterruptedTail"',
        "stage=bad_tail_removed",
        "same_thread=true",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
        "同 ID 清理中断尾巴（0xC000013A）",
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
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r59 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=59" not in version or "app_version=2.4.5+59" not in version:
    raise SystemExit("r59 fast-current-tree version stamp missing")

print("R59 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r58 tree is reused without replay when warm")
print("- only same-thread interrupted/failed tail recovery is added")
print("- r58 lifecycle, r57 external migration, r56 compact parser and r49 TEMP remain unchanged")
