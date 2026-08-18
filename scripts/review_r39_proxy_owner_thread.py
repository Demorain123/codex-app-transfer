from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "src-tauri/src/proxy_runner.rs"
HANDLER = ROOT / "src-tauri/src/admin/handlers/proxy.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"

proxy = PROXY.read_text(encoding="utf-8")
handler = HANDLER.read_text(encoding="utf-8")
chain = CHAIN.read_text(encoding="utf-8")

required_proxy = [
    "CAS-R39-PROXY-OWNER-THREAD",
    "cas-proxy-owner-",
    "new_current_thread()",
    "owner_thread_joined",
    "shutdown_signal_received",
    "server_grace_timeout",
    "server_future_dropped",
    "owner_runtime_shutdown_complete",
    "owner_thread_exit",
    "port_release_verified",
    "listener_residue_detected",
    "CAS-R39-PROXY-OWNER-THREAD-TESTS",
    "proxy_lifecycle_r39_owner_thread_join_rebind_100_generations",
    "0..100u64",
]
for token in required_proxy:
    if token not in proxy:
        raise SystemExit(f"r39 review: proxy marker missing: {token}")

prefix = proxy.split("struct ResolverSnapshot {", 1)[0]
for forbidden in [
    "runtime: tokio::runtime::Runtime",
    "inside_async_runtime",
    '"background_async_safe"',
    "h.runtime.shutdown_background()",
]:
    if forbidden in prefix:
        raise SystemExit(f"r39 review: forbidden cross-owner runtime pattern survived: {forbidden}")

join_index = prefix.find("owner_thread_joined")
probe_index = prefix.find("let released = wait_until_port_bindable")
if join_index < 0 or probe_index < 0 or join_index > probe_index:
    raise SystemExit("r39 review: same-port release probe must occur after owner-thread join")

for token in [
    "CAS-R39-BIND-BUSY-NONRETRYABLE",
    "bind_busy_nonretryable",
    "manager.stop().map_err",
]:
    if token not in handler:
        raise SystemExit(f"r39 review: handler marker missing: {token}")

for forbidden in [
    "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
    "[proxy-lifecycle-r28] bind busy requested_port=",
]:
    if forbidden in handler:
        raise SystemExit(f"r39 review: blind address-in-use retry survived: {forbidden}")

for token in [
    "CAS-R39-BINDER-TERMINOLOGY",
    "binder_pid=",
    "classification=unresolved_listener_residue",
]:
    if token not in chain:
        raise SystemExit(f"r39 review: chain-health binder marker missing: {token}")

print("r39 proxy owner-thread review: PASS")
