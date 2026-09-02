from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
MARKER = "CAS-R60-SUB2API-POST-COMPACTION-REPLAY"
HOOK_MARKER = "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK"

sub = SUB2API.read_text(encoding="utf-8")
resp = RESPONSES.read_text(encoding="utf-8")

if MARKER in sub and HOOK_MARKER in resp:
    print("r60 Sub2API post-compaction replay compatibility already applied")
    raise SystemExit(0)

if "CAS-SUB2API-GROK-COMPAT-HOOK" not in resp:
    raise SystemExit("r60 requires the existing Sub2API Responses compatibility hook")
if "localize_compaction_summary_prefix" not in (ROOT / "crates/adapters/src/responses/compact.rs").read_text(encoding="utf-8"):
    raise SystemExit("r60 requires the existing compaction summary replay/localization helper")

if MARKER not in sub:
    anchor = "\n#[cfg(test)]\nmod tests {\n"
    if anchor not in sub:
        raise SystemExit("r60 sub2api helper test-module anchor missing")
    helper = r'''

// CAS-R60-SUB2API-POST-COMPACTION-REPLAY
// Codex remote-compaction output later re-enters a normal Responses request as
// input[type=compaction].  OpenAI understands that private item, but Sub2API's
// otherwise-compatible /responses endpoint rejects it with HTTP 400.  Our local
// compact implementation intentionally stores plaintext PREFIX+summary in the
// historical `encrypted_content` field (the field name is a protocol legacy),
// and the chat-adapter path already renders the same item as a user summary
// message.  Reuse that exact semantic lowering for Sub2API Responses passthrough.
fn sub2api_post_compaction_compat_enabled(provider: &Provider) -> bool {
    let explicit = provider
        .extra
        .get("sub2apiPostCompactionCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let existing_sub2api_opt_in = provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let named_sub2api = provider.name.trim().eq_ignore_ascii_case("sub2api");
    explicit || existing_sub2api_opt_in || named_sub2api
}

pub(crate) fn apply_sub2api_post_compaction_replay_compat(
    body: Bytes,
    provider: &Provider,
) -> Bytes {
    if !sub2api_post_compaction_compat_enabled(provider) {
        return body;
    }

    let request_bytes_before = body.len();
    let Ok(mut parsed) = serde_json::from_slice::<Value>(&body) else {
        return body;
    };
    let Some(input) = parsed.get_mut("input").and_then(Value::as_array_mut) else {
        return body;
    };

    let mut transformed = 0usize;
    for item in input.iter_mut() {
        let kind = item.get("type").and_then(Value::as_str);
        if !matches!(kind, Some("compaction" | "context_compaction" | "compaction_summary")) {
            continue;
        }
        let Some(summary) = item.get("encrypted_content").and_then(Value::as_str) else {
            // Do not silently discard a future/private shape that we cannot preserve.
            tracing::warn!(
                target: "adapters::sub2api_compaction",
                "[sub2api-r60] action=post_compaction_replay_skip reason=missing_encrypted_content"
            );
            continue;
        };
        let summary = summary.trim();
        if summary.is_empty() {
            tracing::warn!(
                target: "adapters::sub2api_compaction",
                "[sub2api-r60] action=post_compaction_replay_skip reason=empty_summary"
            );
            continue;
        }

        let summary = crate::responses::compact::localize_compaction_summary_prefix(summary);
        *item = serde_json::json!({
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": summary}],
        });
        transformed += 1;
    }

    if transformed == 0 {
        return body;
    }

    let Ok(out) = serde_json::to_vec(&parsed) else {
        return body;
    };
    tracing::warn!(
        target: "adapters::sub2api_compaction",
        transformed,
        request_bytes_before,
        request_bytes_after = out.len(),
        "[sub2api-r60] action=post_compaction_replay_rewrite"
    );
    Bytes::from(out)
}
'''
    sub = sub.replace(anchor, helper + anchor, 1)

    test_anchor = r'''    #[test]
    fn cache_compat_never_touches_luna() {
'''
    tests = r'''    #[test]
    fn r60_named_sub2api_rewrites_luna_compaction_to_standard_message() {
        let p = provider(false, false);
        let body = Bytes::from(
            serde_json::to_vec(&json!({
                "model": "gpt-5.6-luna",
                "input": [
                    {"type":"compaction","encrypted_content":"summary checkpoint"},
                    {"type":"message","role":"user","content":[{"type":"input_text","text":"continue"}]}
                ],
                "stream": true
            }))
            .unwrap(),
        );
        let out = apply_sub2api_post_compaction_replay_compat(body, &p);
        let v: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(v["input"][0]["type"], "message");
        assert_eq!(v["input"][0]["role"], "user");
        assert_eq!(v["input"][0]["content"][0]["type"], "input_text");
        assert_eq!(v["input"][0]["content"][0]["text"], "summary checkpoint");
        assert_eq!(v["input"][1]["type"], "message");
        assert_eq!(v["model"], "gpt-5.6-luna");
        assert_eq!(v["stream"], true);
    }

    #[test]
    fn r60_unrelated_provider_keeps_private_compaction_byte_identical() {
        let mut p = provider(false, false);
        p.name = "OpenAI".to_owned();
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction","encrypted_content":"summary checkpoint"}]}"#,
        );
        let out = apply_sub2api_post_compaction_replay_compat(body.clone(), &p);
        assert_eq!(out, body);
    }

    #[test]
    fn r60_malformed_compaction_is_not_silently_dropped() {
        let p = provider(false, false);
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction"}]}"#,
        );
        let out = apply_sub2api_post_compaction_replay_compat(body.clone(), &p);
        assert_eq!(out, body);
    }

'''
    if test_anchor not in sub:
        raise SystemExit("r60 sub2api test insertion anchor missing")
    sub = sub.replace(test_anchor, tests + test_anchor, 1)

if HOOK_MARKER not in resp:
    old = '''        let body = crate::mapper::sub2api_grok_compat::apply_sub2api_grok_free_cache_compat(
            body, provider,
        );

        // [MOC-234] 只读观测整合'''
    new = '''        let body = crate::mapper::sub2api_grok_compat::apply_sub2api_grok_free_cache_compat(
            body, provider,
        );
        // CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK
        // Lower Codex's private replay-only compaction item only for Sub2API.
        // Native/OpenAI Responses providers remain byte-level passthrough.
        let body = crate::mapper::sub2api_grok_compat::apply_sub2api_post_compaction_replay_compat(
            body, provider,
        );

        // [MOC-234] 只读观测整合'''
    if old not in resp:
        raise SystemExit("r60 Responses passthrough hook anchor missing")
    resp = resp.replace(old, new, 1)

for invariant in (
    MARKER,
    "apply_sub2api_post_compaction_replay_compat",
    "[sub2api-r60] action=post_compaction_replay_rewrite",
    "r60_named_sub2api_rewrites_luna_compaction_to_standard_message",
    "r60_unrelated_provider_keeps_private_compaction_byte_identical",
):
    if invariant not in sub:
        raise SystemExit(f"r60 Sub2API invariant missing: {invariant}")
if HOOK_MARKER not in resp:
    raise SystemExit("r60 Responses hook invariant missing")

SUB2API.write_text(sub, encoding="utf-8")
RESPONSES.write_text(resp, encoding="utf-8")
print("R60 SUB2API POST-COMPACTION REPLAY PASS")
print("- Sub2API compaction/context_compaction/compaction_summary inputs become standard user input_text messages")
print("- plaintext summary content is preserved; no model call is added")
print("- unrelated/native OpenAI Responses providers remain untouched")
print("- malformed private items fail visibly rather than being silently discarded")
