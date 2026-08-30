from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY"

source = FORWARD.read_text(encoding="utf-8")
if MARKER in source:
    print("r50 same-session cross-model replay already applied")
    raise SystemExit(0)

helper_anchor = "pub async fn forward_handler(\n"
if helper_anchor not in source:
    raise SystemExit("r50 replay: forward_handler anchor missing")

helpers = r'''
// CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY
//
// Preserve the Codex thread/session identity and persisted rollout exactly as-is, but
// make the *outbound copy* portable when one session changes model. Responses
// reasoning.encrypted_content is model/provider state, not conversation text: replaying
// a Grok blob into GPT (or a GPT blob into Grok) can produce a permanent 4xx loop.
// Codex compaction items are different: their `encrypted_content` field is historical
// naming and contains a plaintext handoff summary, so keep that information by lowering
// the item to an ordinary user message.
//
// previous_response_id is also upstream-specific. On an actual model switch the full
// Codex input replay is authoritative, so do not ask the new upstream to resolve an id
// minted by the previous model/provider.
//
// This function never mutates the on-disk rollout, raw session/thread id, tool call ids,
// user/assistant messages, or the selected model. It only rewrites a per-request byte
// copy after routing has resolved the target model.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct PortableReplayStatsR50 {
    before_bytes: usize,
    after_bytes: usize,
    reasoning_dropped: usize,
    compaction_portable_messages: usize,
    empty_compactions_dropped: usize,
    previous_response_id_dropped: bool,
}

fn cross_model_switch_r50(previous_model: Option<&str>, target_model: Option<&str>) -> bool {
    let (Some(previous), Some(target)) = (previous_model, target_model) else {
        return false;
    };
    !previous.trim().is_empty()
        && !target.trim().is_empty()
        && !model_equivalent_r45(previous, target)
}

fn portableize_input_item_r50(
    item: serde_json::Value,
    stats: &mut PortableReplayStatsR50,
) -> Option<serde_json::Value> {
    let kind = item
        .get("type")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("");
    match kind {
        // Encrypted reasoning is intentionally opaque and model/provider-bound.
        // The visible assistant/user/tool history stays in the replay, so dropping
        // only this hidden state is the least invasive cross-model boundary.
        "reasoning" => {
            stats.reasoning_dropped += 1;
            None
        }
        "compaction" | "context_compaction" | "compaction_summary" => {
            let summary = item
                .get("encrypted_content")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .trim();
            if summary.is_empty() {
                stats.empty_compactions_dropped += 1;
                None
            } else {
                stats.compaction_portable_messages += 1;
                // Responses accepts an EasyInputMessage (`role` + `content`) alongside
                // typed input items. Use that portable public shape instead of carrying
                // a private compaction item across model/provider boundaries.
                Some(serde_json::json!({
                    "role": "user",
                    "content": summary,
                }))
            }
        }
        _ => Some(item),
    }
}

fn portableize_cross_model_replay_r50(
    body: &[u8],
    previous_model: Option<&str>,
    target_model: Option<&str>,
    compaction_helper: bool,
) -> Option<(Vec<u8>, PortableReplayStatsR50)> {
    if compaction_helper || !cross_model_switch_r50(previous_model, target_model) {
        return None;
    }

    let mut value = serde_json::from_slice::<serde_json::Value>(body).ok()?;
    let obj = value.as_object_mut()?;
    let mut stats = PortableReplayStatsR50 {
        before_bytes: body.len(),
        ..PortableReplayStatsR50::default()
    };
    let mut changed = false;

    if obj
        .get("previous_response_id")
        .is_some_and(|value| !value.is_null())
    {
        obj.remove("previous_response_id");
        stats.previous_response_id_dropped = true;
        changed = true;
    }

    if let Some(input) = obj.get_mut("input") {
        match input {
            serde_json::Value::Array(items) => {
                let old_items = std::mem::take(items);
                let old_len = old_items.len();
                let mut portable = Vec::with_capacity(old_len);
                for item in old_items {
                    if let Some(item) = portableize_input_item_r50(item, &mut stats) {
                        portable.push(item);
                    }
                }
                if portable.len() != old_len || stats.compaction_portable_messages > 0 {
                    changed = true;
                }
                *items = portable;
            }
            serde_json::Value::Object(_) => {
                let item = std::mem::replace(input, serde_json::Value::Null);
                match portableize_input_item_r50(item, &mut stats) {
                    Some(item) => *input = item,
                    None => *input = serde_json::Value::Array(Vec::new()),
                }
                if stats.reasoning_dropped > 0
                    || stats.compaction_portable_messages > 0
                    || stats.empty_compactions_dropped > 0
                {
                    changed = true;
                }
            }
            _ => {}
        }
    }

    if !changed {
        return None;
    }
    let rewritten = serde_json::to_vec(&value).ok()?;
    stats.after_bytes = rewritten.len();
    Some((rewritten, stats))
}

fn log_portable_replay_r50(
    session_fingerprint: Option<&str>,
    previous_model: Option<&str>,
    target_model: Option<&str>,
    stats: &PortableReplayStatsR50,
) {
    let session = session_fingerprint
        .map(|value| &value[..8.min(value.len())])
        .unwrap_or("-");
    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[model-switch-r50] action=portable_replay session={} from={} to={} previous_response_id_dropped={} reasoning_dropped={} compaction_portable_messages={} empty_compactions_dropped={} before_bytes={} after_bytes={}",
            session,
            previous_model.unwrap_or("<none>"),
            target_model.unwrap_or("<unknown>"),
            stats.previous_response_id_dropped,
            stats.reasoning_dropped,
            stats.compaction_portable_messages,
            stats.empty_compactions_dropped,
            stats.before_bytes,
            stats.after_bytes,
        ),
    );
}

'''
source = source.replace(helper_anchor, helpers + helper_anchor, 1)

resolved_anchor = '''    let resolved_model = body_model(&body_bytes);
    let r46_forensics = analyze_request_forensics_r46(
'''
resolved_new = '''    let resolved_model = body_model(&body_bytes);

    // r46 captured the session's previous effective model *before* r45 advances it.
    // Use that exact state to detect a real same-session switch. Rewrite only the
    // outbound Responses replay; the selected model and persisted Codex rollout stay
    // untouched.
    if is_local_responses_route(&client_path) {
        if let Some((rewritten, stats)) = portableize_cross_model_replay_r50(
            &body_bytes,
            r46_effective_before.as_deref(),
            resolved_model.as_deref(),
            r45_compaction_helper,
        ) {
            body_bytes = Bytes::from(rewritten);
            log_portable_replay_r50(
                r45_conversation_fingerprint.as_deref(),
                r46_effective_before.as_deref(),
                resolved_model.as_deref(),
                &stats,
            );
        }
    }

    let r46_forensics = analyze_request_forensics_r46(
'''
if resolved_anchor not in source:
    raise SystemExit("r50 replay: r46 resolved-model anchor missing")
source = source.replace(resolved_anchor, resolved_new, 1)

test_anchor = '''    #[test]
    fn r46_metadata_truth_keeps_feature_flag_out_of_request_role() {
'''
tests = r'''    #[test]
    fn r50_cross_model_replay_drops_opaque_reasoning_and_keeps_compaction_summary() {
        let body = br#"{
            "model":"gpt-5.6-terra",
            "previous_response_id":"resp_from_grok",
            "input":[
                {"type":"message","role":"user","content":"keep-user"},
                {"type":"reasoning","id":"rs_grok","summary":[],"encrypted_content":"FOREIGN_BLOB"},
                {"type":"compaction","encrypted_content":"portable handoff summary"},
                {"type":"function_call","call_id":"call_1","name":"x","arguments":"{}"}
            ]
        }"#;
        let (rewritten, stats) = portableize_cross_model_replay_r50(
            body,
            Some("grok-4.6"),
            Some("gpt-5.6-terra"),
            false,
        )
        .expect("cross-model replay should be portableized");
        let value: serde_json::Value = serde_json::from_slice(&rewritten).unwrap();

        assert_eq!(value["model"], "gpt-5.6-terra");
        assert!(value.get("previous_response_id").is_none());
        let input = value["input"].as_array().unwrap();
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("reasoning")));
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("compaction")));
        assert!(input.iter().any(|item| item.get("content").and_then(|v| v.as_str()) == Some("portable handoff summary")));
        assert!(input.iter().any(|item| item.get("call_id").and_then(|v| v.as_str()) == Some("call_1")));
        assert_eq!(stats.reasoning_dropped, 1);
        assert_eq!(stats.compaction_portable_messages, 1);
        assert!(stats.previous_response_id_dropped);
    }

    #[test]
    fn r50_same_model_and_compaction_helpers_are_byte_passthrough() {
        let body = br#"{"model":"grok-4.6","input":[{"type":"reasoning","encrypted_content":"x"}]}"#;
        assert!(portableize_cross_model_replay_r50(
            body,
            Some("grok-4.6"),
            Some("grok-4.6"),
            false,
        )
        .is_none());
        assert!(portableize_cross_model_replay_r50(
            body,
            Some("gpt-5.6-terra"),
            Some("grok-4.6"),
            true,
        )
        .is_none());
    }

    #[test]
    fn r50_cross_model_single_reasoning_input_becomes_empty_without_touching_model() {
        let body = br#"{
            "model":"grok-4.6",
            "input":{"type":"reasoning","encrypted_content":"GPT_ONLY_BLOB"}
        }"#;
        let (rewritten, stats) = portableize_cross_model_replay_r50(
            body,
            Some("gpt-5.6-terra"),
            Some("grok-4.6"),
            false,
        )
        .unwrap();
        let value: serde_json::Value = serde_json::from_slice(&rewritten).unwrap();
        assert_eq!(value["model"], "grok-4.6");
        assert_eq!(value["input"], serde_json::json!([]));
        assert_eq!(stats.reasoning_dropped, 1);
    }

'''
if test_anchor not in source:
    raise SystemExit("r50 replay: r46 focused-test anchor missing")
source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "portableize_cross_model_replay_r50",
    "previous_response_id_dropped",
    "reasoning_dropped",
    "compaction_portable_messages",
    "[model-switch-r50] action=portable_replay",
    "r50_cross_model_replay_drops_opaque_reasoning_and_keeps_compaction_summary",
):
    if invariant not in source:
        raise SystemExit(f"r50 replay invariant missing: {invariant}")

FORWARD.write_text(source, encoding="utf-8")
print("R50 SAME-SESSION CROSS-MODEL REPLAY PASS")
