from __future__ import annotations

# MODERN-R39-LIFECYCLE-SELECTIVE-CARRY-FORWARD
#
# r82+ intentionally stopped replaying recursive historical r24-r41 unified
# drivers. That was correct for avoiding stale provider/UI transforms, but it
# also dropped the independently-tested r38/r39 fixed-port proxy lifecycle.
#
# Re-materialize ONLY the reviewed lifecycle/recovery leaf transforms needed by
# modern r94. Do not stamp an old revision, do not call apply_r38_unified.py or
# apply_r39_unified.py, and do not replay unrelated r24-r41 behavior.

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]


def run_leaf(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"modern r39 lifecycle required leaf missing: {rel}")
    print(f"modern-r39-lifecycle leaf={rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise SystemExit(
                f"modern r39 lifecycle leaf failed: {rel} exit={exc.code}"
            ) from exc


# 1) Native read-only Windows listener/binder attribution. Use the modern
#    substrate-only leaf: the historical r38 leaf also expected an r38-specific
#    proxy_runner lifecycle anchor and is intentionally not replayed here.
run_leaf("scripts/apply_r39_windows_owner_selective_modern.py")

# 2) Teach Chain Health/Recovery to distinguish a free stopped Transfer from a
#    live external binder or unresolved listener residue. Never kill, port-hop,
#    or SO_REUSEADDR around an ownership conflict.
run_leaf("scripts/apply_r38_recovery_port_classification.py")
run_leaf("scripts/apply_r38_recovery_async_stop.py")

# 3) Final r39 lifecycle owner: listener + axum server + Tokio runtime remain on
#    one dedicated OS thread. Stop signals it, joins it, then verifies same-port
#    bindability before another generation may publish.
run_leaf("scripts/apply_r39_proxy_owner_thread.py")
run_leaf("scripts/apply_r39_r25_replay_marker_prep.py")
run_leaf("scripts/apply_r39_owner_thread_state_guard.py")

# 4) A 10048/address-in-use result is ownership evidence, not a transient retry
#    condition. One bind attempt only; Chain Health explains binder evidence.
run_leaf("scripts/apply_r39_bind_busy_policy.py")

# 5) Preserve the original 100-generation same-port owner-thread regression test.
run_leaf("scripts/apply_r39_proxy_owner_thread_tests.py")


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"modern r39 lifecycle postcondition file missing: {rel}")
    return path.read_text(encoding="utf-8")


proxy_runner = read("src-tauri/src/proxy_runner.rs")
for marker in (
    "CAS-R39-PROXY-OWNER-THREAD",
    "CAS-R39-OWNER-THREAD-STATE-GUARD",
    "CAS-R39-PROXY-OWNER-THREAD-TESTS",
    "CAS-APPS-MCP-AUTH-R25-WIRE",
    "cas-proxy-owner-",
    "owner_thread_joined",
    "shutdown_signal_received",
    "owner_runtime_shutdown_complete",
    "port_release_verified",
    "listener_residue_detected",
    "finished_owner_generation_detected",
    "proxy_lifecycle_r39_owner_thread_join_rebind_100_generations",
):
    if marker not in proxy_runner:
        raise SystemExit(f"modern r39 lifecycle proxy_runner invariant missing: {marker}")

proxy_prefix = proxy_runner.split("struct ResolverSnapshot {", 1)[0]
for forbidden in (
    "runtime: tokio::runtime::Runtime",
    "h.runtime.shutdown_background()",
):
    if forbidden in proxy_prefix:
        raise SystemExit(
            f"modern r39 lifecycle retained obsolete proxy ownership: {forbidden}"
        )

proxy_handler = read("src-tauri/src/admin/handlers/proxy.rs")
for marker in (
    "CAS-R39-BIND-BUSY-NONRETRYABLE",
    "bind_busy_nonretryable",
    "manager.stop().map_err",
    "exactly one bind attempt",
):
    if marker not in proxy_handler:
        raise SystemExit(f"modern r39 lifecycle proxy handler invariant missing: {marker}")
for forbidden in (
    "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
    "[proxy-lifecycle-r28] bind busy requested_port=",
):
    if forbidden in proxy_handler:
        raise SystemExit(f"modern r39 lifecycle retained blind bind retry: {forbidden}")

chain = read("src-tauri/src/admin/handlers/chain_health.rs")
for marker in (
    "CAS-R38-RECOVERY-PORT-CLASSIFICATION",
    "CAS-R38-RECOVERY-ASYNC-STOP",
    "CAS-R39-BINDER-TERMINOLOGY",
    "transfer_port_occupied_live",
    "transfer_port_stale_owner",
    "preserve_live_port_owner",
    "preserve_stale_listener_evidence",
    "spawn_blocking(move || manager.stop())",
    "binder_pid=",
    "classification=unresolved_listener_residue",
):
    if marker not in chain:
        raise SystemExit(f"modern r39 lifecycle chain-health invariant missing: {marker}")

owner = read("src-tauri/src/windows_tcp_owner.rs")
for marker in (
    "CAS-R38-WINDOWS-TCP-OWNER",
    "GetExtendedTcpTable",
    "TCP_TABLE_OWNER_PID_LISTENER",
    "listener_owner_evidence",
):
    if marker not in owner:
        raise SystemExit(f"modern r39 lifecycle Windows owner invariant missing: {marker}")

cargo = read("src-tauri/Cargo.toml")
if "Win32_NetworkManagement_IpHelper" not in cargo:
    raise SystemExit("modern r39 lifecycle Cargo IP Helper feature missing")

main = read("src-tauri/src/main.rs")
if "mod windows_tcp_owner" not in main:
    raise SystemExit("modern r39 lifecycle Windows owner module registration missing")

page = read("frontend/src/pages/ProxyPage.vue")
if "chainHealth.recovering" not in page:
    raise SystemExit("modern r39 lifecycle recovery progress UI marker missing")

print("MODERN_R39_LIFECYCLE_SELECTIVE_CARRY_FORWARD_PASS")
print("- dedicated owner-thread listener lifecycle restored without recursive historical replay")
print("- stop joins owner and verifies same-port release before rebind")
print("- Windows binder PID evidence restored for occupied/residual listeners")
print("- 10048/address-in-use is single-attempt nonretryable; no blind retry loop")
print("- recovery preserves live/stale owner evidence instead of hammering bind")
