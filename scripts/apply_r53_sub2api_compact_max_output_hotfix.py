from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
MARKER = "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT"

sub2api = SUB2API.read_text(encoding="utf-8")
responses = RESPONSES.read_text(encoding="utf-8")

if MARKER in sub2api and MARKER in responses:
    print("r53 Sub2API compact max_output_tokens hotfix already applied")
    raise SystemExit(0)

helper_anchor = '''/// Explicit opt-in for a normal bearer Responses provider (for example
/// Sub2API), gated again by the actual request model. Mixed providers therefore
'''
helper = r'''// CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT
//
// Sub2API OpenAI OAuth auto-passthrough can reject Responses requests containing
// `max_output_tokens` with upstream HTTP 400 even though ordinary Codex turns work.
// Our local compact synthetic body previously injected 20_000 unconditionally, so a
// private compact that had already been translated to an ordinary /responses request
// could still fail before model inference. Scope this compatibility shim only to the
// non-Grok Sub2API local-compact branch; Grok keeps its proven r52 body unchanged.
pub(crate) fn sanitize_sub2api_non_grok_compact_body_r53(body: Bytes) -> Bytes {
    let Ok(mut parsed) = serde_json::from_slice::<Value>(&body) else {
        tracing::warn!(
            target: "adapters::sub2api_compact",
            "[model-switch-r53] action=strip_max_output_tokens parse_failed=true"
        );
        return body;
    };
    let Some(obj) = parsed.as_object_mut() else {
        return body;
    };

    let model = obj
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or("<unknown>")
        .to_owned();
    let removed = obj.remove("max_output_tokens").is_some();
    let stream = obj.get("stream").and_then(Value::as_bool);
    let has_reasoning = obj.get("reasoning").is_some();
    let tools = obj
        .get("tools")
        .and_then(Value::as_array)
        .map(|v| v.len())
        .unwrap_or(0);
    let input_items = obj
        .get("input")
        .and_then(Value::as_array)
        .map(|v| v.len())
        .unwrap_or(0);

    tracing::warn!(
        target: "adapters::sub2api_compact",
        "[model-switch-r53] action=strip_max_output_tokens model={} removed={} stream={:?} reasoning={} tools={} input_items={} reason=sub2api_oauth_responses_compat",
        model,
        removed,
        stream,
        has_reasoning,
        tools,
        input_items,
    );

    serde_json::to_vec(&parsed)
        .ok()
        .map(Bytes::from)
        .unwrap_or(body)
}

'''
if MARKER not in sub2api:
    if helper_anchor not in sub2api:
        raise SystemExit("r53: Sub2API helper anchor missing")
    sub2api = sub2api.replace(helper_anchor, helper + helper_anchor, 1)

branch_old = r'''                let summ = if use_grok_compat
                    || crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)
                {
                    crate::mapper::grok_build::adapt_grok_build_request_body(&summ, provider)
                        .unwrap_or(summ)
                } else {
                    summ
                };
'''
branch_new = r'''                let summ = if use_grok_compat
                    || crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)
                {
                    crate::mapper::grok_build::adapt_grok_build_request_body(&summ, provider)
                        .unwrap_or(summ)
                } else {
                    // CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT
                    // r52 already proved this is the non-Grok Sub2API local-compact path.
                    // Keep the native Responses body, but remove the one parameter known
                    // to be rejected by OpenAI OAuth auto-passthrough accounts.
                    crate::mapper::sub2api_grok_compat::sanitize_sub2api_non_grok_compact_body_r53(summ)
                };
'''
if MARKER not in responses:
    if branch_old not in responses:
        raise SystemExit("r53: r52 non-Grok compact branch anchor missing")
    responses = responses.replace(branch_old, branch_new, 1)

# Focused unit coverage lives beside the Sub2API helper and proves no unrelated field
# is rewritten. The response mapper branch test is locked by marker/invariant checks.
test_anchor = '''    #[test]
    fn only_matches_grok_models() {
'''
tests = r'''    #[test]
    fn r53_non_grok_compact_strips_only_max_output_tokens() {
        let body = Bytes::from(
            serde_json::to_vec(&json!({
                "model": "gpt-5.6-luna",
                "stream": false,
                "max_output_tokens": 20000,
                "reasoning": {"effort":"high"},
                "input": [
                    {"type":"message","role":"user","content":"keep history"},
                    {"type":"message","role":"user","content":"summarize"}
                ]
            }))
            .unwrap(),
        );
        let out = sanitize_sub2api_non_grok_compact_body_r53(body);
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert!(parsed.get("max_output_tokens").is_none());
        assert_eq!(parsed["model"], "gpt-5.6-luna");
        assert_eq!(parsed["stream"], false);
        assert_eq!(parsed["reasoning"]["effort"], "high");
        assert_eq!(parsed["input"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn r53_non_grok_compact_is_idempotent_without_max_output_tokens() {
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","stream":false,"input":[{"role":"user","content":"x"}]}"#,
        );
        let out = sanitize_sub2api_non_grok_compact_body_r53(body.clone());
        let before: Value = serde_json::from_slice(&body).unwrap();
        let after: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(before, after);
    }

'''
if "r53_non_grok_compact_strips_only_max_output_tokens" not in sub2api:
    if test_anchor not in sub2api:
        raise SystemExit("r53: Sub2API test anchor missing")
    sub2api = sub2api.replace(test_anchor, tests + test_anchor, 1)

for text, name, invariants in (
    (sub2api, "sub2api_grok_compat.rs", (
        MARKER,
        "sanitize_sub2api_non_grok_compact_body_r53",
        "[model-switch-r53] action=strip_max_output_tokens",
        "r53_non_grok_compact_strips_only_max_output_tokens",
    )),
    (responses, "responses.rs", (
        MARKER,
        "sanitize_sub2api_non_grok_compact_body_r53(summ)",
        "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
    )),
):
    for invariant in invariants:
        if invariant not in text:
            raise SystemExit(f"r53 invariant missing in {name}: {invariant}")

SUB2API.write_text(sub2api, encoding="utf-8")
RESPONSES.write_text(responses, encoding="utf-8")
print("R53 SUB2API OAUTH COMPACT MAX-OUTPUT PASS")
print("- non-Grok Sub2API local compact removes max_output_tokens before forwarding")
print("- Grok compact request shape is unchanged")
print("- ordinary model turns and exact Codex session/thread identity are unchanged")
