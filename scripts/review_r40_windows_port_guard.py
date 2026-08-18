from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "src-tauri/src/windows_tcp_owner.rs"
PROXY = ROOT / "src-tauri/src/proxy_runner.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"

owner = OWNER.read_text(encoding="utf-8")
proxy = PROXY.read_text(encoding="utf-8")
chain = CHAIN.read_text(encoding="utf-8")

for token in [
    "CAS-R40-WINDOWS-PORT-GUARD",
    "GetHandleInformation",
    "SetHandleInformation",
    "HANDLE_FLAG_INHERIT",
    "harden_socket_inheritance",
    "owner_class=",
    "foreign_live",
    "self_live",
    "stale_binder",
    "recommended_action=stop_foreign_owner_safely",
    "recommended_action=preserve_evidence_no_pid_kill",
    "windows_port_guard_r40_clears_inherit_bit",
    "windows_port_guard_r40_classifies_foreign_and_stale_binders",
]:
    if token not in owner:
        raise SystemExit(f"r40 review: Windows owner/guard marker missing: {token}")

for token in [
    "CAS-R39-PROXY-OWNER-THREAD",
    "CAS-R40-WINDOWS-PORT-GUARD",
    "AsRawSocket",
    "listener_handle_guard",
    "listener_handle_guard_failed",
    "listener_owner_evidence_for",
    "owner_thread_joined",
    "port_release_verified",
    "listener_residue_detected",
]:
    if token not in proxy:
        raise SystemExit(f"r40 review: proxy marker missing: {token}")

for token in [
    "CAS-R39-BINDER-TERMINOLOGY",
    "CAS-R40-PORT-OWNER-CLASSIFICATION",
    "owner_class=foreign_live",
    "owner_class=stale_binder",
    "recommended_action=stop_foreign_owner_safely",
    "recommended_action=preserve_evidence_no_pid_kill",
]:
    if token not in chain:
        raise SystemExit(f"r40 review: chain-health marker missing: {token}")

# Safety invariants: r40 improves attribution/hardening, but does not take ownership
# of arbitrary foreign processes or hide a bind conflict by changing socket semantics.
combined = owner + "\n" + proxy + "\n" + chain
for forbidden in [
    "TerminateProcess(",
    "taskkill",
    "Stop-Process",
    "SO_REUSEADDR",
    "set_reuseaddr(true)",
]:
    if forbidden in combined:
        raise SystemExit(f"r40 review: unsafe automatic recovery primitive introduced: {forbidden}")

# The handle guard has to execute after bind succeeds but before the listener is
# published to the manager/UI.
guard_index = proxy.find("listener_handle_guard")
publish_index = proxy.find("listener_published")
if guard_index < 0 or publish_index < 0 or guard_index > publish_index:
    raise SystemExit("r40 review: listener handle guard must run before listener publication")

# Preserve the r39 teardown barrier; r40 is an outer defensive shell, not a rewrite.
join_index = proxy.find("owner_thread_joined")
release_index = proxy.find("let released = wait_until_port_bindable")
if join_index < 0 or release_index < 0 or join_index > release_index:
    raise SystemExit("r40 review: r39 owner-thread join must remain before port release probe")

print("r40 Windows port guard review: PASS")
