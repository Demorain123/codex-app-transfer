from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "crates/proxy/src/diagnostics.rs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = DIAG.read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-GENERIC
# `ChatGPT-Account-ID` is identity metadata, not an auth secret by conventional
# name heuristics. r25 may synthesize it from auth.json, so generic forward traces
# must treat it as credential-bearing even though it lacks token/secret/password.
if "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-GENERIC" not in text:
    text = replace_once(
        text,
        '''                | "x-goog-api-key"
                | "cookie"
                | "set-cookie"''',
        '''                | "x-goog-api-key"
                | "cookie"
                | "set-cookie"
                | "chatgpt-account-id" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-GENERIC''',
        label="r25 generic forward header privacy",
    )

# CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-MCP
# Browser/MCP recorder traces use a second wide-header predicate after recursive
# JSON key scrubbing. Add the normalized custom account header there as well.
if "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-MCP" not in text:
    text = replace_once(
        text,
        '''    norm.contains("cookie") || norm.contains("session") || norm == "proxyauthorization"
}''',
        '''    norm.contains("cookie")
        || norm.contains("session")
        || norm == "proxyauthorization"
        || norm == "chatgptaccountid" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-MCP
}''',
        label="r25 MCP recorder account-id privacy",
    )

# CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-PASSTHROUGH
# ChatGPT backend traces deliberately retain Cookie/Authorization structure, then
# apply a separate credential predicate to other headers. Account ID has no safe
# diagnostic value here, so mask it completely rather than fingerprinting it.
if "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-PASSTHROUGH" not in text:
    text = replace_once(
        text,
        '''                        | "anthropic-api-key"
                        | "x-goog-api-key"
                ) || lower.starts_with("x-auth-")''',
        '''                        | "anthropic-api-key"
                        | "x-goog-api-key"
                        | "chatgpt-account-id" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-PASSTHROUGH
                ) || lower.starts_with("x-auth-")''',
        label="r25 ChatGPT passthrough account-id privacy",
    )

# Behaviour regressions live in diagnostics.rs's existing test module so they execute
# in the same crate without exposing private scrub helpers. The test name intentionally
# includes `apps_mcp_auth_r25` so the dedicated filtered proxy test cannot skip it.
if "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-TEST" not in text:
    test_anchor = '''    #[test]
    fn passthrough_non_standard_cookie_and_credential_still_redacted() {'''
    test_block = '''    // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-TEST
    #[test]
    fn apps_mcp_auth_r25_chatgpt_account_id_is_redacted_in_all_diagnostic_header_paths() {
        let mut h = reqwest::header::HeaderMap::new();
        h.insert("chatgpt-account-id", "acct-r25-private-123".parse().unwrap());
        h.insert("content-type", "application/json".parse().unwrap());

        let generic = headers_to_json_redacted(&h);
        let generic_s = serde_json::to_string(&generic).unwrap();
        assert!(!generic_s.contains("acct-r25-private-123"), "generic trace leaked account id: {generic_s}");
        assert!(generic["chatgpt-account-id"].as_str().unwrap().starts_with("***"));

        let passthrough = headers_to_json_passthrough(&h);
        let passthrough_s = serde_json::to_string(&passthrough).unwrap();
        assert!(!passthrough_s.contains("acct-r25-private-123"), "passthrough trace leaked account id: {passthrough_s}");
        assert!(passthrough["chatgpt-account-id"].as_str().unwrap().starts_with("***"));

        let mut mcp = json!({
            "kind": "fetch",
            "req_headers": {
                "ChatGPT-Account-ID": "acct-r25-private-123",
                "content-type": "application/json"
            }
        });
        redact_mcp_value(&mut mcp);
        assert_eq!(mcp["req_headers"]["ChatGPT-Account-ID"], "***");
        assert_eq!(mcp["req_headers"]["content-type"], "application/json");
        assert!(!serde_json::to_string(&mcp).unwrap().contains("acct-r25-private-123"));
    }

'''
    text = replace_once(
        text,
        test_anchor,
        test_block + test_anchor,
        label="r25 diagnostic privacy behavior test",
    )

DIAG.write_text(text, encoding="utf-8")

for marker in (
    "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-GENERIC",
    "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-MCP",
    "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-PASSTHROUGH",
    "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-TEST",
):
    if marker not in text:
        raise SystemExit(f"r25 trace privacy marker missing: {marker}")

print("r25 Apps MCP diagnostic trace privacy hardening: complete")
