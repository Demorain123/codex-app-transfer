from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r40 required overlay/composer missing: {rel}")
    print(f"r40 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r40 inherited successful no-op: {rel}")


# Preserve the fully validated r39 lifecycle as the base. r40 deliberately adds
# Windows socket-handle and owner-classification guards around it rather than
# replacing the owner-thread architecture.
run("scripts/apply_r39_unified.py")

# Keep the inherited r25 marker replay-safe before stamping the next visible/package
# revision, following the same composition invariant used by r39.
run("scripts/apply_r39_r25_replay_marker_prep.py")
REVISION.write_text("40\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

run("scripts/apply_r40_windows_port_guard.py")
run("scripts/apply_r40_chain_owner_class_fix.py")
run("scripts/review_r39_proxy_owner_thread.py")
run("scripts/review_r40_windows_port_guard.py")

required = {
    "src-tauri/src/proxy_runner.rs": [
        "CAS-R39-PROXY-OWNER-THREAD",
        "CAS-R40-WINDOWS-PORT-GUARD",
        "listener_handle_guard",
        "listener_handle_guard_failed",
        "owner_thread_joined",
        "port_release_verified",
        "listener_residue_detected",
        "proxy_lifecycle_r39_owner_thread_join_rebind_100_generations",
    ],
    "src-tauri/src/windows_tcp_owner.rs": [
        "CAS-R38-WINDOWS-TCP-OWNER",
        "CAS-R40-WINDOWS-PORT-GUARD",
        "GetHandleInformation",
        "SetHandleInformation",
        "HANDLE_FLAG_INHERIT",
        "owner_class=",
        "windows_port_guard_r40_clears_inherit_bit",
        "windows_port_guard_r40_classifies_foreign_and_stale_binders",
    ],
    "src-tauri/src/admin/handlers/proxy.rs": [
        "CAS-R39-BIND-BUSY-NONRETRYABLE",
        "bind_busy_nonretryable",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R39-BINDER-TERMINOLOGY",
        "CAS-R40-PORT-OWNER-CLASSIFICATION",
        "CAS-R40-LIVE-BINDER-SELF-CLASSIFICATION",
        '"self_live"',
        '"foreign_live"',
        "owner_class=stale_binder",
        '"inspect_internal_lifecycle"',
        '"stop_foreign_owner_safely"',
    ],
    "src-tauri/src/main.rs": [
        "CAS-R39-RELEASE-TEST-CONSOLE",
        'cfg_attr(all(not(debug_assertions), not(test)), windows_subsystem = "windows")',
    ],
    "frontend/src/i18n/zh.ts": ["Sub2API Grok Compat r40 · v2.4.5+40"],
    "frontend/src/i18n/en.ts": ["Sub2API Grok Compat r40 · v2.4.5+40"],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r40 materialization missing marker in {rel}: {marker}")

# r40 must not weaken the r39 safety policy. Match actual mutation primitives,
# not user-facing explanatory text that intentionally mentions SO_REUSEADDR.
combined = "\n".join((ROOT / rel).read_text(encoding="utf-8") for rel in [
    "src-tauri/src/proxy_runner.rs",
    "src-tauri/src/windows_tcp_owner.rs",
    "src-tauri/src/admin/handlers/proxy.rs",
    "src-tauri/src/admin/handlers/chain_health.rs",
])
for forbidden in (
    "runtime: tokio::runtime::Runtime",
    "h.runtime.shutdown_background()",
    "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
    "TerminateProcess(",
    "Command::new(\"taskkill\")",
    "Command::new(\"Stop-Process\")",
    "set_reuseaddr(true)",
):
    if forbidden in combined:
        raise SystemExit(f"r40 materialization retained/introduced forbidden pattern: {forbidden}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=40" not in version or "app_version=2.4.5+40" not in version:
    raise SystemExit("r40 visible/package version stamp missing after composition")

print(
    "r40 unified composition: COMPLETE "
    "(validated r39 owner-thread base + Windows socket inheritance guard + self/foreign/stale binder classification + no unsafe auto-kill/port-switch)"
)
