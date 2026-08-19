from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "src-tauri/src/windows_tcp_owner.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PROXY = ROOT / "src-tauri/src/proxy_runner.rs"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"

owner = OWNER.read_text(encoding="utf-8")
chain = CHAIN.read_text(encoding="utf-8")
proxy = PROXY.read_text(encoding="utf-8")
zh = ZH.read_text(encoding="utf-8")
en = EN.read_text(encoding="utf-8")

for token in [
    "CAS-R41-EXPLICIT-PORT-REPAIR",
    "terminate_live_foreign_listener_owner",
    "PROCESS_TERMINATE",
    "TerminateProcess",
    "expected_pid == std::process::id()",
    "expected_pid == 0 || expected_pid <= 4",
    "protected_repair_owner_name",
    "listener owner changed before repair",
    "listener owner changed during repair",
    "windows_port_repair_r41_rejects_self_owner",
    "windows_port_repair_r41_terminates_explicit_foreign_owner",
]:
    if token not in owner:
        raise SystemExit(f"r41 review: owner safety marker missing: {token}")

for token in [
    "CAS-R41-EXPLICIT-PORT-REPAIR",
    '"transfer_port_occupied_live"',
    '"release_foreign_port_owner"',
    "terminate_live_foreign_listener_owner(port, pid)",
    "现在可重新点击‘启动转发’",
    '"preserve_stale_listener_evidence"',
    '"refuse_self_port_owner_termination"',
]:
    if token not in chain:
        raise SystemExit(f"r41 review: recovery marker missing: {token}")

if "terminate_live_foreign_listener_owner" in proxy:
    raise SystemExit("r41 review: explicit termination primitive leaked into normal proxy start/stop path")

# Preserve the user's requested control boundary: process termination is allowed only
# after the explicit chain-health repair endpoint is invoked. No background watchdog,
# start retry, or automatic port switching may call it.
repair_call_count = chain.count("terminate_live_foreign_listener_owner(port, pid)")
if repair_call_count != 1:
    raise SystemExit(f"r41 review: explicit repair call count={repair_call_count}, expected 1")

# Stale/dead binder PIDs remain evidence-only. Inspect the actual recovery match arm,
# not earlier classification code that happens to mention the same token.
stale_arm = '        "transfer_port_stale_owner" => {'
stale_pos = chain.find(stale_arm)
if stale_pos < 0:
    raise SystemExit("r41 review: stale-owner recovery arm missing")
stale_window = chain[stale_pos : stale_pos + 1200]
if "TerminateProcess" in stale_window or "terminate_live_foreign_listener_owner" in stale_window:
    raise SystemExit("r41 review: stale/dead binder recovery arm must not terminate a PID")
if "preserve_stale_listener_evidence" not in stale_window:
    raise SystemExit("r41 review: stale/dead binder recovery arm must preserve evidence")

# Do not reintroduce the old conflict-masking behavior.
combined = owner + "\n" + chain + "\n" + proxy
for forbidden in [
    "set_reuseaddr(true)",
    "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
]:
    if forbidden in combined:
        raise SystemExit(f"r41 review: forbidden conflict-masking primitive present: {forbidden}")

if "'chainHealth.recover': '尝试修复'" not in zh:
    raise SystemExit("r41 review: Chinese explicit repair button label missing")
if "'chainHealth.recover': 'Try repair'" not in en:
    raise SystemExit("r41 review: English explicit repair button label missing")

print("r41 explicit port repair safety review: PASS")
