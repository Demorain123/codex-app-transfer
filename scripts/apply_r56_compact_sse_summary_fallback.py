from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MARKER = "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK"

text = COMPACT.read_text(encoding="utf-8")
if MARKER in text:
    print("r56 compact SSE summary fallback already applied")
    raise SystemExit(0)

if "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY" not in text:
    raise SystemExit("r56 compact SSE fallback requires the r54 SSE reassembler")

# r54 accumulated output_text.done/delta, but preferred response.completed
# unconditionally. Some Sub2API/OpenAI OAuth Responses streams carry the user-visible
# summary in the incremental SSE events while response.completed.response is a valid
# status=completed object whose output has no message/output_text. In that case r54
# discarded the good text and the existing extractor reported missing_summary.
old_completed = '''    if let Some(response) = completed_response {
        return serde_json::to_vec(&response).ok();
    }

    let summary = output_text_done.or_else(|| {
'''
new_completed = r'''    // CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK
    if let Some(mut response) = completed_response {
        // Prefer the provider's completed response when it already contains a normal
        // Responses message/output_text. This keeps usage and the exact output shape.
        if extract_compact_summary_text(&response).is_some() {
            return serde_json::to_vec(&response).ok();
        }

        // Sub2API can emit a perfectly valid completed response object without the
        // textual message while the same SSE stream already delivered the summary via
        // response.output_text.done/delta (or the equivalent item/part events captured
        // below). Preserve the completed metadata/usage, but restore only the missing
        // public output message from the observed SSE text. No prompt/history content is
        // logged and the persisted Codex rollout is untouched.
        let fallback = output_text_done
            .as_ref()
            .filter(|value| !value.trim().is_empty())
            .map(|value| (value.clone(), "output_text_done"))
            .or_else(|| {
                if output_text_delta.trim().is_empty() {
                    None
                } else {
                    Some((output_text_delta.clone(), "output_text_delta"))
                }
            });

        if let Some((summary, source)) = fallback {
            let summary_chars = summary.chars().count();
            response["output"] = json!([{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": summary}]
            }]);
            tracing::warn!(
                "[compact-r56] action=sse_summary_fallback source={} chars={} reason=completed_response_missing_output_text",
                source,
                summary_chars,
            );
            return serde_json::to_vec(&response).ok();
        }

        // Keep r54's truthful failure semantics when neither the completed response nor
        // any public text event carried a summary. Do not synthesize content from
        // reasoning or tool events.
        return serde_json::to_vec(&response).ok();
    }

    let summary = output_text_done.or_else(|| {
'''
if old_completed not in text:
    raise SystemExit("r56 compact SSE fallback: r54 completed-response anchor missing")
text = text.replace(old_completed, new_completed, 1)

old_event_tail = '''            Some("response.output_text.delta") => {
                if let Some(delta) = event.get("delta").and_then(Value::as_str) {
                    output_text_delta.push_str(delta);
                }
            }
            _ => {}
'''
new_event_tail = r'''            Some("response.output_text.delta") => {
                if let Some(delta) = event.get("delta").and_then(Value::as_str) {
                    output_text_delta.push_str(delta);
                }
            }
            // A few Responses-compatible gateways omit output_text.done but still send
            // the equivalent public text in content_part.done or output_item.done.
            Some("response.content_part.done") => {
                if let Some(part) = event.get("part") {
                    if part.get("type").and_then(Value::as_str) == Some("output_text") {
                        if let Some(done) = part.get("text").and_then(Value::as_str) {
                            if !done.trim().is_empty() {
                                output_text_done = Some(done.to_owned());
                            }
                        }
                    }
                }
            }
            Some("response.output_item.done") => {
                if let Some(item) = event.get("item") {
                    let wrapped = json!({"output": [item.clone()]});
                    if let Some(done) = extract_compact_summary_text(&wrapped) {
                        if !done.trim().is_empty() {
                            output_text_done = Some(done);
                        }
                    }
                }
            }
            _ => {}
'''
if old_event_tail not in text:
    raise SystemExit("r56 compact SSE fallback: r54 event-tail anchor missing")
text = text.replace(old_event_tail, new_event_tail, 1)

test_anchor = '''    #[test]
    fn r54_reassembles_responses_sse_completed_response() {
'''
tests = r'''    #[test]
    fn r56_completed_response_without_text_uses_output_text_done() {
        let sse = concat!(
            "event: response.output_text.done\n",
            "data: {\"type\":\"response.output_text.done\",\"text\":\"## Summary\\nTerra checkpoint\"}\n\n",
            "event: response.completed\n",
            "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_r56\",\"status\":\"completed\",\"output\":[{\"type\":\"reasoning\",\"summary\":[]}],\"usage\":{\"input_tokens\":77,\"output_tokens\":11}}}\n\n"
        );
        let out = reassemble_responses_sse_to_response_json_r54(sse.as_bytes())
            .expect("r56 should recover public text from output_text.done");
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(
            extract_compact_summary_text(&parsed).as_deref(),
            Some("## Summary\nTerra checkpoint")
        );
        assert_eq!(extract_compact_usage(&parsed)["input_tokens"], 77);
    }

    #[test]
    fn r56_completed_response_without_text_uses_accumulated_delta() {
        let sse = concat!(
            "event: response.output_text.delta\n",
            "data: {\"type\":\"response.output_text.delta\",\"delta\":\"## Sum\"}\n\n",
            "event: response.output_text.delta\n",
            "data: {\"type\":\"response.output_text.delta\",\"delta\":\"mary\\nDelta checkpoint\"}\n\n",
            "event: response.completed\n",
            "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_r56_delta\",\"status\":\"completed\",\"output\":[]}}\n\n"
        );
        let out = reassemble_responses_sse_to_response_json_r54(sse.as_bytes())
            .expect("r56 should recover accumulated output_text.delta");
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(
            extract_compact_summary_text(&parsed).as_deref(),
            Some("## Summary\nDelta checkpoint")
        );
    }

    #[test]
    fn r56_completed_response_with_text_still_wins_over_sse_fallback() {
        let sse = concat!(
            "event: response.output_text.done\n",
            "data: {\"type\":\"response.output_text.done\",\"text\":\"fallback must not win\"}\n\n",
            "event: response.completed\n",
            "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_r56_exact\",\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"## Summary\\nExact completed text\"}]}]}}\n\n"
        );
        let out = reassemble_responses_sse_to_response_json_r54(sse.as_bytes()).unwrap();
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(
            extract_compact_summary_text(&parsed).as_deref(),
            Some("## Summary\nExact completed text")
        );
    }

'''
if test_anchor not in text:
    raise SystemExit("r56 compact SSE fallback: r54 test anchor missing")
text = text.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    MARKER,
    "[compact-r56] action=sse_summary_fallback",
    "completed_response_missing_output_text",
    "response.content_part.done",
    "response.output_item.done",
    "r56_completed_response_without_text_uses_output_text_done",
    "r56_completed_response_without_text_uses_accumulated_delta",
):
    if invariant not in text:
        raise SystemExit(f"r56 compact SSE fallback invariant missing: {invariant}")

COMPACT.write_text(text, encoding="utf-8")
print("R56 COMPACT SSE SUMMARY FALLBACK PASS")
print("- response.completed with normal output_text remains authoritative")
print("- completed responses missing public text reuse observed output_text.done/delta")
print("- content_part.done/output_item.done are accepted as equivalent public text events")
print("- usage/completed metadata is preserved while only the missing output message is restored")
print("- no reasoning/tool content is promoted into the summary")
