from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = FORWARD.read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-REDIRECT
# reqwest 0.12 removes a fixed set of credential headers (including Authorization)
# when a redirect crosses host/scheme/port, but ChatGPT-Account-ID is a custom
# identity header and is not in that built-in strip list. r25 can synthesize that
# header, so an Apps MCP request must never carry the synthesized identity across
# origins. Restrict only redirect chains whose original request is the hosted Apps
# MCP namespace; all unrelated providers keep the existing redirect policy.
if "CAS-APPS-MCP-AUTH-R25-REDIRECT" not in text:
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
                    // CAS-APPS-MCP-AUTH-R25-REDIRECT
                    if let Some(origin) = attempt.previous().first() {
                        let origin_is_apps_mcp = origin.scheme() == "https"
                            && origin.host_str() == Some("chatgpt.com")
                            && (origin.path() == "/backend-api/ps/mcp"
                                || origin.path().starts_with("/backend-api/ps/mcp/"));
                        let next_same_origin = attempt.url().scheme() == "https"
                            && attempt.url().host_str() == Some("chatgpt.com")
                            && attempt.url().port_or_known_default()
                                == origin.port_or_known_default();
                        if origin_is_apps_mcp && !next_same_origin {
                            return attempt.error(
                                "Apps MCP cross-origin redirect blocked".to_string(),
                            );
                        }
                    }
                    let host = attempt.url().host_str().unwrap_or("").to_string();''',
        label="r25 redirect origin guard",
    )

# Mark both values synthesized from auth.json as sensitive. This does not replace
# the redirect guard above; it additionally prevents accidental Debug/HTTP2-table
# exposure by downstream libraries.
if text.count("set_sensitive(true)") < 2:
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
    authorization.set_sensitive(true);''',
        label="r25 bearer sensitivity",
    )
    text = replace_once(
        text,
        '''            .filter(|value| !value.trim().is_empty())
            .and_then(|value| reqwest::header::HeaderValue::from_bytes(value.as_bytes()).ok())''',
        '''            .filter(|value| !value.trim().is_empty())
            .and_then(|value| reqwest::header::HeaderValue::from_bytes(value.as_bytes()).ok())
            .map(|mut value| {
                value.set_sensitive(true);
                value
            })''',
        label="r25 account-id sensitivity",
    )

FORWARD.write_text(text, encoding="utf-8")

if "CAS-APPS-MCP-AUTH-R25-REDIRECT" not in text:
    raise SystemExit("r25 redirect hardening marker missing")
if "Apps MCP cross-origin redirect blocked" not in text:
    raise SystemExit("r25 redirect hardening error path missing")
if text.count("set_sensitive(true)") < 2:
    raise SystemExit("r25 synthesized credential headers are not both marked sensitive")

print("r25 Apps MCP redirect/privacy hardening: complete")
