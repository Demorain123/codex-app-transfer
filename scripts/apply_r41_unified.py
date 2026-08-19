from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r41 required overlay/composer missing: {rel}")
    print(f"r41 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r41 inherited successful no-op: {rel}")


# r41 deliberately keeps the fully validated r40 socket guard and owner
# classification. It changes only the user-triggered recovery semantics for a
# live foreign owner: clicking Try repair may release that owner after revalidation.
# apply_r40_unified.py already runs the r40 no-auto-kill review BEFORE r41 adds its
# explicit user-triggered termination primitive. Do not rerun that older review
# afterward, because its contract intentionally forbids any TerminateProcess use.
run("scripts/apply_r40_unified.py")
run("scripts/apply_r39_r25_replay_marker_prep.py")
REVISION.write_text("41\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r41_explicit_port_repair.py")
run("scripts/review_r39_proxy_owner_thread.py")
run("scripts/review_r41_explicit_port_repair.py")

required = {
    "src-tauri/src/proxy_runner.rs": [
        "CAS-R39-PROXY-OWNER-THREAD",
        "CAS-R40-WINDOWS-PORT-GUARD",
        "owner_thread_joined",
        "port_release_verified",
    ],
    "src-tauri/src/windows_tcp_owner.rs": [
        "CAS-R40-WINDOWS-PORT-GUARD",
        "CAS-R41-EXPLICIT-PORT-REPAIR",
        "terminate_live_foreign_listener_owner",
        "windows_port_repair_r41_rejects_self_owner",
        "windows_port_repair_r41_terminates_explicit_foreign_owner",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R40-PORT-OWNER-CLASSIFICATION",
        "CAS-R41-EXPLICIT-PORT-REPAIR",
        "release_foreign_port_owner",
        "现在可重新点击‘启动转发’",
    ],
    "frontend/src/i18n/zh.ts": [
        "Sub2API Grok Compat r41 · v2.4.5+41",
        "'chainHealth.recover': '尝试修复'",
    ],
    "frontend/src/i18n/en.ts": [
        "Sub2API Grok Compat r41 · v2.4.5+41",
        "'chainHealth.recover': 'Try repair'",
    ],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r41 materialization missing marker in {rel}: {marker}")

# Normal start/stop must remain non-destructive. TerminateProcess is permitted only
# inside windows_tcp_owner and must have exactly one call site from the explicit
# chain-health repair handler.
proxy = (ROOT / "src-tauri/src/proxy_runner.rs").read_text(encoding="utf-8")
chain = (ROOT / "src-tauri/src/admin/handlers/chain_health.rs").read_text(encoding="utf-8")
owner = (ROOT / "src-tauri/src/windows_tcp_owner.rs").read_text(encoding="utf-8")
if "TerminateProcess" in proxy:
    raise SystemExit("r41 materialization: process termination leaked into normal proxy lifecycle")
if chain.count("terminate_live_foreign_listener_owner(port, pid)") != 1:
    raise SystemExit("r41 materialization: explicit repair termination call must appear exactly once")
if owner.count("TerminateProcess(handle, R41_REPAIR_EXIT_CODE)") != 1:
    raise SystemExit("r41 materialization: native termination primitive count must be exactly one")
for forbidden in (
    "set_reuseaddr(true)",
    "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
):
    if forbidden in proxy + "\n" + chain + "\n" + owner:
        raise SystemExit(f"r41 materialization retained/introduced forbidden pattern: {forbidden}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=41" not in version or "app_version=2.4.5+41" not in version:
    raise SystemExit("r41 visible/package version stamp missing after composition")

print(
    "r41 unified composition: COMPLETE "
    "(r40 guard preserved + explicit user-triggered live foreign owner release + manual Start after repair)"
)
