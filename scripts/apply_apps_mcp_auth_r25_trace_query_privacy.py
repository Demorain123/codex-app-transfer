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

# CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY
# OAuth `state` is a request/callback binding value and can be security-sensitive.
# For the hosted Apps MCP namespace, no query value is required to diagnose routing;
# omit query+fragment completely. All non-MCP ChatGPT backend traces retain the
# existing fine-grained redact_credential_params behavior.
if "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY" not in text:
    anchor = '''/// 一条 chatgpt-backend passthrough trace → 诊断 JSON(MOC-125)。结构同 forward
/// (inbound/outbound/response),但 header 用 [`headers_to_json_passthrough`](cookie 友好脱敏)。
pub(crate) fn build_chatgpt_backend_trace_value(input: &ForwardTraceInput, seq: u64) -> Value {'''
    replacement = '''// CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY
fn apps_mcp_safe_trace_route(raw: &str) -> String {
    let relative_path = raw.split(['?', '#']).next().unwrap_or(raw);
    if relative_path == "/backend-api/ps/mcp"
        || relative_path.starts_with("/backend-api/ps/mcp/")
    {
        return relative_path.to_string();
    }

    if let Ok(mut url) = reqwest::Url::parse(raw) {
        if url.scheme() == "https"
            && url.host_str() == Some("chatgpt.com")
            && (url.path() == "/backend-api/ps/mcp"
                || url.path().starts_with("/backend-api/ps/mcp/"))
        {
            url.set_query(None);
            url.set_fragment(None);
            return url.to_string();
        }
    }

    redact_credential_params(raw).0
}

/// 一条 chatgpt-backend passthrough trace → 诊断 JSON(MOC-125)。结构同 forward
/// (inbound/outbound/response),但 header 用 [`headers_to_json_passthrough`](cookie 友好脱敏)。
pub(crate) fn build_chatgpt_backend_trace_value(input: &ForwardTraceInput, seq: u64) -> Value {'''
    text = replace_once(text, anchor, replacement, label="r25 Apps MCP trace route helper")

    text = replace_once(
        text,
        '"client_path": redact_credential_params(input.client_path).0,',
        '"client_path": apps_mcp_safe_trace_route(input.client_path),',
        label="r25 inbound trace route privacy",
    )
    text = replace_once(
        text,
        '"url": redact_credential_params(input.upstream_url).0,',
        '"url": apps_mcp_safe_trace_route(input.upstream_url),',
        label="r25 outbound trace route privacy",
    )

if "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY-TEST" not in text:
    test_anchor = '''    // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-TEST
    #[test]
    fn apps_mcp_auth_r25_chatgpt_account_id_is_redacted_in_all_diagnostic_header_paths() {'''
    test_block = '''    // CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY-TEST
    #[test]
    fn apps_mcp_auth_r25_trace_omits_mcp_oauth_query_state_without_changing_other_paths() {
        let relative = apps_mcp_safe_trace_route(
            "/backend-api/ps/mcp/.well-known?state=private-state&code=secret-code#fragment",
        );
        assert_eq!(relative, "/backend-api/ps/mcp/.well-known");
        assert!(!relative.contains("private-state"));
        assert!(!relative.contains("secret-code"));

        let absolute = apps_mcp_safe_trace_route(
            "https://chatgpt.com/backend-api/ps/mcp/callback?state=private-state&code=secret-code#fragment",
        );
        assert!(absolute.starts_with("https://chatgpt.com/backend-api/ps/mcp/callback"));
        assert!(!absolute.contains('?'));
        assert!(!absolute.contains('#'));
        assert!(!absolute.contains("private-state"));

        // Preserve existing non-MCP semantics: generic `state` remains visible, while
        // the pre-existing credential redactor still masks an OAuth authorization code.
        let other = apps_mcp_safe_trace_route(
            "/backend-api/ps/plugins/installed?state=diagnostic-state&code=secret-code",
        );
        assert!(other.contains("state=diagnostic-state"));
        assert!(other.contains("code=***"));
        assert!(!other.contains("secret-code"));
    }

'''
    text = replace_once(
        text,
        test_anchor,
        test_block + test_anchor,
        label="r25 Apps MCP trace query behavior test",
    )

DIAG.write_text(text, encoding="utf-8")

for marker in (
    "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY",
    "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY-TEST",
    "apps_mcp_safe_trace_route(input.client_path)",
    "apps_mcp_safe_trace_route(input.upstream_url)",
):
    if marker not in text:
        raise SystemExit(f"r25 trace query privacy marker missing: {marker}")

print("r25 Apps MCP trace OAuth query privacy: complete")
