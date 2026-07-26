#!/usr/bin/env python3
"""Apply r16/r18 parent-child retry diagnostics.

r16 introduced a one-shot synthetic HTTP 429 for an eligible Grok subagent,
armed by:

    ~/.codex-app-transfer/subagent-retry-diag.flag

r18 keeps that child-side probe and adds:

1. a one-shot synthetic HTTP 429 for an eligible *main-agent* request, armed by
   `~/.codex-app-transfer/main-retry-diag.flag`; and
2. compact request-identity correlation logs for Sub2API Grok-compat Responses
   traffic so retries can be tied to the same main/child thread without logging
   prompts, bodies, API keys, or raw header values.

Both fault injectors are disabled by default and independent, allowing one main
and one child forced reconnect in the same Transfer process.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"

R16_HELPER_MARKER = "CAS-SUB2API-SUBAGENT-RETRY-DIAG-HOOK"
R16_CALL_MARKER = "CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT"
R18_HELPER_MARKER = "CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-HOOK"
R18_CALL_MARKER = "CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-CALL"

R16_HELPER_ANCHOR = "/// grok.com Web 后端反代必需 / 我们要独占注入的 header 名集合"
R16_CALL_ANCHOR = "    // 6/7. 构造 reqwest 请求 + 发送(抽到 `build_and_send_upstream`,\n"
R18_HELPER_ANCHOR = "/// CAS-SUB2API-SUBAGENT-RETRY-DIAG-HOOK"
R18_CALL_ANCHOR = "    // CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT: deterministic one-shot test for the\n"

R16_HELPER = r'''
/// CAS-SUB2API-SUBAGENT-RETRY-DIAG-HOOK
///
/// Diagnostic-only, one-shot fault injection used to determine whether a spawned
/// Codex subagent inherited the parent's `stream_max_retries` provider setting.
///
/// Arming is intentionally out-of-band and local-only: create
/// `~/.codex-app-transfer/subagent-retry-diag.flag`. The first eligible request is
/// answered locally with a synthetic HTTP 429 and the flag is deleted. Eligibility
/// is deliberately narrow:
/// - explicit Sub2API Grok compat provider;
/// - `grok-*` model only;
/// - Codex subagent identity header present (`x-openai-subagent` or
///   `x-codex-parent-thread-id`).
///
/// This never logs request bodies, prompts, API keys, or header values.
static SUB2API_SUBAGENT_RETRY_DIAG_INJECTED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

fn sub2api_subagent_retry_diag_flag_path() -> Option<std::path::PathBuf> {
    codex_app_transfer_registry::paths::resolve_home().map(|home| {
        home.join(".codex-app-transfer")
            .join("subagent-retry-diag.flag")
    })
}

fn is_sub2api_grok_subagent_retry_diag_candidate(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
) -> bool {
    if !provider.api_format.trim().eq_ignore_ascii_case("responses") {
        return false;
    }
    let compat_enabled = provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    if !compat_enabled {
        return false;
    }
    let is_grok = model
        .map(str::trim)
        .map(str::to_ascii_lowercase)
        .is_some_and(|model| model.starts_with("grok-"));
    if !is_grok {
        return false;
    }
    headers.contains_key("x-openai-subagent")
        || headers.contains_key("x-codex-parent-thread-id")
}

fn maybe_take_sub2api_subagent_retry_diag(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
) -> bool {
    if !is_sub2api_grok_subagent_retry_diag_candidate(provider, headers, model) {
        return false;
    }
    let Some(flag_path) = sub2api_subagent_retry_diag_flag_path() else {
        return false;
    };
    if !flag_path.is_file() {
        return false;
    }
    if SUB2API_SUBAGENT_RETRY_DIAG_INJECTED
        .compare_exchange(
            false,
            true,
            std::sync::atomic::Ordering::SeqCst,
            std::sync::atomic::Ordering::SeqCst,
        )
        .is_err()
    {
        return false;
    }

    match std::fs::remove_file(&flag_path) {
        Ok(()) => proxy_telemetry().logs.add(
            "INFO",
            "[subagent-retry-diag] armed flag consumed; this process will not inject again"
                .to_string(),
        ),
        Err(error) => proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[subagent-retry-diag] synthetic 429 armed, but failed to remove flag {}: {error}",
                flag_path.display()
            ),
        ),
    }
    true
}

fn sub2api_subagent_retry_diag_response() -> Result<Response, ForwardError> {
    let body = serde_json::json!({
        "error": {
            "message": "CAS diagnostic: synthetic one-shot Grok subagent rate limit",
            "type": "rate_limit_error",
            "code": "subagent_retry_diag"
        }
    });
    Ok(Response::builder()
        .status(StatusCode::TOO_MANY_REQUESTS)
        .header("content-type", "application/json; charset=utf-8")
        .header("retry-after", "1")
        .body(Body::from(body.to_string()))?)
}

#[cfg(test)]
mod sub2api_subagent_retry_diag_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "sub2api-test",
            "name": "sub2api",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "sk-test",
            "models": {},
            "sub2apiGrokCompat": compat
        }))
        .unwrap()
    }

    #[test]
    fn diagnostic_candidate_requires_compat_grok_and_subagent_identity() {
        let mut headers = HeaderMap::new();
        headers.insert("x-openai-subagent", "worker".parse().unwrap());
        assert!(is_sub2api_grok_subagent_retry_diag_candidate(
            &provider(true),
            &headers,
            Some("grok-4.5")
        ));
        assert!(!is_sub2api_grok_subagent_retry_diag_candidate(
            &provider(false),
            &headers,
            Some("grok-4.5")
        ));
        assert!(!is_sub2api_grok_subagent_retry_diag_candidate(
            &provider(true),
            &headers,
            Some("gpt-5.6-luna")
        ));
        assert!(!is_sub2api_grok_subagent_retry_diag_candidate(
            &provider(true),
            &HeaderMap::new(),
            Some("grok-4.5")
        ));
    }

    #[test]
    fn parent_thread_header_is_also_recognized_as_subagent_identity() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-codex-parent-thread-id",
            "019f94f6-09ce-7942-95d3-28d74688a336"
                .parse()
                .unwrap(),
        );
        assert!(is_sub2api_grok_subagent_retry_diag_candidate(
            &provider(true),
            &headers,
            Some("GROK-4.5")
        ));
    }

    #[test]
    fn synthetic_response_is_http_429_json() {
        let response = sub2api_subagent_retry_diag_response().unwrap();
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(response.headers().get("retry-after").unwrap(), "1");
    }
}

'''

R16_CALL = r'''    // CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT: deterministic one-shot test for the
    // child session's effective reconnect budget. This runs only when the local flag file exists,
    // only for a Grok request on the explicit Sub2API compat provider, and only when Codex marks the
    // request as a subagent. Returning a real HTTP 429 exercises Codex's normal stream retry path;
    // `retry-after: 1` avoids a hot loop while keeping the test quick.
    let diag_model = resolved_model.as_deref().or(upstream_model.as_deref());
    if maybe_take_sub2api_subagent_retry_diag(&resolved.provider, &parts.headers, diag_model) {
        telemetry.logs.add(
            "WARN",
            format!(
                "[subagent-retry-diag] injecting synthetic one-shot HTTP 429; model={} subagent_header={} parent_thread_header={}",
                diag_model.unwrap_or("<unknown>"),
                parts.headers.contains_key("x-openai-subagent"),
                parts.headers.contains_key("x-codex-parent-thread-id")
            ),
        );
        return sub2api_subagent_retry_diag_response();
    }

'''

R18_HELPER = r'''
/// CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-HOOK
///
/// Parent/child retry diagnostics for the Sub2API compat path.
///
/// - `main-retry-diag.flag` injects exactly one synthetic 429 into an eligible
///   main-agent request.
/// - r16's separate `subagent-retry-diag.flag` remains the child-side injector.
/// - compact correlation logs fingerprint request identity headers instead of
///   logging their raw values.
///
/// Both injectors are disabled by default. This r18 layer never logs request
/// bodies, prompts, tool arguments, API keys, authorization, or raw identity
/// header values.
static SUB2API_MAIN_RETRY_DIAG_INJECTED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

fn sub2api_retry_runtime_diag_provider_enabled(
    provider: &codex_app_transfer_registry::Provider,
) -> bool {
    provider.api_format.trim().eq_ignore_ascii_case("responses")
        && provider
            .extra
            .get("sub2apiGrokCompat")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
}

fn sub2api_retry_runtime_diag_is_subagent(headers: &HeaderMap) -> bool {
    headers.contains_key("x-openai-subagent")
        || headers.contains_key("x-codex-parent-thread-id")
}

/// FNV-1a fingerprint used only for correlating repeated requests in local
/// diagnostics. It intentionally avoids logging raw thread/session/request IDs.
fn sub2api_retry_runtime_diag_header_fingerprint(headers: &HeaderMap, name: &str) -> String {
    let Some(value) = headers.get(name).and_then(|value| value.to_str().ok()) else {
        return "-".to_string();
    };
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in value.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{:08x}", (hash ^ (hash >> 32)) as u32)
}

fn log_sub2api_retry_runtime_diag(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
) {
    if !sub2api_retry_runtime_diag_provider_enabled(provider) {
        return;
    }
    let is_subagent = sub2api_retry_runtime_diag_is_subagent(headers);
    proxy_telemetry().logs.add(
        "INFO",
        format!(
            "[retry-runtime-diag] target={} model={} provider={} thread={} parent={} session={} client_request={} subagent_header={} parent_thread_header={}",
            if is_subagent { "subagent" } else { "main" },
            model.unwrap_or("<unknown>"),
            provider.id,
            sub2api_retry_runtime_diag_header_fingerprint(headers, "thread-id"),
            sub2api_retry_runtime_diag_header_fingerprint(headers, "x-codex-parent-thread-id"),
            sub2api_retry_runtime_diag_header_fingerprint(headers, "session-id"),
            sub2api_retry_runtime_diag_header_fingerprint(headers, "x-client-request-id"),
            headers.contains_key("x-openai-subagent"),
            headers.contains_key("x-codex-parent-thread-id"),
        ),
    );
}

fn sub2api_main_retry_diag_flag_path() -> Option<std::path::PathBuf> {
    codex_app_transfer_registry::paths::resolve_home()
        .map(|home| home.join(".codex-app-transfer").join("main-retry-diag.flag"))
}

fn is_sub2api_main_retry_diag_candidate(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
) -> bool {
    sub2api_retry_runtime_diag_provider_enabled(provider)
        && !sub2api_retry_runtime_diag_is_subagent(headers)
        && model.is_some_and(|model| !model.trim().is_empty())
}

fn maybe_take_sub2api_main_retry_diag(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
) -> bool {
    if !is_sub2api_main_retry_diag_candidate(provider, headers, model) {
        return false;
    }
    let Some(flag_path) = sub2api_main_retry_diag_flag_path() else {
        return false;
    };
    if !flag_path.is_file() {
        return false;
    }
    if SUB2API_MAIN_RETRY_DIAG_INJECTED
        .compare_exchange(
            false,
            true,
            std::sync::atomic::Ordering::SeqCst,
            std::sync::atomic::Ordering::SeqCst,
        )
        .is_err()
    {
        return false;
    }

    match std::fs::remove_file(&flag_path) {
        Ok(()) => proxy_telemetry().logs.add(
            "INFO",
            "[main-retry-diag] armed flag consumed; this process will not inject a second main-agent fault"
                .to_string(),
        ),
        Err(error) => proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[main-retry-diag] synthetic 429 armed, but failed to remove flag {}: {error}",
                flag_path.display()
            ),
        ),
    }
    true
}

fn sub2api_main_retry_diag_response() -> Result<Response, ForwardError> {
    let body = serde_json::json!({
        "error": {
            "message": "CAS diagnostic: synthetic one-shot main-agent rate limit",
            "type": "rate_limit_error",
            "code": "main_retry_diag"
        }
    });
    Ok(Response::builder()
        .status(StatusCode::TOO_MANY_REQUESTS)
        .header("content-type", "application/json; charset=utf-8")
        .header("retry-after", "1")
        .body(Body::from(body.to_string()))?)
}

#[cfg(test)]
mod sub2api_retry_runtime_diag_r18_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "sub2api-test",
            "name": "sub2api",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "sk-test",
            "models": {},
            "sub2apiGrokCompat": compat
        }))
        .unwrap()
    }

    #[test]
    fn main_candidate_requires_compat_and_rejects_subagent_identity() {
        assert!(is_sub2api_main_retry_diag_candidate(
            &provider(true),
            &HeaderMap::new(),
            Some("gpt-5.6-luna")
        ));
        assert!(!is_sub2api_main_retry_diag_candidate(
            &provider(false),
            &HeaderMap::new(),
            Some("gpt-5.6-luna")
        ));
        assert!(!is_sub2api_main_retry_diag_candidate(
            &provider(true),
            &HeaderMap::new(),
            None
        ));

        let mut child = HeaderMap::new();
        child.insert("x-openai-subagent", "worker".parse().unwrap());
        assert!(!is_sub2api_main_retry_diag_candidate(
            &provider(true),
            &child,
            Some("grok-4.5")
        ));
    }

    #[test]
    fn parent_thread_header_marks_request_as_subagent() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-codex-parent-thread-id",
            "019f94f6-09ce-7942-95d3-28d74688a336"
                .parse()
                .unwrap(),
        );
        assert!(sub2api_retry_runtime_diag_is_subagent(&headers));
        assert!(!is_sub2api_main_retry_diag_candidate(
            &provider(true),
            &headers,
            Some("grok-4.5")
        ));
    }

    #[test]
    fn identity_fingerprint_correlates_without_echoing_raw_header() {
        let raw = "019f94f6-09ce-7942-95d3-28d74688a336";
        let mut headers = HeaderMap::new();
        headers.insert("thread-id", raw.parse().unwrap());
        let first = sub2api_retry_runtime_diag_header_fingerprint(&headers, "thread-id");
        let second = sub2api_retry_runtime_diag_header_fingerprint(&headers, "thread-id");
        assert_eq!(first, second);
        assert_ne!(first, raw);
        assert_eq!(first.len(), 8);
        assert_eq!(
            sub2api_retry_runtime_diag_header_fingerprint(&headers, "session-id"),
            "-"
        );
    }

    #[test]
    fn main_synthetic_response_is_http_429_json() {
        let response = sub2api_main_retry_diag_response().unwrap();
        assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(response.headers().get("retry-after").unwrap(), "1");
    }
}

'''

R18_CALL = r'''    // CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-CALL: correlate parent/child traffic before
    // either one-shot fault injector can return early. Raw identity header values are never logged.
    let retry_runtime_diag_model = resolved_model.as_deref().or(upstream_model.as_deref());
    log_sub2api_retry_runtime_diag(
        &resolved.provider,
        &parts.headers,
        retry_runtime_diag_model,
    );

    // Main-agent side of the deterministic A/B control. The existing r16 subagent injector below
    // remains independent, so one Transfer process can expose main 1/N and child 1/N separately.
    if maybe_take_sub2api_main_retry_diag(
        &resolved.provider,
        &parts.headers,
        retry_runtime_diag_model,
    ) {
        telemetry.logs.add(
            "WARN",
            format!(
                "[main-retry-diag] injecting synthetic one-shot HTTP 429; model={} thread={} session={} client_request={}",
                retry_runtime_diag_model.unwrap_or("<unknown>"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "thread-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "session-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "x-client-request-id"),
            ),
        );
        return sub2api_main_retry_diag_response();
    }

'''


def main() -> int:
    text = FORWARD.read_text(encoding="utf-8")

    r16_helper_present = R16_HELPER_MARKER in text
    r16_call_present = R16_CALL_MARKER in text
    if r16_helper_present != r16_call_present:
        raise SystemExit("partial r16 subagent retry diagnostic overlay detected; refusing to guess")

    if not r16_helper_present:
        if R16_HELPER_ANCHOR not in text:
            raise SystemExit(f"r16 helper anchor not found in {FORWARD}")
        text = text.replace(R16_HELPER_ANCHOR, R16_HELPER + R16_HELPER_ANCHOR, 1)
        if R16_CALL_ANCHOR not in text:
            raise SystemExit(f"r16 call anchor not found in {FORWARD}")
        text = text.replace(R16_CALL_ANCHOR, R16_CALL + R16_CALL_ANCHOR, 1)
        print("Applied r16 Grok subagent retry diagnostic overlay.")
    else:
        print("r16 subagent retry diagnostic overlay already present; validating.")

    r18_helper_present = R18_HELPER_MARKER in text
    r18_call_present = R18_CALL_MARKER in text
    if r18_helper_present != r18_call_present:
        raise SystemExit("partial r18 retry runtime diagnostic overlay detected; refusing to guess")

    if not r18_helper_present:
        if R18_HELPER_ANCHOR not in text:
            raise SystemExit(f"r18 helper anchor not found in {FORWARD}")
        text = text.replace(R18_HELPER_ANCHOR, R18_HELPER + R18_HELPER_ANCHOR, 1)
        if R18_CALL_ANCHOR not in text:
            raise SystemExit(f"r18 call anchor not found in {FORWARD}")
        text = text.replace(R18_CALL_ANCHOR, R18_CALL + R18_CALL_ANCHOR, 1)
        print("Applied r18 parent/child retry runtime diagnostic overlay.")
    else:
        print("r18 retry runtime diagnostic overlay already present; validating.")

    FORWARD.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
