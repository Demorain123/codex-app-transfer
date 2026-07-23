from pathlib import Path

PATH = Path("crates/adapters/src/mapper/responses.rs")
text = PATH.read_text(encoding="utf-8")

helper_anchor = "#[derive(Debug, Default, Clone, Copy)]\npub(crate) struct ResponsesPassthroughMapper;\n"
helper = r'''

/// Enable the Grok Responses compatibility shim for a normal bearer provider
/// (for example Sub2API) only when the current request actually targets a
/// Grok model. This keeps mixed Sub2API providers safe: Luna/GPT requests stay
/// byte-for-byte Responses passthrough while grok-* gets the existing
/// custom/namespace/tool_search compatibility path.
fn sub2api_grok_compat_enabled(provider: &Provider, body: &Bytes) -> bool {
    let enabled = provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !enabled {
        return false;
    }

    let Ok(parsed) = serde_json::from_slice::<Value>(body) else {
        return false;
    };
    let Some(model) = parsed.get("model").and_then(Value::as_str) else {
        return false;
    };
    let model = model.trim().to_ascii_lowercase();
    model == "grok" || model.starts_with("grok-") || model.starts_with("grok/")
}

fn should_use_grok_compat(provider: &Provider, body: &Bytes) -> bool {
    crate::mapper::grok_build::is_grok_build_provider(provider)
        || sub2api_grok_compat_enabled(provider, body)
}
'''

if "fn sub2api_grok_compat_enabled" not in text:
    if helper_anchor not in text:
        raise SystemExit("helper anchor not found")
    text = text.replace(helper_anchor, helper_anchor + helper, 1)

map_anchor = "    ) -> Result<RequestPlan, AdapterError> {\n"
if "let use_grok_compat = should_use_grok_compat(provider, &body);" not in text:
    if map_anchor not in text:
        raise SystemExit("map_request anchor not found")
    text = text.replace(
        map_anchor,
        map_anchor + "        let use_grok_compat = should_use_grok_compat(provider, &body);\n",
        1,
    )

old = "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider) {"
new = "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider) || use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("compaction gate not found")

old = "let grok_shim_ctx = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let grok_shim_ctx = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("request shim context gate not found")

old = "let body = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let body = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("request adapter gate not found")

old = "if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "if should_use_grok_compat(provider, &request_plan.body) {"
# At this point the earlier request-side occurrence has already been replaced;
# the remaining occurrence is the response-side shim gate.
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("response shim gate not found")

if "sub2api_grok_compat_only_matches_grok_models" not in text:
    text += r'''

#[cfg(test)]
mod sub2api_grok_compat_tests {
    use super::*;
    use serde_json::json;

    fn provider(enabled: bool) -> Provider {
        serde_json::from_value(json!({
            "id": "sub2api",
            "name": "Sub2API",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "test",
            "models": {},
            "sub2apiGrokCompat": enabled
        }))
        .expect("provider fixture")
    }

    #[test]
    fn sub2api_grok_compat_only_matches_grok_models() {
        let p = provider(true);
        assert!(sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"grok-4.5"}"#)
        ));
        assert!(sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"grok/something"}"#)
        ));
        assert!(!sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"gpt-5.6-luna"}"#)
        ));
        assert!(!sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"gpt-5.4"}"#)
        ));
    }

    #[test]
    fn sub2api_grok_compat_requires_explicit_opt_in() {
        let p = provider(false);
        assert!(!sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"grok-4.5"}"#)
        ));
    }
}
'''

PATH.write_text(text, encoding="utf-8")
print(f"patched {PATH}")
