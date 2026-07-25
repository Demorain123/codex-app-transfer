#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-MCP-RELAY-DIAG-R20-HOOK"
RESOLVE_MARKER = "CAS-MCP-RELAY-DIAG-R20-RESOLVE"
PRIVACY_MARKER = "CAS-MCP-RELAY-DIAG-R20-QUERY-PRIVACY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r20 mcp diag: anchor not found: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"r20 mcp diag: anchor not unique: {label} count={text.count(old)}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    present = [marker in text for marker in (MARKER, RESOLVE_MARKER, PRIVACY_MARKER)]
    if any(present):
        if not all(present):
            raise SystemExit(
                "r20 mcp diag: partial/old generated diagnostic detected; refusing to silently accept it"
            )
        print("r20 mcp relay diagnostics already applied and privacy markers verified")
        return

    backend_helper = '''fn is_chatgpt_backend_path(path: &str) -> bool {
    let p = path.split('?').next().unwrap_or(path);
    p == "/backend-api" || p.starts_with("/backend-api/")
}
'''
    backend_helper_new = backend_helper + '''
// CAS-MCP-RELAY-DIAG-R20-HOOK
// CAS-MCP-RELAY-DIAG-R20-QUERY-PRIVACY
// Diagnostic-only helpers for the ChatGPT hosted-MCP relay path. These do not change routing,
// authentication, or response handling; they only make the already-existing diagnostic trace
// trustworthy enough to compare what Codex sent with what reqwest was actually prepared to send.
static MCP_RELAY_DIAG_SEQ: std::sync::atomic::AtomicU64 =
    std::sync::atomic::AtomicU64::new(1);

fn diagnostic_path_only(path: &str) -> &str {
    path.split('?').next().unwrap_or(path)
}

fn is_chatgpt_mcp_backend_path(path: &str) -> bool {
    let p = diagnostic_path_only(path);
    p == "/backend-api/ps/mcp" || p.starts_with("/backend-api/ps/mcp/")
}

fn diagnostic_header_names(headers: &HeaderMap) -> String {
    let mut names: Vec<String> = headers
        .keys()
        .map(|name| name.as_str().to_ascii_lowercase())
        .collect();
    names.sort();
    names.dedup();
    names.join(",")
}

fn diagnostic_body_fingerprint(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}
'''
    text = replace_once(text, backend_helper, backend_helper_new, "backend helper")

    trace_gate = '''    // [MOC-125] gate 开时先 clone Codex 原始请求体(下面会 move 进 rb),供 passthrough 诊断 trace。
    let trace_inbound = forward_trace_enabled().then(|| body.clone());
'''
    trace_gate_new = trace_gate + '''    let mcp_diag_id = (forward_trace_enabled() && is_chatgpt_mcp_backend_path(client_path)).then(|| {
        MCP_RELAY_DIAG_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    });
    if let Some(diag_id) = mcp_diag_id {
        telemetry.logs.add(
            "INFO",
            format!(
                "[mcp-relay-diag id={diag_id}] inbound method={method} path={} body_bytes={} auth={} cookie={} account={} headers=[{}]",
                diagnostic_path_only(client_path),
                body.len(),
                headers.contains_key("authorization"),
                headers.contains_key("cookie"),
                headers.contains_key("chatgpt-account-id"),
                diagnostic_header_names(headers),
            ),
        );
    }
'''
    text = replace_once(text, trace_gate, trace_gate_new, "trace gate")

    send_block = '''    let resp = rb.send().await?;
    let status = resp.status().as_u16();
    let resp_headers = resp.headers().clone();
'''
    send_block_new = '''    // Build explicitly before execute so diagnostics can snapshot the request headers after all
    // passthrough copy/strip decisions. This is behavior-equivalent to RequestBuilder::send();
    // it does not add/remove any application header or alter the target URL/body.
    let req = rb.build()?;
    let outbound_headers_snapshot = req.headers().clone();
    if let Some(diag_id) = mcp_diag_id {
        telemetry.logs.add(
            "INFO",
            format!(
                "[mcp-relay-diag id={diag_id}] outbound-pre-execute auth={} cookie={} account={} headers=[{}]",
                outbound_headers_snapshot.contains_key("authorization"),
                outbound_headers_snapshot.contains_key("cookie"),
                outbound_headers_snapshot.contains_key("chatgpt-account-id"),
                diagnostic_header_names(&outbound_headers_snapshot),
            ),
        );
    }
    let resp = state.http.execute(req).await?;
    let status = resp.status().as_u16();
    let resp_headers = resp.headers().clone();
'''
    text = replace_once(text, send_block, send_block_new, "send block")

    body_read = '''    let resp_body = resp.bytes().await.map_err(ForwardError::Upstream)?;

    // [review N-3] 不再 log 响应 body preview —— getAccount/plugin 响应含 account id/email,
'''
    body_read_new = '''    let resp_body = resp.bytes().await.map_err(ForwardError::Upstream)?;
    if let Some(diag_id) = mcp_diag_id {
        telemetry.logs.add(
            if (200..300).contains(&status) { "INFO" } else { "WARN" },
            format!(
                "[mcp-relay-diag id={diag_id}] response status={status} body_bytes={} body_fp={:016x} content_type={} headers=[{}]",
                resp_body.len(),
                diagnostic_body_fingerprint(&resp_body),
                resp_headers
                    .get(reqwest::header::CONTENT_TYPE)
                    .and_then(|v| v.to_str().ok())
                    .unwrap_or("<none>"),
                diagnostic_header_names(&resp_headers),
            ),
        );
    }

    // [review N-3] 不再 log 响应 body preview —— getAccount/plugin 响应含 account id/email,
'''
    text = replace_once(text, body_read, body_read_new, "response body")

    trace_outbound = '''            // [review comment #1] passthrough 不转换协议,trace 的 outbound 段直接复用 inbound
            // headers/body 作镜像 —— 真实发 chatgpt.com 的请求会再 strip host/accept-encoding、
            // reqwest 重填 host/content-length(trace 未反映这层)。诊断重点在 inbound cookie +
            // response set-cookie 的会话连续性,outbound 仅作对照。
            outbound_headers: headers,
'''
    trace_outbound_new = '''            // r20 diagnostics: use the actually-built reqwest request header map rather than
            // mirroring inbound headers. This exposes passthrough copy/strip drift while the
            // existing trace serializer still masks credential values. Client-level defaults
            // that reqwest may add at execute time remain outside this snapshot.
            outbound_headers: &outbound_headers_snapshot,
'''
    text = replace_once(text, trace_outbound, trace_outbound_new, "trace outbound headers")

    resolver = '''    let original_model = body_model(&body_bytes);
    let resolved = state.resolver.resolve(&parts, &body_bytes)?;
'''
    resolver_new = '''    let original_model = body_model(&body_bytes);
    let resolved = match state.resolver.resolve(&parts, &body_bytes) {
        Ok(resolved) => resolved,
        Err(error) => {
            // CAS-MCP-RELAY-DIAG-R20-RESOLVE
            // The observed "missing or invalid gateway api key" is emitted before normal proxy
            // telemetry starts. When diagnostics are enabled, record only path + header *names*
            // and credential-presence booleans so that a resolver failure can be correlated with
            // the MCP 451 sequence without exposing any header value/body/API key/query string.
            if forward_trace_enabled() {
                proxy_telemetry().logs.add(
                    "WARN",
                    format!(
                        "[resolver-diag] method={} path={} auth={} x_api_key={} api_key={} headers=[{}] error={}",
                        parts.method,
                        diagnostic_path_only(&client_path),
                        parts.headers.contains_key("authorization"),
                        parts.headers.contains_key("x-api-key"),
                        parts.headers.contains_key("api-key"),
                        diagnostic_header_names(&parts.headers),
                        error,
                    ),
                );
            }
            return Err(error.into());
        }
    };
'''
    text = replace_once(text, resolver, resolver_new, "resolver")

    test_anchor = '''    // [MOC-124 H-2] chatgpt backend 透传遇上游 401 → 回灌 relogin 的边界:只 401 不含 403
    #[test]
    fn token_invalidated_only_on_401_not_403() {
'''
    tests = '''    #[test]
    fn mcp_relay_diag_path_scope_is_narrow_and_query_is_not_logged() {
        assert!(is_chatgpt_mcp_backend_path("/backend-api/ps/mcp"));
        assert!(is_chatgpt_mcp_backend_path(
            "/backend-api/ps/mcp/.well-known/oauth-protected-resource"
        ));
        assert!(is_chatgpt_mcp_backend_path(
            "/backend-api/ps/mcp?access_token=do-not-log"
        ));
        assert_eq!(
            diagnostic_path_only("/backend-api/ps/mcp?access_token=do-not-log"),
            "/backend-api/ps/mcp"
        );
        assert!(!is_chatgpt_mcp_backend_path("/backend-api/ps/plugins/list"));
        assert!(!is_chatgpt_mcp_backend_path("/backend-api/f/conversation"));
    }

    #[test]
    fn mcp_relay_diag_body_fingerprint_is_stable_without_exposing_body() {
        assert_eq!(
            diagnostic_body_fingerprint(b"gateway error"),
            diagnostic_body_fingerprint(b"gateway error")
        );
        assert_ne!(
            diagnostic_body_fingerprint(b"gateway error"),
            diagnostic_body_fingerprint(b"other error")
        );
    }

'''
    text = replace_once(text, test_anchor, tests + test_anchor, "tests")

    TARGET.write_text(text, encoding="utf-8")
    print("applied r20 MCP relay diagnostic overlay")


if __name__ == "__main__":
    main()
