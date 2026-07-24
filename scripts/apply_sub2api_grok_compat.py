from pathlib import Path

PATH = Path("crates/adapters/src/mapper/responses.rs")
text = PATH.read_text(encoding="utf-8")


def require(needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing anchor: {label}")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        print(f"[ok] {label}: already applied")
        return
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    text = text.replace(old, new, 1)
    print(f"[ok] {label}: applied")


impl_anchor = "impl RequestMapper for ResponsesPassthroughMapper {\n"
require(impl_anchor, "RequestMapper impl")

base_helpers = r'''
/// Enable the Grok Responses compatibility shim for a normal bearer provider
/// (for example Sub2API) only when the current request actually targets a
/// Grok model. Mixed Sub2API providers stay safe: Luna/GPT remain Responses
/// passthrough while grok-* reuses the existing Grok tool compatibility shim.
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
    text = text.replace(impl_anchor, base_helpers + impl_anchor, 1)
    print("[ok] base Grok compat helpers: applied")
else:
    print("[ok] base Grok compat helpers: already applied")

cache_helpers = r'''
/// Optional cache-routing compatibility for Grok Free OAuth behind Sub2API.
///
/// Keep Codex's existing `prompt_cache_key` untouched. When explicitly enabled,
/// append xAI native search tools in a deterministic order so a Grok Free request
/// with client-side Codex/MCP tools can still qualify for the cache-capable route.
/// This mirrors the body-side idea behind Sub2API's Grok client-tool cache switch.
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

    // Codex 0.144+ already supplies a stable session/thread-scoped key. Do not
    // synthesize, randomize, or replace it: that would destroy cache affinity.
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

    // Stable append order matters for prefix caching.
    if !has_tool_type(tools, "web_search") {
        tools.push(serde_json::json!({ "type": "web_search" }));
    }
    if !has_tool_type(tools, "x_search") {
        tools.push(serde_json::json!({ "type": "x_search" }));
    }

    // If there were no client tools, the native tools exist only as a routing
    // companion and must not alter model behavior. Tool-bearing turns keep the
    // caller's existing tool_choice (normally `auto`) so MCP remains callable.
    if !had_client_tools {
        obj.insert("tool_choice".to_owned(), Value::String("none".to_owned()));
    }

    serde_json::to_vec(&parsed)
        .ok()
        .map(Bytes::from)
        .unwrap_or(body)
}

'''

if "fn sub2api_grok_free_cache_compat_enabled" not in text:
    require(impl_anchor, "cache helper insertion")
    text = text.replace(impl_anchor, cache_helpers + impl_anchor, 1)
    print("[ok] Grok Free cache helpers: applied")
else:
    print("[ok] Grok Free cache helpers: already applied")

map_anchor = "    ) -> Result<RequestPlan, AdapterError> {\n"
if "let use_grok_compat = should_use_grok_compat(provider, &body);" not in text:
    require(map_anchor, "map_request body")
    text = text.replace(
        map_anchor,
        map_anchor + "        let use_grok_compat = should_use_grok_compat(provider, &body);\n",
        1,
    )
    print("[ok] request model gate: applied")
else:
    print("[ok] request model gate: already applied")

replace_once(
    "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider) {",
    "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)\n            || use_grok_compat\n        {",
    "Grok compaction gate",
)
replace_once(
    "let grok_shim_ctx = if crate::mapper::grok_build::is_grok_build_provider(provider) {",
    "let grok_shim_ctx = if use_grok_compat {",
    "request shim context gate",
)
replace_once(
    "let body = if crate::mapper::grok_build::is_grok_build_provider(provider) {",
    "let body = if use_grok_compat {",
    "request Grok adapter gate",
)

# Insert cache routing immediately after the Grok body adapter. Anchor only on
# the closing block + next stable comment so rustfmt changes inside the call do
# not make the patch brittle.
cache_apply = "        let body = apply_sub2api_grok_free_cache_compat(body, provider);\n"
if cache_apply not in text:
    observe_comment = "        // [MOC-234] 只读观测整合"
    idx_comment = text.find(observe_comment)
    if idx_comment < 0:
        raise SystemExit("missing anchor: observe comment after Grok body adapter")
    before = text[:idx_comment]
    block_end = before.rfind("        };\n\n")
    if block_end < 0:
        raise SystemExit("missing anchor: Grok body adapter closing block")
    insert_at = block_end + len("        };\n")
    text = text[:insert_at] + cache_apply + text[insert_at:]
    print("[ok] Free cache body routing: applied")
else:
    print("[ok] Free cache body routing: already applied")

replace_once(
    "if crate::mapper::grok_build::is_grok_build_provider(provider) {",
    "if should_use_grok_compat(provider, &request_plan.body) {",
    "response Grok shim gate",
)

# The Sub2API-specific test module is intentionally the final module in this
# file. Replacing from this marker to EOF is deterministic and leaves the large
# upstream `tests` module untouched.
test_marker = "#[cfg(test)]\nmod sub2api_grok_compat_tests {"
require(test_marker, "Sub2API test module")
text = text[: text.index(test_marker)] + r'''#[cfg(test)]
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
    fn free_cache_compat_preserves_prompt_cache_key_and_client_tools() {
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
    fn free_cache_compat_tool_free_turn_uses_native_tools_only_as_companions() {
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
    fn free_cache_compat_never_touches_luna() {
        let p = provider(true, true);
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","prompt_cache_key":"thread-1","tools":[]}"#,
        );
        let out = apply_sub2api_grok_free_cache_compat(body.clone(), &p);
        assert_eq!(out, body);
    }
}
'''
print("[ok] Sub2API Grok compat tests: refreshed")

PATH.write_text(text, encoding="utf-8")
print(f"patched {PATH}")
