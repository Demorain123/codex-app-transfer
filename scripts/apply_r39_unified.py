from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r39 required overlay/composer missing: {rel}")
    print(f"r39 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r39 inherited successful no-op: {rel}")


# Materialize the complete tested r38 feature set first. r39 is deliberately a narrow
# outer shell: proxy ownership/teardown, bind-busy policy, stronger same-port stress.
run("scripts/apply_r38_unified.py")

REVISION.write_text("39\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

run("scripts/apply_r39_proxy_owner_thread.py")
run("scripts/apply_r39_bind_busy_policy.py")
run("scripts/apply_r39_proxy_owner_thread_tests.py")
run("scripts/review_r39_proxy_owner_thread.py")

required = {
    "src-tauri/src/proxy_runner.rs": [
        "CAS-R39-PROXY-OWNER-THREAD",
        "cas-proxy-owner-",
        "owner_thread_joined",
        "shutdown_signal_received",
        "owner_runtime_shutdown_complete",
        "port_release_verified",
        "listener_residue_detected",
        "CAS-R39-PROXY-OWNER-THREAD-TESTS",
        "proxy_lifecycle_r39_owner_thread_join_rebind_100_generations",
    ],
    "src-tauri/src/admin/handlers/proxy.rs": [
        "CAS-R39-BIND-BUSY-NONRETRYABLE",
        "bind_busy_nonretryable",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R39-BINDER-TERMINOLOGY",
        "binder_pid=",
        "classification=unresolved_listener_residue",
    ],
    "src-tauri/src/windows_tcp_owner.rs": [
        "CAS-R38-WINDOWS-TCP-OWNER",
        "GetExtendedTcpTable",
        "TCP_TABLE_OWNER_PID_LISTENER",
    ],
    "src-tauri/src/codex_quota_injector.rs": [
        "CAS-R38-CODEX-USAGE-INJECTOR-COMPAT",
        "QuotaInjectorStatus",
    ],
    "frontend/src/i18n/zh.ts": ["Sub2API Grok Compat r39 · v2.4.5+39"],
    "frontend/src/i18n/en.ts": ["Sub2API Grok Compat r39 · v2.4.5+39"],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r39 materialization missing marker in {rel}: {marker}")

proxy_prefix = (ROOT / "src-tauri/src/proxy_runner.rs").read_text(encoding="utf-8").split(
    "struct ResolverSnapshot {", 1
)[0]
for forbidden in (
    "runtime: tokio::runtime::Runtime",
    "inside_async_runtime",
    '"background_async_safe"',
    "h.runtime.shutdown_background()",
):
    if forbidden in proxy_prefix:
        raise SystemExit(f"r39 materialization retained forbidden lifecycle pattern: {forbidden}")

handler = (ROOT / "src-tauri/src/admin/handlers/proxy.rs").read_text(encoding="utf-8")
if "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];" in handler:
    raise SystemExit("r39 materialization retained blind address-in-use retry schedule")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=39" not in version or "app_version=2.4.5+39" not in version:
    raise SystemExit("r39 visible/package version stamp missing after composition")

print(
    "r39 unified composition: COMPLETE "
    "(r38 preserved + single owner-thread proxy + non-retryable bind-busy + 100x same-port stress)"
)
