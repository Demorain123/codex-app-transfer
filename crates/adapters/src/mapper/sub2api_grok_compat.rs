//! Sub2API Grok compatibility overlay.
//!
//! This file intentionally contains all Sub2API-specific runtime logic so that
//! upstream `mapper/responses.rs` only needs a handful of stable hook calls.
//! Keeping the overlay isolated makes future upstream syncs/rebases much less
//! conflict-prone.

use bytes::Bytes;
use codex_app_transfer_registry::Provider;
use serde_json::Value;

/// Explicit opt-in for a normal bearer Responses provider (for example
/// Sub2API), gated again by the actual request model. Mixed providers therefore
/// keep Luna/GPT as native Responses passthrough while only grok-* reuses the
/// upstream Grok tool compatibility machinery.
pub(crate) fn sub2api_grok_compat_enabled(provider: &Provider, body: &Bytes) -> bool {
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

/// Built-in Grok Build continues to work exactly as upstream intended; this
/// overlay only broadens the same path to explicitly opted-in Sub2API grok-*.
pub(crate) fn should_use_grok_compat(provider: &Provider, body: &Bytes) -> bool {
    crate::mapper::grok_build::is_grok_build_provider(provider)
        || sub2api_grok_compat_enabled(provider, body)
}

fn sub2api_grok_free_cache_compat_enabled(provider: &Provider, body: &Bytes) -> bool {
    let enabled = provider
        .extra
        .get("sub2apiGrokFreeCacheCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    enabled && sub2api_grok_compat_enabled(provider, body)
}

/// Optional cache-routing compatibility for Grok Free OAuth behind Sub2API.
///
/// Codex's existing `prompt_cache_key` is deliberately preserved byte-for-byte.
/// When explicitly enabled, native xAI search tools are appended in a stable
/// order so a request that also exposes client/MCP tools can qualify for the
/// cache-capable route. This remains opt-in because native tools may affect
/// automatic tool selection.
pub(crate) fn apply_sub2api_grok_free_cache_compat(body: Bytes, provider: &Provider) -> Bytes {
    if !sub2api_grok_free_cache_compat_enabled(provider, &body) {
        return body;
    }

    let Ok(mut parsed) = serde_json::from_slice::<Value>(&body) else {
        return body;
    };
    let Some(obj) = parsed.as_object_mut() else {
        return body;
    };

    // Never synthesize/randomize/replace the Codex cache key.
    if obj
        .get("prompt_cache_key")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .is_none()
    {
        tracing::warn!(
            target: "adapters::grok_cache",
            "Sub2API Grok Free cache compat is enabled but prompt_cache_key is missing"
        );
    }

    let had_client_tools = obj
        .get("tools")
        .and_then(Value::as_array)
        .is_some_and(|tools| !tools.is_empty());

    let tools_value = obj
        .entry("tools".to_owned())
        .or_insert_with(|| Value::Array(Vec::new()));
    let Some(tools) = tools_value.as_array_mut() else {
        return body;
    };

    fn has_tool_type(tools: &[Value], wanted: &str) -> bool {
        tools.iter().any(|tool| {
            tool.get("type")
                .and_then(Value::as_str)
                .is_some_and(|kind| kind == wanted)
        })
    }

    // Stable append order matters for prefix caching and prevents duplicates if
    // Sub2API/the client already supplied a native tool.
    if !has_tool_type(tools, "web_search") {
        tools.push(serde_json::json!({ "type": "web_search" }));
    }
    if !has_tool_type(tools, "x_search") {
        tools.push(serde_json::json!({ "type": "x_search" }));
    }

    // Tool-free turns use native tools only as routing companions. Tool-bearing
    // turns retain the caller's tool_choice (normally auto) so MCP remains usable.
    if !had_client_tools {
        obj.insert("tool_choice".to_owned(), Value::String("none".to_owned()));
    }

    serde_json::to_vec(&parsed)
        .ok()
        .map(Bytes::from)
        .unwrap_or(body)
}

#[cfg(test)]
mod tests {
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
    fn only_matches_grok_models() {
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
    fn requires_explicit_opt_in() {
        let p = provider(false, false);
        assert!(!sub2api_grok_compat_enabled(
            &p,
            &Bytes::from_static(br#"{"model":"grok-4.5"}"#)
        ));
    }

    #[test]
    fn cache_compat_preserves_prompt_cache_key_and_client_tools() {
        let p = provider(true, true);
        let key = "019f9082-3c25-7b00-84b4-3b4a14ff09f0";
        let body = Bytes::from(
            serde_json::to_vec(&json!({
                "model": "grok-4.5",
                "prompt_cache_key": key,
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
        assert_eq!(v["prompt_cache_key"], key);
        assert_eq!(v["tool_choice"], "auto");
        let tools = v["tools"].as_array().unwrap();
        assert!(tools.iter().any(|t| t["type"] == "function"));
        assert!(tools.iter().any(|t| t["type"] == "web_search"));
        assert!(tools.iter().any(|t| t["type"] == "x_search"));
    }

    #[test]
    fn cache_compat_tool_free_turn_uses_native_tools_only_as_companions() {
        let p = provider(true, true);
        let body =
            Bytes::from_static(br#"{"model":"grok-4.5","prompt_cache_key":"thread-1","input":[]}"#);
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
    fn cache_compat_never_touches_luna() {
        let p = provider(true, true);
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","prompt_cache_key":"thread-1","tools":[]}"#,
        );
        let out = apply_sub2api_grok_free_cache_compat(body.clone(), &p);
        assert_eq!(out, body);
    }
}
