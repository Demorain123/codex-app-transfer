from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MARKER = "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY"

text = COMPACT.read_text(encoding="utf-8")
if MARKER in text:
    print("r54 Responses SSE compact reassembly already applied")
    raise SystemExit(0)

helper_anchor = "async fn collect_compact_summary_for_v2(\n"
if helper_anchor not in text:
    raise SystemExit("r54 compact SSE: collect_compact_summary_for_v2 anchor missing")

helper = r'''
// CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY
//
// Sub2API's OpenAI OAuth Responses path may answer with SSE even when the local
// compact request explicitly sets `stream:false`. r53 proved the request itself is
// valid (HTTP 200 after removing max_output_tokens), but collect_compact_summary_for_v2
// still assumed a single JSON document and rejected the successful SSE stream as
// "non-JSON". Reassemble the public Responses SSE wire into the same non-streaming
// response object that extract_compact_summary_text / extract_compact_usage already
// understand. Ordinary JSON remains byte-for-byte passthrough.
fn reassemble_responses_sse_to_response_json_r54(buf: &[u8]) -> Option<Vec<u8>> {
    let text = std::str::from_utf8(buf).ok()?;
    let trimmed = text.trim_start();
    if !trimmed.starts_with("event:") && !trimmed.starts_with("data:") {
        return None;
    }

    let mut completed_response: Option<Value> = None;
    let mut output_text_done: Option<String> = None;
    let mut output_text_delta = String::new();

    for raw_line in text.lines() {
        let line = raw_line.trim();
        let Some(payload) = line.strip_prefix("data:") else {
            continue;
        };
        let payload = payload.trim();
        if payload.is_empty() || payload == "[DONE]" {
            continue;
        }
        let Ok(event) = serde_json::from_str::<Value>(payload) else {
            continue;
        };
        match event.get("type").and_then(Value::as_str) {
            Some("response.completed") => {
                if let Some(response) = event.get("response") {
                    completed_response = Some(response.clone());
                }
            }
            Some("response.output_text.done") => {
                if let Some(done) = event.get("text").and_then(Value::as_str) {
                    output_text_done = Some(done.to_owned());
                }
            }
            Some("response.output_text.delta") => {
                if let Some(delta) = event.get("delta").and_then(Value::as_str) {
                    output_text_delta.push_str(delta);
                }
            }
            _ => {}
        }
    }

    if let Some(response) = completed_response {
        return serde_json::to_vec(&response).ok();
    }

    let summary = output_text_done.or_else(|| {
        if output_text_delta.is_empty() {
            None
        } else {
            Some(output_text_delta)
        }
    })?;

    // Defensive fallback for providers that omit response.completed after already
    // sending output_text.done/delta. Usage is intentionally omitted here; the existing
    // usage extractor safely records zero when unavailable.
    serde_json::to_vec(&json!({
        "object": "response",
        "status": "completed",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": summary}]
        }]
    }))
    .ok()
}

'''
text = text.replace(helper_anchor, helper + helper_anchor, 1)

old_parse = '''    let parsed: Value = serde_json::from_slice(&buf).map_err(|e| {
        let preview: String = String::from_utf8_lossy(&buf).chars().take(300).collect();
        (
            "server_error",
            "non_json",
            format!("compact v2 upstream non-JSON: {e}; first 300 chars: {preview}"),
        )
    })?;
'''
new_parse = r'''    let original_wire_bytes = buf.len();
    let buf = match reassemble_responses_sse_to_response_json_r54(&buf) {
        Some(reassembled) => {
            tracing::warn!(
                "[model-switch-r54] action=reassemble_responses_sse source_bytes={} json_bytes={} reason=sub2api_stream_false_returns_sse",
                original_wire_bytes,
                reassembled.len(),
            );
            reassembled
        }
        None => buf,
    };

    let parsed: Value = serde_json::from_slice(&buf).map_err(|e| {
        let preview: String = String::from_utf8_lossy(&buf).chars().take(300).collect();
        (
            "server_error",
            "non_json",
            format!("compact v2 upstream non-JSON: {e}; first 300 chars: {preview}"),
        )
    })?;
'''
if old_parse not in text:
    raise SystemExit("r54 compact SSE: V2 JSON parse anchor missing")
text = text.replace(old_parse, new_parse, 1)

test_anchor = '''    #[tokio::test]
    async fn compact_v2_plan_wraps_chat_upstream_into_sse_with_single_compaction_item() {
'''
tests = r'''    #[test]
    fn r54_reassembles_responses_sse_completed_response() {
        let sse = concat!(
            "event: response.created\n",
            "data: {\"type\":\"response.created\",\"response\":{\"id\":\"resp_1\",\"status\":\"in_progress\"}}\n\n",
            "event: response.output_text.delta\n",
            "data: {\"type\":\"response.output_text.delta\",\"delta\":\"ignored-fallback\"}\n\n",
            "event: response.completed\n",
            "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\",\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"## Summary\\nportable checkpoint\"}]}],\"usage\":{\"input_tokens\":12,\"output_tokens\":5}}}\n\n"
        );
        let out = reassemble_responses_sse_to_response_json_r54(sse.as_bytes())
            .expect("Responses SSE should reassemble");
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(
            extract_compact_summary_text(&parsed).as_deref(),
            Some("## Summary\nportable checkpoint")
        );
        assert_eq!(extract_compact_usage(&parsed)["input_tokens"], 12);
        assert_eq!(extract_compact_usage(&parsed)["output_tokens"], 5);
    }

    #[test]
    fn r54_reassembles_responses_sse_without_completed_event_from_output_text_done() {
        let sse = concat!(
            "event: response.output_text.delta\n",
            "data: {\"type\":\"response.output_text.delta\",\"delta\":\"partial\"}\n\n",
            "event: response.output_text.done\n",
            "data: {\"type\":\"response.output_text.done\",\"text\":\"## Summary\\nfallback checkpoint\"}\n\n"
        );
        let out = reassemble_responses_sse_to_response_json_r54(sse.as_bytes())
            .expect("output_text.done should be enough");
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(
            extract_compact_summary_text(&parsed).as_deref(),
            Some("## Summary\nfallback checkpoint")
        );
    }

    #[test]
    fn r54_non_sse_json_is_passthrough_signal_none() {
        let json_body = br#"{"output":[{"type":"message"}]}"#;
        assert!(reassemble_responses_sse_to_response_json_r54(json_body).is_none());
    }

'''
if test_anchor not in text:
    raise SystemExit("r54 compact SSE: focused-test anchor missing")
text = text.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    MARKER,
    "reassemble_responses_sse_to_response_json_r54",
    "[model-switch-r54] action=reassemble_responses_sse",
    "response.completed",
    "response.output_text.done",
    "r54_reassembles_responses_sse_completed_response",
):
    if invariant not in text:
        raise SystemExit(f"r54 compact SSE invariant missing: {invariant}")

COMPACT.write_text(text, encoding="utf-8")
print("R54 SUB2API RESPONSES SSE REASSEMBLY PASS")
print("- successful Responses SSE is reassembled before compact summary parsing")
print("- response.completed.response is preferred so usage and output remain exact")
print("- output_text.done/delta is a defensive fallback for incomplete gateway SSE framing")
print("- ordinary JSON compact responses remain untouched")
