#!/usr/bin/env python3
"""Apply r16 diagnostic-only Sub2API/Grok subagent retry instrumentation.

This overlay adds a one-shot synthetic HTTP 429 for an eligible Grok subagent
request when the user explicitly arms a local flag file:

    ~/.codex-app-transfer/subagent-retry-diag.flag

The flag is consumed (deleted) when the synthetic 429 is injected. The hook is
strictly opt-in, Grok-only, Sub2API-compat-only, and subagent-only. Main-agent
traffic and non-Grok traffic are untouched.

The purpose is to deterministically expose Codex's effective stream reconnect
budget (for example Reconnecting 1/5 vs 1/15) without waiting for a natural 429.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"

HELPER_MARKER = "CAS-SUB2API-SUBAGENT-RETRY-DIAG-HOOK"
CALL_MARKER = "CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT"

HELPER_ANCHOR = "/// grok.com Web 后端反代必需 / 我们要独占注入的 header 名集合"
CALL_ANCHOR = "    // 6/7. 构造 reqwest 请求 + 发送(抽到 `build_and_send_upstream`,\n"

HELPER = r'''
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
        assert_eq!(
            response.headers().get("retry-after").unwrap(),
            "1"
        );
    }
}

'''

CALL = r'''    // CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT: deterministic one-shot test for the
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


def main() -> int:
    text = FORWARD.read_text(encoding="utf-8")

    helper_present = HELPER_MARKER in text
    call_present = CALL_MARKER in text
    if helper_present and call_present:
        print("Subagent retry diagnostic overlay already present; validating.")
        return 0
    if helper_present != call_present:
        raise SystemExit(
            "partial subagent retry diagnostic overlay detected; refusing to guess"
        )

    if HELPER_ANCHOR not in text:
        raise SystemExit(f"helper anchor not found in {FORWARD}")
    text = text.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)

    if CALL_ANCHOR not in text:
        raise SystemExit(f"call anchor not found in {FORWARD}")
    text = text.replace(CALL_ANCHOR, CALL + CALL_ANCHOR, 1)

    FORWARD.write_text(text, encoding="utf-8")
    print("Applied Sub2API Grok subagent retry diagnostic overlay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
