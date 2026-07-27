from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = ROOT / "src-tauri/src/codex_real_account.rs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = ACCOUNT.read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-REVOCATION
# A locally-unexpired JWT may still have been revoked server-side. The surrounding
# real-account state machine already records the bearer fingerprint after a ChatGPT
# backend 401. r25 must not proactively re-inject that same known-revoked bearer.
if "CAS-APPS-MCP-AUTH-R25-REVOCATION" not in text:
    text = replace_once(
        text,
        '''pub fn active_chatgpt_mcp_relay_auth() -> Option<(String, Option<String>)> {
    let paths = CodexPaths::from_home_env().ok()?;
    let value = read_auth(&paths.auth_json).ok()?;
    chatgpt_mcp_relay_auth_from_value(&value, chrono::Utc::now().timestamp())
}
''',
        '''pub fn active_chatgpt_mcp_relay_auth() -> Option<(String, Option<String>)> {
    let paths = CodexPaths::from_home_env().ok()?;
    let value = read_auth(&paths.auth_json).ok()?;
    // CAS-APPS-MCP-AUTH-R25-REVOCATION
    // Reuse the existing revocation fingerprint semantics without mutating/clearing
    // the state here. Unknown revocation fingerprint (0) also fails closed.
    if !apps_mcp_auth_r25_revocation_allows(
        access_token_fingerprint(&value),
        REVOKED_TOKEN_FP.load(Ordering::SeqCst),
        HAS_REVOCATION.load(Ordering::SeqCst),
    ) {
        return None;
    }
    chatgpt_mcp_relay_auth_from_value(&value, chrono::Utc::now().timestamp())
}

fn apps_mcp_auth_r25_revocation_allows(
    active_token_fp: u64,
    revoked_fp: u64,
    has_revocation: bool,
) -> bool {
    should_clear_relogin(active_token_fp, revoked_fp, has_revocation)
}
''',
        label="r25 active relay auth revocation gate",
    )

if "CAS-APPS-MCP-AUTH-R25-REVOCATION-TEST" not in text:
    text = replace_once(
        text,
        '''    #[test]
    fn snapshot_accepts_only_active_real_unexpired_chatgpt_auth() {''',
        '''    // CAS-APPS-MCP-AUTH-R25-REVOCATION-TEST
    #[test]
    fn apps_mcp_auth_r25_known_revoked_bearer_fails_closed() {
        assert!(apps_mcp_auth_r25_revocation_allows(0x1111, 0, false));
        assert!(!apps_mcp_auth_r25_revocation_allows(0x1111, 0, true));
        assert!(!apps_mcp_auth_r25_revocation_allows(0x1111, 0x1111, true));
        assert!(apps_mcp_auth_r25_revocation_allows(0x2222, 0x1111, true));
    }

    #[test]
    fn snapshot_accepts_only_active_real_unexpired_chatgpt_auth() {''',
        label="r25 account revocation regression",
    )

ACCOUNT.write_text(text, encoding="utf-8")

for marker in (
    "CAS-APPS-MCP-AUTH-R25-REVOCATION",
    "CAS-APPS-MCP-AUTH-R25-REVOCATION-TEST",
    "REVOKED_TOKEN_FP.load(Ordering::SeqCst)",
    "HAS_REVOCATION.load(Ordering::SeqCst)",
):
    if marker not in text:
        raise SystemExit(f"r25 revocation hardening marker missing: {marker}")

print("r25 Apps MCP revoked-bearer hardening: complete")
