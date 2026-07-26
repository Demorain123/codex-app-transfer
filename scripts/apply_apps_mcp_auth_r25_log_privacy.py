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

# CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY
# Keep existing telemetry behavior for every non-MCP ChatGPT backend path, but never
# persist hosted Apps MCP query values. OAuth-style query parameters can contain
# authorization codes/state/correlation material and the dedicated MCP diagnostics
# already intentionally operate on path-only identifiers.
if "CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY" not in text:
    anchor = '''fn is_chatgpt_mcp_backend_path(path: &str) -> bool {
    let p = diagnostic_path_only(path);
    p == "/backend-api/ps/mcp" || p.starts_with("/backend-api/ps/mcp/")
}
'''
    replacement = anchor + '''
// CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY
fn apps_mcp_safe_relay_log_path(path: &str) -> &str {
    if is_chatgpt_mcp_backend_path(path) {
        diagnostic_path_only(path)
    } else {
        path
    }
}

fn apps_mcp_safe_reqwest_error(path: &str, error: reqwest::Error) -> reqwest::Error {
    if is_chatgpt_mcp_backend_path(path) {
        error.without_url()
    } else {
        error
    }
}

#[cfg(test)]
mod apps_mcp_auth_r25_log_privacy_tests {
    use super::*;

    #[test]
    fn apps_mcp_auth_r25_relay_logs_strip_mcp_query_but_preserve_other_backend_paths() {
        assert_eq!(
            apps_mcp_safe_relay_log_path(
                "/backend-api/ps/mcp/.well-known?code=secret-code&state=private-state"
            ),
            "/backend-api/ps/mcp/.well-known"
        );
        assert_eq!(
            apps_mcp_safe_relay_log_path("/backend-api/ps/plugins/installed?view=all"),
            "/backend-api/ps/plugins/installed?view=all"
        );
    }
}
'''
    text = replace_once(text, anchor, replacement, label="r25 MCP relay log privacy helper")

if "CAS-APPS-MCP-AUTH-R25-LOG-SAFE-PATH-WIRE" not in text:
    text = replace_once(
        text,
        '''    let upstream = format!("https://chatgpt.com{client_path}");
    let telemetry = proxy_telemetry();
    telemetry.logs.add(
        "INFO",
        format!("[chatgpt-relay] {method} {client_path} → {upstream}"),
    );''',
        '''    let upstream = format!("https://chatgpt.com{client_path}");
    // CAS-APPS-MCP-AUTH-R25-LOG-SAFE-PATH-WIRE
    // The real upstream keeps its full query; only human-readable local telemetry
    // drops Apps MCP query values. Other ChatGPT backend log paths are unchanged.
    let relay_log_path = apps_mcp_safe_relay_log_path(client_path);
    let relay_log_upstream = format!("https://chatgpt.com{relay_log_path}");
    let telemetry = proxy_telemetry();
    telemetry.logs.add(
        "INFO",
        format!("[chatgpt-relay] {method} {relay_log_path} → {relay_log_upstream}"),
    );''',
        label="r25 initial ChatGPT relay telemetry path",
    )

    text = replace_once(
        text,
        '''            "[chatgpt-relay] resp {status} {client_path} ({} bytes)",''',
        '''            "[chatgpt-relay] resp {status} {relay_log_path} ({} bytes)",''',
        label="r25 response ChatGPT relay telemetry path",
    )

    text = replace_once(
        text,
        '''                    "[chatgpt-relay] 上游 401 → chatgpt 账号 token 服务端失效,已回灌 relogin_required(后续 401 静默): {client_path}"''',
        '''                    "[chatgpt-relay] 上游 401 → chatgpt 账号 token 服务端失效,已回灌 relogin_required(后续 401 静默): {relay_log_path}"''',
        label="r25 401 ChatGPT relay telemetry path",
    )

# CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY
# reqwest::Error can retain/display the full request URL. Strip it before the common
# ForwardError telemetry path can stringify an Apps MCP failure; preserve existing
# URL-rich diagnostics for all non-MCP requests.
if "CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY" not in text:
    text = replace_once(
        text,
        '''    let req = rb.build()?;''',
        '''    let req = rb
        .build()
        .map_err(|e| ForwardError::Upstream(apps_mcp_safe_reqwest_error(client_path, e)))?; // CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY''',
        label="r25 request-build error URL privacy",
    )
    text = replace_once(
        text,
        '''    let resp = state.http.execute(req).await?;''',
        '''    let resp = state
        .http
        .execute(req)
        .await
        .map_err(|e| ForwardError::Upstream(apps_mcp_safe_reqwest_error(client_path, e)))?;''',
        label="r25 execute error URL privacy",
    )
    text = replace_once(
        text,
        '''    let resp_body = resp.bytes().await.map_err(ForwardError::Upstream)?;''',
        '''    let resp_body = resp
        .bytes()
        .await
        .map_err(|e| ForwardError::Upstream(apps_mcp_safe_reqwest_error(client_path, e)))?;''',
        label="r25 response-body error URL privacy",
    )

FORWARD.write_text(text, encoding="utf-8")

for marker in (
    "CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY",
    "CAS-APPS-MCP-AUTH-R25-LOG-SAFE-PATH-WIRE",
    "CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY",
    "apps_mcp_auth_r25_relay_logs_strip_mcp_query_but_preserve_other_backend_paths",
    "apps_mcp_safe_reqwest_error(client_path, e)",
):
    if marker not in text:
        raise SystemExit(f"r25 relay log privacy marker missing: {marker}")

print("r25 Apps MCP relay telemetry/error URL privacy: complete")
