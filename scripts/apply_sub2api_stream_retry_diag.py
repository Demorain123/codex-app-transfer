#!/usr/bin/env python3
"""Apply r19 stream-retry diagnostics on top of the r16/r18 retry overlay.

The older diagnostic returned a raw HTTP 429 before a Responses stream was
established. Codex treats that as an HTTP/request failure, so it does not expose
`stream_max_retries` via the Reconnecting X/N path.

r19 keeps the same opt-in one-shot flag files and eligibility rules, but consumes
an armed flag earlier and returns HTTP 200 `text/event-stream` containing a valid
but incomplete Responses SSE event. The body ends before `response.completed`,
matching Codex's own `stream_no_completed` regression-test shape and exercising
the stream reconnect budget instead of request-level HTTP retry handling.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"

HELPER_MARKER = "CAS-SUB2API-STREAM-RETRY-DIAG-R19-HOOK"
CALL_MARKER = "CAS-SUB2API-STREAM-RETRY-DIAG-R19-CALL"

# r19 intentionally depends on r18: the existing helper owns provider eligibility,
# main/child identity classification, one-shot flag consumption, privacy-preserving
# request fingerprints, and runtime correlation logging.
HELPER_ANCHOR = "/// CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-HOOK"
CALL_ANCHOR = "    // CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-CALL: correlate parent/child traffic before\n"

HELPER = r'''
/// CAS-SUB2API-STREAM-RETRY-DIAG-R19-HOOK
///
/// Produce a successfully-established Responses SSE body that terminates before
/// `response.completed`. This deliberately exercises Codex's *stream* retry path
/// (`stream_max_retries`) rather than the request-level HTTP status path.
///
/// The single `response.output_item.done` event mirrors the minimal incomplete
/// stream shape used by Codex's own `stream_no_completed` regression test. The
/// body then reaches EOF, which should be surfaced as a retryable stream
/// disconnect before completion.
fn sub2api_stream_retry_diag_incomplete_sse_response() -> Result<Response, ForwardError> {
    let event = serde_json::json!({
        "type": "response.output_item.done"
    });
    let body = format!("data: {event}\\n\\n");
    Ok(Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/event-stream")
        .header("cache-control", "no-cache")
        .header("x-cas-retry-diag", "incomplete-sse-before-response-completed")
        .body(Body::from(body))?)
}

#[cfg(test)]
mod sub2api_stream_retry_diag_r19_tests {
    use super::*;

    #[test]
    fn synthetic_stream_response_is_http_200_event_stream() {
        let response = sub2api_stream_retry_diag_incomplete_sse_response().unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get("content-type").unwrap(),
            "text/event-stream"
        );
        assert_eq!(
            response.headers().get("x-cas-retry-diag").unwrap(),
            "incomplete-sse-before-response-completed"
        );
    }
}

'''

CALL = r'''    // CAS-SUB2API-STREAM-RETRY-DIAG-R19-CALL: consume an armed retry probe before the
    // legacy raw-429 probes below. A 200/SSE response that ends before `response.completed`
    // reaches Codex's stream-disconnect retry loop and therefore reveals stream_max_retries.
    let stream_retry_diag_model = resolved_model.as_deref().or(upstream_model.as_deref());

    if maybe_take_sub2api_main_retry_diag(
        &resolved.provider,
        &parts.headers,
        stream_retry_diag_model,
    ) {
        log_sub2api_retry_runtime_diag(
            &resolved.provider,
            &parts.headers,
            stream_retry_diag_model,
        );
        telemetry.logs.add(
            "WARN",
            format!(
                "[main-retry-diag] injecting synthetic incomplete SSE before response.completed; model={} thread={} session={} client_request={}",
                stream_retry_diag_model.unwrap_or("<unknown>"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "thread-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "session-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "x-client-request-id"),
            ),
        );
        return sub2api_stream_retry_diag_incomplete_sse_response();
    }

    if maybe_take_sub2api_subagent_retry_diag(
        &resolved.provider,
        &parts.headers,
        stream_retry_diag_model,
    ) {
        log_sub2api_retry_runtime_diag(
            &resolved.provider,
            &parts.headers,
            stream_retry_diag_model,
        );
        telemetry.logs.add(
            "WARN",
            format!(
                "[subagent-retry-diag] injecting synthetic incomplete SSE before response.completed; model={} thread={} parent={} session={} client_request={}",
                stream_retry_diag_model.unwrap_or("<unknown>"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "thread-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "x-codex-parent-thread-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "session-id"),
                sub2api_retry_runtime_diag_header_fingerprint(&parts.headers, "x-client-request-id"),
            ),
        );
        return sub2api_stream_retry_diag_incomplete_sse_response();
    }

'''


def main() -> int:
    text = FORWARD.read_text(encoding="utf-8")

    helper_present = HELPER_MARKER in text
    call_present = CALL_MARKER in text
    if helper_present != call_present:
        raise SystemExit("partial r19 stream retry diagnostic overlay detected; refusing to guess")

    if helper_present:
        print("r19 stream retry diagnostic overlay already present; validating.")
        return 0

    # The r18 overlay must be applied first because r19 reuses its eligibility,
    # identity, flag-consumption, fingerprint and correlation helpers.
    required = [
        "CAS-SUB2API-SUBAGENT-RETRY-DIAG-HOOK",
        "CAS-SUB2API-SUBAGENT-RETRY-DIAG-INJECT",
        "CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-HOOK",
        "CAS-SUB2API-RETRY-RUNTIME-DIAG-R18-CALL",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise SystemExit(
            "r19 requires the r16/r18 retry diagnostic overlay first; missing: "
            + ", ".join(missing)
        )

    if HELPER_ANCHOR not in text:
        raise SystemExit(f"r19 helper anchor not found in {FORWARD}")
    text = text.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)

    if CALL_ANCHOR not in text:
        raise SystemExit(f"r19 call anchor not found in {FORWARD}")
    text = text.replace(CALL_ANCHOR, CALL + CALL_ANCHOR, 1)

    FORWARD.write_text(text, encoding="utf-8")
    print("Applied r19 incomplete-SSE stream retry diagnostic overlay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
