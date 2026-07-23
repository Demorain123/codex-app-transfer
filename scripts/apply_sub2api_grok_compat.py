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

/// Optional compatibility mode for Grok Free OAuth behind Sub2API.
///
/// Sub2API v0.1.164 only selects its cache-capable mixed client/native-tool route
/// after it has positively identified the account as Grok Free. SSO-imported
/// accounts can remain "unknown" even though the user is actually on Free, which
/// leaves client-function requests on xAI's non-cacheable build-free route.
///
/// This explicit opt-in reproduces the body-side part of Sub2API's own Free cache
/// routing policy locally: keep the Codex-supplied `prompt_cache_key` untouched,
/// append missing native `web_search` / `x_search` tools in a deterministic order,
/// and (only for otherwise tool-free requests) set `tool_choice="none"` so the
/// native tools act purely as a cache-routing companion and cannot be selected.
///
/// For requests that already contain client tools, native search tools remain
/// selectable under `tool_choice="auto"`; this is the same trade-off warned about
/// by Sub2API's "client tool cache" toggle, so this behavior is never enabled
/// implicitly. Set provider extra `sub2apiGrokFreeCacheCompat=true` to opt in.
fn sub2api_grok_free_cache_compat_enabled(provider: &Provider, body: &Bytes) -> bool {
    let enabled = provider
        .extra
        .get("sub2apiGrokFreeCacheCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    enabled && sub2api_grok_compat_enabled(provider, body)
}

fn apply_sub2api_grok_free_cache_compat(body: Bytes, provider: &Provider) -> Bytes {
    if !sub2api_grok_free_cache_compat_enabled(provider, &body) {
        return body;
    }

    let Ok(mut parsed) = serde_json::from_slice::<Value>(&body) else {
        return body;
    };
    let Some(obj) = parsed.as_object_mut() else {
        return body;
    };

    // Do NOT synthesize or replace the key. Codex 0.144+ already sends the
    // thread-scoped `prompt_cache_key`; preserving that exact value is critical
    // for xAI sticky routing and prefix-cache reuse.
    if obj
        .get("prompt_cache_key")
        .and_then(Value::as_str)
        .is_none_or(|v| v.trim().is_empty())
    {
        tracing::warn!(
            target: "adapters::grok_cache",
            "Sub2API Grok Free cache compat enabled but request has no prompt_cache_key; cache hits may be unreliable"
        );
    }

    let had_client_tools = obj
        .get("tools")
        .and_then(Value::as_array)
        .is_some_and(|tools| !tools.is_empty());

    let tools = obj
        .entry("tools".to_owned())
        .or_insert_with(|| Value::Array(Vec::new()));
    let Some(tools) = tools.as_array_mut() else {
        return body;
    };

    let has_type = |tools: &[Value], wanted: &str| {
        tools.iter().any(|tool| {
            tool.get("type")
                .and_then(Value::as_str)
                .is_some_and(|kind| kind == wanted)
        })
    };

    // Fixed append order keeps the request stable across turns.
    if !has_type(tools, "web_search") {
        tools.push(serde_json::json!({ "type": "web_search" }));
    }
    if !has_type(tools, "x_search") {
        tools.push(serde_json::json!({ "type": "x_search" }));
    }

    // Tool-free turns can use native tools only as a routing signal without
    // changing model behavior. Tool-bearing turns intentionally retain their
    // existing choice (usually `auto`) so Codex client tools remain callable.
    if !had_client_tools {
        obj.insert("tool_choice".to_owned(), Value::String("none".to_owned()));
    }

    serde_json::to_vec(&parsed)
        .ok()
        .map(Bytes::from)
        .unwrap_or(body)
}
'''

if "fn sub2api_grok_compat_enabled" not in text:
    if helper_anchor not in text:
        raise SystemExit("helper anchor not found")
    text = text.replace(helper_anchor, helper_anchor + helper, 1)
elif "fn sub2api_grok_free_cache_compat_enabled" not in text:
    # Upgrade an already-patched branch by inserting the cache helpers directly
    # before the RequestMapper impl.
    impl_anchor = "impl RequestMapper for ResponsesPassthroughMapper {\n"
    cache_helper = helper[helper.index("\n/// Optional compatibility mode"):]
    if impl_anchor not in text:
        raise SystemExit("request mapper impl anchor not found")
    text = text.replace(impl_anchor, cache_helper + "\n" + impl_anchor, 1)

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

# Apply the optional Free cache route *after* the Grok tool shim so the native
# companion tools are not dropped/reshaped by the Grok adapter.
cache_apply_anchor = "        let body = if use_grok_compat {\n            crate::mapper::grok_build::adapt_grok_build_request_body(&body, provider)\n                .unwrap_or(body)\n        } else {\n            body\n        };\n"
cache_apply = cache_apply_anchor + "        let body = apply_sub2api_grok_free_cache_compat(body, provider);\n"
if "let body = apply_sub2api_grok_free_cache_compat(body, provider);" not in text:
    if cache_apply_anchor not in text:
        raise SystemExit("cache application anchor not found")
    text = text.replace(cache_apply_anchor, cache_apply, 1)

old = "if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "if should_use_grok_compat(provider, &request_plan.body) {"
# At this point the earlier request-side occurrence has already been replaced;
# the remaining occurrence is the response-side shim gate.
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("response shim gate not found")

# Replace the original compact test module with an expanded cache-aware version.
marker = "#[cfg(test)]\nmod sub2api_grok_compat_tests {"
if marker in text:
    text = text[: text.index(marker)]

text += r'''

#[cfg(test)]
mod sub2api_grok_compat_tests {
    use super::*;
    use serde_json::json;

    fn provider(enabled: bool, cache_enabled: bool) -> Provider {
        serde_json::from_value(json!({
            "id": "sub2api",
            "name": "Sub2API",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "test",
            "models": {},
            "sub2apiGrokCompat": enabled,
            "sub2apiGrokFreeCacheCompat": cache_enabled
        }))
        .expect("provider fixture")
    }

    #[test]
    fn sub2api_grok_compat_only_matches_grok_models() {
        let p = provider(true, false);
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
        let p = provider(false, false);
        assert!(!sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"grok-4.5"}"#)
        ));
    }

    #[test]
    fn free_cache_compat_preserves_codex_prompt_cache_key_and_adds_native_companions() {
        let p = provider(true, true);
        let original_key = "019f9082-3c25-7b00-84b4-3b4a14ff09f0";
        let body = Bytes::from(
            serde_json::to_vec(&json!({
                "model": "grok-4.5",
                "prompt_cache_key": original_key,
                "tool_choice": "auto",
                "tools": [{
                    "type": "function",
                    "name": "mcp__ask_user_questions__ask_user_questions",
                    "description": "test",
                    "parameters": {"type":"object","properties":{}}
                }],
                "input": []
            }))
            .unwrap(),
        );

        let out = apply_sub2api_grok_free_cache_compat(body, &p);
        let v: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(v["prompt_cache_key"], original_key);
        assert_eq!(v["tool_choice"], "auto");
        let tools = v["tools"].as_array().unwrap();
        assert!(tools.iter().any(|t| t["type"] == "function"));
        assert!(tools.iter().any(|t| t["type"] == "web_search"));
        assert!(tools.iter().any(|t| t["type"] == "x_search"));
    }

    #[test]
    fn free_cache_compat_tool_free_turn_disables_native_tool_execution() {
        let p = provider(true, true);
        let body = Bytes::from_static(
            br#"{"model":"grok-4.5","prompt_cache_key":"thread-1","input":[]}"#,
        );
        let out = apply_sub2api_grok_free_cache_compat(body, &p);
        let v: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(v["prompt_cache_key"], "thread-1");
        assert_eq!(v["tool_choice"], "none");
        let tools = v["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 2);
        assert_eq!(tools[0]["type"], "web_search");
        assert_eq!(tools[1]["type"], "x_search");
    }

    #[test]
    fn free_cache_compat_never_touches_non_grok_models() {
        let p = provider(true, true);
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","prompt_cache_key":"thread-1","tools":[]}"#,
        );
        let out = apply_sub2api_grok_free_cache_compat(body.clone(), &p);
        assert_eq!(out, body);
    }
}
'''

PATH.write_text(text, encoding="utf-8")
print(f"patched {PATH}")
