from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = FORWARD.read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-REDIRECT-HELPER
# Keep the redirect security predicate separately testable. It intentionally returns
# true for non-MCP origins so r25 does not alter redirect semantics of other providers.
if "CAS-APPS-MCP-AUTH-R25-REDIRECT-HELPER" not in text:
    text = replace_once(
        text,
        '''const DEFAULT_OUTBOUND_USER_AGENT: &str = concat!("Codex-App-Transfer/", env!("CARGO_PKG_VERSION"));

impl ProxyState {''',
        '''const DEFAULT_OUTBOUND_USER_AGENT: &str = concat!("Codex-App-Transfer/", env!("CARGO_PKG_VERSION"));

// CAS-APPS-MCP-AUTH-R25-REDIRECT-HELPER
fn apps_mcp_redirect_target_allowed(origin: &reqwest::Url, next: &reqwest::Url) -> bool {
    let origin_is_apps_mcp = origin.scheme() == "https"
        && origin.host_str() == Some("chatgpt.com")
        && (origin.path() == "/backend-api/ps/mcp"
            || origin.path().starts_with("/backend-api/ps/mcp/"));
    if !origin_is_apps_mcp {
        return true;
    }
    next.scheme() == "https"
        && next.host_str() == Some("chatgpt.com")
        && next.port_or_known_default() == origin.port_or_known_default()
}

#[cfg(test)]
mod apps_mcp_auth_r25_redirect_tests {
    use super::*;

    #[test]
    fn synthesized_identity_never_crosses_origin_but_other_paths_keep_old_policy() {
        let origin = reqwest::Url::parse(
            "https://chatgpt.com/backend-api/ps/mcp/.well-known/oauth-protected-resource",
        )
        .unwrap();
        let same = reqwest::Url::parse("https://chatgpt.com/backend-api/ps/mcp/next").unwrap();
        let other_host = reqwest::Url::parse("https://example.com/next").unwrap();
        let other_scheme = reqwest::Url::parse("http://chatgpt.com/backend-api/ps/mcp/next").unwrap();
        let other_port = reqwest::Url::parse("https://chatgpt.com:444/backend-api/ps/mcp/next").unwrap();
        assert!(apps_mcp_redirect_target_allowed(&origin, &same));
        assert!(!apps_mcp_redirect_target_allowed(&origin, &other_host));
        assert!(!apps_mcp_redirect_target_allowed(&origin, &other_scheme));
        assert!(!apps_mcp_redirect_target_allowed(&origin, &other_port));

        let non_mcp = reqwest::Url::parse("https://chatgpt.com/backend-api/ps/plugins/installed").unwrap();
        assert!(apps_mcp_redirect_target_allowed(&non_mcp, &other_host));
    }
}

impl ProxyState {''',
        label="r25 redirect testable helper",
    )

# CAS-APPS-MCP-AUTH-R25-REDIRECT-GUARD
# reqwest 0.12 removes a fixed set of credential headers (including Authorization)
# when a redirect crosses host/scheme/port, but ChatGPT-Account-ID is a custom
# identity header and is not in that built-in strip list. r25 can synthesize that
# header, so an Apps MCP request must never carry the synthesized identity across
# origins. Restrict only redirect chains whose original request is the hosted Apps
# MCP namespace; all unrelated providers keep the existing redirect policy.
if "CAS-APPS-MCP-AUTH-R25-REDIRECT-GUARD" not in text:
    text = replace_once(
        text,
        '''                .redirect(reqwest::redirect::Policy::custom(|attempt| {
                    if attempt.previous().len() >= 5 {
                        return attempt.error("too many redirects".to_string());
                    }
                    let host = attempt.url().host_str().unwrap_or("").to_string();''',
        '''                .redirect(reqwest::redirect::Policy::custom(|attempt| {
                    if attempt.previous().len() >= 5 {
                        return attempt.error("too many redirects".to_string());
                    }
                    // CAS-APPS-MCP-AUTH-R25-REDIRECT-GUARD
                    if let Some(origin) = attempt.previous().first() {
                        if !apps_mcp_redirect_target_allowed(origin, attempt.url()) {
                            return attempt.error(
                                "Apps MCP cross-origin redirect blocked".to_string(),
                            );
                        }
                    }
                    let host = attempt.url().host_str().unwrap_or("").to_string();''',
        label="r25 redirect origin guard",
    )

# Mark both values synthesized from auth.json as sensitive. Exact markers are used
# rather than counting arbitrary set_sensitive calls, so future upstream headers
# cannot accidentally satisfy this security gate.
if "CAS-APPS-MCP-AUTH-R25-BEARER-SENSITIVE" not in text:
    text = replace_once(
        text,
        '''    let authorization = reqwest::header::HeaderValue::from_bytes(
        format!("Bearer {}", auth.access_token).as_bytes(),
    )
    .ok()?;''',
        '''    let mut authorization = reqwest::header::HeaderValue::from_bytes(
        format!("Bearer {}", auth.access_token).as_bytes(),
    )
    .ok()?;
    authorization.set_sensitive(true); // CAS-APPS-MCP-AUTH-R25-BEARER-SENSITIVE''',
        label="r25 bearer sensitivity",
    )

if "CAS-APPS-MCP-AUTH-R25-ACCOUNT-SENSITIVE" not in text:
    text = replace_once(
        text,
        '''            .filter(|value| !value.trim().is_empty())
            .and_then(|value| reqwest::header::HeaderValue::from_bytes(value.as_bytes()).ok())''',
        '''            .filter(|value| !value.trim().is_empty())
            .and_then(|value| reqwest::header::HeaderValue::from_bytes(value.as_bytes()).ok())
            .map(|mut value| {
                value.set_sensitive(true); // CAS-APPS-MCP-AUTH-R25-ACCOUNT-SENSITIVE
                value
            })''',
        label="r25 account-id sensitivity",
    )

# Behaviour-level sensitivity regression: source markers alone are not enough.
if "CAS-APPS-MCP-AUTH-R25-SENSITIVITY-TEST" not in text:
    text = replace_once(
        text,
        '''        assert_eq!(prepared.authorization, "Bearer token-from-auth-json");
        assert!(prepared.account_id.is_none());

        let malformed = prepare_chatgpt_mcp_relay_auth(''',
        '''        assert_eq!(prepared.authorization, "Bearer token-from-auth-json");
        assert!(prepared.authorization.is_sensitive());
        assert!(prepared.account_id.is_none());

        // CAS-APPS-MCP-AUTH-R25-SENSITIVITY-TEST
        let with_account = prepare_chatgpt_mcp_relay_auth(
            ChatgptMcpRelayAuth {
                access_token: "token-from-auth-json".to_string(),
                account_id: Some("account-local".to_string()),
            },
            &HeaderMap::new(),
        )
        .expect("valid bearer/account");
        assert!(with_account.authorization.is_sensitive());
        assert!(with_account.account_id.as_ref().unwrap().is_sensitive());

        let malformed = prepare_chatgpt_mcp_relay_auth(''',
        label="r25 sensitivity behaviour test",
    )

FORWARD.write_text(text, encoding="utf-8")

for marker in (
    "CAS-APPS-MCP-AUTH-R25-REDIRECT-HELPER",
    "CAS-APPS-MCP-AUTH-R25-REDIRECT-GUARD",
    "CAS-APPS-MCP-AUTH-R25-BEARER-SENSITIVE",
    "CAS-APPS-MCP-AUTH-R25-ACCOUNT-SENSITIVE",
    "CAS-APPS-MCP-AUTH-R25-SENSITIVITY-TEST",
):
    if marker not in text:
        raise SystemExit(f"r25 redirect/privacy hardening marker missing: {marker}")
if "Apps MCP cross-origin redirect blocked" not in text:
    raise SystemExit("r25 redirect hardening error path missing")

# Keep all credential-boundary hardening in one replayable bundle. The composer
# already invokes this script for every r25 materialization; chaining the trace
# privacy patch here ensures future official rebases cannot stamp r25 while omitting
# account-id redaction, even before workflow-specific checks run.
for companion in (
    "scripts/apply_apps_mcp_auth_r25_trace_privacy.py",
    "scripts/apply_apps_mcp_auth_r25_trace_privacy_review.py",
):
    companion_path = ROOT / companion
    if not companion_path.is_file():
        raise SystemExit(f"r25 hardening companion missing: {companion}")
    print(f"applying {companion}")
    runpy.run_path(str(companion_path), run_name="__main__")

print("r25 Apps MCP redirect/privacy hardening: complete")
