from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
account = (ROOT / "src-tauri/src/codex_real_account.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-REVOCATION-REVIEW
required = [
    "CAS-APPS-MCP-AUTH-R25-REVOCATION",
    "apps_mcp_auth_r25_revocation_allows(",
    "should_clear_relogin(active_token_fp, revoked_fp, has_revocation)",
    "REVOKED_TOKEN_FP.load(Ordering::SeqCst)",
    "HAS_REVOCATION.load(Ordering::SeqCst)",
    "CAS-APPS-MCP-AUTH-R25-REVOCATION-TEST",
    "apps_mcp_auth_r25_known_revoked_bearer_fails_closed",
    "assert!(!apps_mcp_auth_r25_revocation_allows(0x1111, 0, true))",
    "assert!(!apps_mcp_auth_r25_revocation_allows(0x1111, 0x1111, true))",
    "assert!(apps_mcp_auth_r25_revocation_allows(0x2222, 0x1111, true))",
]
for marker in required:
    if marker not in account:
        raise SystemExit(f"r25 revocation review: missing invariant: {marker}")

# r25 must remain read-only with respect to the revocation state. It may consult
# atomics but must not clear them just because an MCP request arrived.
start = account.index("pub fn active_chatgpt_mcp_relay_auth()")
end = account.index("fn chatgpt_mcp_relay_auth_from_value", start)
relay_block = account[start:end]
for forbidden in ("clear_relogin_state()", "store(", "swap("):
    if forbidden in relay_block:
        raise SystemExit(f"r25 revocation review: relay auth path mutates revocation state: {forbidden}")

print("r25 Apps MCP revoked-bearer review: PASS")
