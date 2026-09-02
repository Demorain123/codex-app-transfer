from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R60-SUB2API-POST-COMPACTION-REPLAY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r60 post-compaction replay: anchor missing: {label}")
    return text.replace(old, new, 1)


text = FORWARD.read_text(encoding="utf-8")
if MARKER in text:
    print("r60 Sub2API post-compaction replay compatibility already applied")
    raise SystemExit(0)

helper_anchor = "pub async fn forward_handler(\n"
helper = r'''// CAS-R60-SUB2API-POST-COMPACTION-REPLAY
// Codex's native Responses continuation can replay a successful compact artifact as
// an input item with type="compaction".  Sub2API's OpenAI OAuth /responses route
// currently rejects that native item even though it can produce the compact summary
// itself.  Keep this compatibility shim deliberately provider-scoped: an official
// OpenAI Responses provider (or any provider without sub2apiGrokCompat=true) must see
// the original body byte-for-byte after the normal adapter path.
//
// The existing Responses->Chat converter already preserves this artifact by exposing
// encrypted_content as a user-visible compact-context message.  Mirror that semantic
// conversion here for Sub2API's native Responses passthrough path instead of dropping
// the artifact.  No compact text is logged.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
struct Sub2ApiPostCompactionReplayR60 {
    translated: usize,
    preserved_unrecognized: usize,
    input_items_before: usize,
    input_items_after: usize,
}

fn sub2api_post_compaction_replay_enabled_r60(
    provider: &codex_app_transfer_registry::Provider,
) -> bool {
    provider.api_format.trim().eq_ignore_ascii_case("responses")
        && provider
            .extra
            .get("sub2apiGrokCompat")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
}

fn translate_sub2api_post_compaction_replay_r60(
    body: &mut Bytes,
    provider: &codex_app_transfer_registry::Provider,
) -> Sub2ApiPostCompactionReplayR60 {
    if !sub2api_post_compaction_replay_enabled_r60(provider) {
        return Sub2ApiPostCompactionReplayR60::default();
    }

    let Ok(mut root) = serde_json::from_slice::<serde_json::Value>(body) else {
        return Sub2ApiPostCompactionReplayR60::default();
    };
    let Some(input) = root.get_mut("input").and_then(serde_json::Value::as_array_mut) else {
        return Sub2ApiPostCompactionReplayR60::default();
    };

    let before = input.len();
    let mut translated = 0usize;
    let mut preserved_unrecognized = 0usize;

    for item in input.iter_mut() {
        if item.get("type").and_then(serde_json::Value::as_str) != Some("compaction") {
            continue;
        }

        let encrypted_content = item
            .get("encrypted_content")
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned);

        let Some(encrypted_content) = encrypted_content else {
            // Never silently erase an artifact we do not understand.  Preserving it
            // may still let a future Sub2API version accept the native shape, while
            // logging only a count gives us a safe diagnostic signal.
            preserved_unrecognized += 1;
            continue;
        };

        *item = serde_json::json!({
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": format!(
                        "[Compacted conversation context]\n{encrypted_content}"
                    )
                }
            ]
        });
        translated += 1;
    }

    if translated > 0 {
        // serde_json::Value containing only parsed JSON is infallibly serializable in
        // practice.  Still fail closed: if serialization ever fails, keep the exact
        // original body instead of emitting a partially rewritten request.
        if let Ok(serialized) = serde_json::to_vec(&root) {
            *body = Bytes::from(serialized);
        } else {
            return Sub2ApiPostCompactionReplayR60 {
                translated: 0,
                preserved_unrecognized: preserved_unrecognized + translated,
                input_items_before: before,
                input_items_after: before,
            };
        }
    }

    Sub2ApiPostCompactionReplayR60 {
        translated,
        preserved_unrecognized,
        input_items_before: before,
        input_items_after: input.len(),
    }
}

#[cfg(test)]
mod sub2api_post_compaction_replay_r60_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "sub2api-r60-test",
            "name": "sub2api",
            "baseUrl": "http://127.0.0.1:8113/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "sk-test",
            "models": {},
            "sub2apiGrokCompat": compat
        }))
        .unwrap()
    }

    #[test]
    fn translates_valid_compaction_in_place_and_preserves_order() {
        let mut body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"message","role":"user","content":"before"},{"type":"compaction","encrypted_content":"summary-token"},{"type":"message","role":"user","content":"after"}]}"#,
        );
        let result = translate_sub2api_post_compaction_replay_r60(&mut body, &provider(true));
        assert_eq!(result.translated, 1);
        assert_eq!(result.preserved_unrecognized, 0);
        assert_eq!(result.input_items_before, 3);
        assert_eq!(result.input_items_after, 3);

        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        let input = value.get("input").and_then(serde_json::Value::as_array).unwrap();
        assert_eq!(input[0].get("type").and_then(serde_json::Value::as_str), Some("message"));
        assert_eq!(input[1].get("type").and_then(serde_json::Value::as_str), Some("message"));
        assert_eq!(input[1].get("role").and_then(serde_json::Value::as_str), Some("user"));
        assert_eq!(
            input[1]
                .pointer("/content/0/type")
                .and_then(serde_json::Value::as_str),
            Some("input_text")
        );
        assert_eq!(
            input[1]
                .pointer("/content/0/text")
                .and_then(serde_json::Value::as_str),
            Some("[Compacted conversation context]\nsummary-token")
        );
        assert_eq!(input[2].get("type").and_then(serde_json::Value::as_str), Some("message"));
    }

    #[test]
    fn blank_or_missing_compaction_payload_is_not_dropped() {
        let mut body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction","encrypted_content":"   "},{"type":"compaction"}]}"#,
        );
        let original = body.clone();
        let result = translate_sub2api_post_compaction_replay_r60(&mut body, &provider(true));
        assert_eq!(result.translated, 0);
        assert_eq!(result.preserved_unrecognized, 2);
        assert_eq!(body, original);
    }

    #[test]
    fn official_or_non_compat_responses_provider_is_byte_identical() {
        let mut body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction","encrypted_content":"summary-token"}]}"#,
        );
        let original = body.clone();
        let result = translate_sub2api_post_compaction_replay_r60(&mut body, &provider(false));
        assert_eq!(result, Sub2ApiPostCompactionReplayR60::default());
        assert_eq!(body, original);
    }
}

'''
text = replace_once(text, helper_anchor, helper + helper_anchor, "forward handler helper insertion")

call_anchor = '''    let mut plan = adapter.prepare_request(&client_path, body_bytes, &resolved.provider)?;

    // 5. 拼上游 URL —— base 末尾去 `/`,plan.upstream_path 必含 `/`
'''
call = r'''    let mut plan = adapter.prepare_request(&client_path, body_bytes, &resolved.provider)?;

    // CAS-R60-SUB2API-POST-COMPACTION-REPLAY-CALL
    // Apply only after the normal adapter has produced the final native Responses
    // wire body, and only for the explicit Sub2API compat provider.  Official OpenAI
    // providers therefore never enter this rewrite.
    let r60_compaction =
        translate_sub2api_post_compaction_replay_r60(&mut plan.body, &resolved.provider);
    if r60_compaction.translated > 0 || r60_compaction.preserved_unrecognized > 0 {
        let action = if r60_compaction.translated > 0 {
            "translate_compaction_for_sub2api"
        } else {
            "preserve_unrecognized_compaction"
        };
        proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[model-switch-r60] action={} translated={} preserved_unrecognized={} input_items_before={} input_items_after={} provider={} content_logged=false",
                action,
                r60_compaction.translated,
                r60_compaction.preserved_unrecognized,
                r60_compaction.input_items_before,
                r60_compaction.input_items_after,
                resolved.provider.id,
            ),
        );
    }

    // 5. 拼上游 URL —— base 末尾去 `/`,plan.upstream_path 必含 `/`
'''
text = replace_once(text, call_anchor, call, "post-adapter request rewrite call")

for marker in (
    MARKER,
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-CALL",
    "translate_sub2api_post_compaction_replay_r60",
    "sub2api_post_compaction_replay_enabled_r60",
    "translate_compaction_for_sub2api",
    "preserve_unrecognized_compaction",
    "[Compacted conversation context]",
    "content_logged=false",
    "official_or_non_compat_responses_provider_is_byte_identical",
):
    if marker not in text:
        raise SystemExit(f"r60 post-compaction replay invariant missing: {marker}")

FORWARD.write_text(text, encoding="utf-8")
print("R60 SUB2API POST-COMPACTION REPLAY PASS")
print("- explicit Sub2API Responses compat providers translate native compaction artifacts")
print("- encrypted_content is preserved as a standard user/input_text context message")
print("- item order/count are preserved; unknown/blank artifacts are never silently dropped")
print("- official/non-compat Responses providers remain byte-identical at this shim")
print("- compact content is never written to telemetry")
