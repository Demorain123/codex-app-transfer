from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MARKER = "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION"

sub2api = SUB2API.read_text(encoding="utf-8")
responses = RESPONSES.read_text(encoding="utf-8")
compact = COMPACT.read_text(encoding="utf-8")

if MARKER in sub2api and MARKER in responses and MARKER in compact:
    print("r52 Sub2API cross-model compaction already applied")
    raise SystemExit(0)

# 1) Provider-level opt-in. The existing Sub2API Grok flag is already an explicit
#    acknowledgement that this mixed Responses provider needs the local compatibility
#    overlay. Reuse that provider identity for private Codex compaction too, regardless
#    of which model (Grok/GPT/Luna/Terra) is currently selected.
sub_anchor = '''/// Explicit opt-in for a normal bearer Responses provider (for example
/// Sub2API), gated again by the actual request model. Mixed providers therefore
'''
sub_insert = r'''// CAS-R52-SUB2API-CROSS-MODEL-COMPACTION
//
// Codex remote compaction v2 is a private Responses extension. A mixed Sub2API
// provider can faithfully proxy ordinary /responses for GPT/Luna while still rejecting
// the private compaction_trigger request with HTTP 400. The existing sub2apiGrokCompat
// flag is an explicit provider-level opt-in to this compatibility overlay, so use it as
// the safe scope for local compaction across *all* models on that provider. Direct
// OpenAI/native Responses providers without the flag remain untouched.
pub(crate) fn sub2api_local_compaction_enabled(provider: &Provider) -> bool {
    provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

'''
if MARKER not in sub2api:
    if sub_anchor not in sub2api:
        raise SystemExit("r52: Sub2API opt-in anchor missing")
    sub2api = sub2api.replace(sub_anchor, sub_insert + sub_anchor, 1)

sub_test_anchor = '''    #[test]
    fn only_matches_grok_models() {
'''
sub_tests = r'''    #[test]
    fn r52_local_compaction_uses_provider_opt_in_not_model_family() {
        let enabled = provider(true, false);
        let disabled = provider(false, false);
        assert!(sub2api_local_compaction_enabled(&enabled));
        assert!(!sub2api_local_compaction_enabled(&disabled));

        // The helper is deliberately provider-scoped: Luna/Terra on the same mixed
        // Sub2API provider need local Codex private compaction even though ordinary
        // Responses requests remain native passthrough.
        assert!(sub2api_local_compaction_enabled(&enabled));
    }

'''
if "r52_local_compaction_uses_provider_opt_in_not_model_family" not in sub2api:
    if sub_test_anchor not in sub2api:
        raise SystemExit("r52: Sub2API test anchor missing")
    sub2api = sub2api.replace(sub_test_anchor, sub_tests + sub_test_anchor, 1)

# 2) Responses mapper: locally implement V1/V2 compact for the explicitly opted-in
#    mixed Sub2API provider. Ordinary turns remain 1:1 native Responses passthrough.
condition_old = '''        if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)
            || use_grok_compat
        {
'''
condition_new = '''        let use_sub2api_local_compaction =
            crate::mapper::sub2api_grok_compat::sub2api_local_compaction_enabled(provider);
        // CAS-R52-SUB2API-CROSS-MODEL-COMPACTION
        // Sub2API ordinary Responses can be native while Codex's private remote
        // compaction v2 extension is not. Handle only compact requests locally; normal
        // GPT/Luna/Terra turns still take the strict passthrough branch below.
        if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)
            || use_grok_compat
            || use_sub2api_local_compaction
        {
'''
if MARKER not in responses:
    if condition_old not in responses:
        raise SystemExit("r52: responses local-compaction condition anchor missing")
    responses = responses.replace(condition_old, condition_new, 1)

kind_anchor = '''            if let Some(kind) = crate::responses::compact::detect_compact(client_path, &body) {
                let stripped = match kind {
'''
kind_new = '''            if let Some(kind) = crate::responses::compact::detect_compact(client_path, &body) {
                if use_sub2api_local_compaction && !use_grok_compat {
                    let model = serde_json::from_slice::<Value>(&body)
                        .ok()
                        .and_then(|value| value.get("model").and_then(Value::as_str).map(str::to_owned))
                        .unwrap_or_else(|| "<unknown>".to_owned());
                    tracing::warn!(
                        target: "adapters::sub2api_compact",
                        "[model-switch-r52] action=local_private_compaction model={} reason=sub2api_private_compaction_unsupported",
                        model,
                    );
                }
                let stripped = match kind {
'''
if "[model-switch-r52] action=local_private_compaction" not in responses:
    if kind_anchor not in responses:
        raise SystemExit("r52: responses compact logging anchor missing")
    responses = responses.replace(kind_anchor, kind_new, 1)

# 3) Local compact history itself must be portable. A previous compaction item is a
#    plaintext handoff summary despite the historical encrypted_content field name.
#    Sending that private item into a different model/provider can 400; lower it to a
#    public user message. Reasoning is already intentionally discarded for compact.
compact_old = '''    input_array.retain(|item| item.get("type").and_then(|t| t.as_str()) != Some("reasoning"));
    // [MOC-243] 仅在「prev_id 非空 且 input(剥 trigger/reasoning 后、加 summary
'''
compact_new = r'''    // CAS-R52-SUB2API-CROSS-MODEL-COMPACTION
    // Portable compact history boundary. Keep visible conversation/tool history, drop
    // opaque reasoning, and lower any prior Codex compaction item to a normal user
    // message. `encrypted_content` here is plaintext SUMMARY_PREFIX + summary (see this
    // module's protocol notes), so no information is lost. This makes a Grok-produced
    // checkpoint consumable by Luna/GPT and vice versa without mutating the rollout.
    let mut portable_input = Vec::with_capacity(input_array.len());
    for item in input_array {
        let kind = item.get("type").and_then(|t| t.as_str()).unwrap_or("");
        match kind {
            "reasoning" => {}
            "compaction" | "context_compaction" | "compaction_summary" => {
                let summary = item
                    .get("encrypted_content")
                    .and_then(|value| value.as_str())
                    .unwrap_or("")
                    .trim();
                if !summary.is_empty() {
                    portable_input.push(json!({
                        "type": "message",
                        "role": "user",
                        "content": localize_compaction_summary_prefix(summary),
                    }));
                }
            }
            _ => portable_input.push(item),
        }
    }
    input_array = portable_input;
    // [MOC-243] 仅在「prev_id 非空 且 input(剥 trigger/reasoning 后、加 summary
'''
if MARKER not in compact:
    if compact_old not in compact:
        raise SystemExit("r52: compact reasoning-filter anchor missing")
    compact = compact.replace(compact_old, compact_new, 1)

compact_test_anchor = '''    #[test]
    fn build_compact_responses_body_strips_v2_trigger_and_injects_summarize_prompt() {
'''
compact_tests = r'''    #[test]
    fn r52_compact_responses_history_lowers_prior_compaction_and_drops_reasoning() {
        let body = json!({
            "model": "gpt-5.6-luna",
            "input": [
                {"type":"message","role":"user","content":"visible user history"},
                {"type":"compaction","encrypted_content":"portable checkpoint from grok"},
                {"type":"reasoning","encrypted_content":"FOREIGN_OPAQUE_REASONING"}
            ],
            "reasoning": {"effort":"medium"}
        });
        let out = build_compact_responses_body(&serde_json::to_vec(&body).unwrap()).unwrap();
        let parsed: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(parsed["model"], "gpt-5.6-luna");
        assert_eq!(parsed["stream"], false);
        let input = parsed["input"].as_array().unwrap();
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("reasoning")));
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("compaction")));
        assert!(input.iter().any(|item| {
            item.get("content")
                .and_then(|v| v.as_str())
                .is_some_and(|text| text.contains("portable checkpoint from grok"))
        }));
        assert!(input.last().and_then(|item| item.get("content")).and_then(|v| v.as_str())
            .is_some_and(|text| text.contains("CONTEXT CHECKPOINT")));
        let raw = String::from_utf8(out).unwrap();
        assert!(!raw.contains("FOREIGN_OPAQUE_REASONING"));
    }

'''
if "r52_compact_responses_history_lowers_prior_compaction_and_drops_reasoning" not in compact:
    if compact_test_anchor not in compact:
        raise SystemExit("r52: compact test anchor missing")
    compact = compact.replace(compact_test_anchor, compact_tests + compact_test_anchor, 1)

for text, name, invariants in (
    (sub2api, "sub2api_grok_compat.rs", (
        MARKER,
        "sub2api_local_compaction_enabled",
        "r52_local_compaction_uses_provider_opt_in_not_model_family",
    )),
    (responses, "responses.rs", (
        MARKER,
        "use_sub2api_local_compaction",
        "[model-switch-r52] action=local_private_compaction",
    )),
    (compact, "compact.rs", (
        MARKER,
        "portable_input",
        "localize_compaction_summary_prefix(summary)",
        "r52_compact_responses_history_lowers_prior_compaction_and_drops_reasoning",
    )),
):
    for invariant in invariants:
        if invariant not in text:
            raise SystemExit(f"r52 invariant missing in {name}: {invariant}")

SUB2API.write_text(sub2api, encoding="utf-8")
RESPONSES.write_text(responses, encoding="utf-8")
COMPACT.write_text(compact, encoding="utf-8")
print("R52 SUB2API CROSS-MODEL COMPACTION PASS")
print("- explicit Sub2API compat providers locally implement Codex private compaction for every model")
print("- ordinary GPT/Luna/Terra Responses turns remain native passthrough")
print("- prior compaction summaries are lowered to portable user messages for summarization")
print("- opaque reasoning is excluded from compact history while visible/tool history remains")
