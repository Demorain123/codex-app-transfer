from pathlib import Path

RESPONSES = Path("crates/adapters/src/mapper/responses.rs")
MAPPER_MOD = Path("crates/adapters/src/mapper/mod.rs")
COMPAT = Path("crates/adapters/src/mapper/sub2api_grok_compat.rs")

COMPAT_SOURCE = r'''//! Sub2API Grok compatibility overlay.
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
    fn cache_compat_never_touches_luna() {
        let p = provider(true, true);
        let body = Bytes::from_static(
            br#"{"model":"gpt-5.6-luna","prompt_cache_key":"thread-1","tools":[]}"#,
        );
        let out = apply_sub2api_grok_free_cache_compat(body.clone(), &p);
        assert_eq!(out, body);
    }
}
'''

HOOK = "// CAS-SUB2API-GROK-COMPAT-HOOK"


def remove_rust_module(text: str, marker: str) -> str:
    """Remove a Rust module beginning at marker by brace counting."""
    start = text.find(marker)
    if start < 0:
        return text
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"malformed module at {marker}")
    depth = 0
    i = brace
    in_str = False
    escape = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in " \t\r\n":
                        end += 1
                    return text[:start] + text[end:]
        i += 1
    raise SystemExit(f"unterminated module at {marker}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


# 1) Isolated overlay module: authoritative source of all Sub2API runtime logic.
COMPAT.write_text(COMPAT_SOURCE, encoding="utf-8")
print(f"[ok] overlay module refreshed: {COMPAT}")

# 2) One-line module registration in upstream mapper/mod.rs.
mod_text = MAPPER_MOD.read_text(encoding="utf-8")
mod_line = "pub(crate) mod sub2api_grok_compat;\n"
if mod_line not in mod_text:
    anchor = "pub(crate) mod responses;\n"
    if anchor not in mod_text:
        raise SystemExit("missing anchor: mapper responses module declaration")
    mod_text = mod_text.replace(anchor, anchor + f"{HOOK}\n" + mod_line, 1)
    print("[ok] mapper module hook: applied")
else:
    print("[ok] mapper module hook: already applied")
MAPPER_MOD.write_text(mod_text, encoding="utf-8")

# 3) Thin hooks in upstream responses.rs.
text = RESPONSES.read_text(encoding="utf-8")

# Migrate old inline implementation from earlier compat builds.
legacy_start = text.find("/// Enable the Grok Responses compatibility shim for a normal bearer provider")
impl_anchor = "impl RequestMapper for ResponsesPassthroughMapper {\n"
if legacy_start >= 0:
    impl_pos = text.find(impl_anchor, legacy_start)
    if impl_pos < 0:
        raise SystemExit("legacy inline helper found but RequestMapper anchor missing")
    text = text[:legacy_start] + text[impl_pos:]
    print("[ok] migrated legacy inline helpers out of responses.rs")

text = remove_rust_module(text, "#[cfg(test)]\nmod sub2api_grok_compat_tests {")

# Request gate: scope insertion to RequestMapper impl so future unrelated methods
# with the same return type cannot steal the anchor.
if "crate::mapper::sub2api_grok_compat::should_use_grok_compat(provider, &body)" not in text:
    impl_pos = text.find(impl_anchor)
    if impl_pos < 0:
        raise SystemExit("missing anchor: RequestMapper impl")
    sig = "    ) -> Result<RequestPlan, AdapterError> {\n"
    sig_pos = text.find(sig, impl_pos)
    if sig_pos < 0:
        raise SystemExit("missing anchor: Responses map_request signature")
    insert_at = sig_pos + len(sig)
    text = (
        text[:insert_at]
        + f"        {HOOK}\n"
        + "        let use_grok_compat = crate::mapper::sub2api_grok_compat::should_use_grok_compat(provider, &body);\n"
        + text[insert_at:]
    )
    print("[ok] request model gate: applied")
else:
    # Migrate old unqualified call if present.
    text = text.replace(
        "let use_grok_compat = should_use_grok_compat(provider, &body);",
        "let use_grok_compat = crate::mapper::sub2api_grok_compat::should_use_grok_compat(provider, &body);",
        1,
    )
    print("[ok] request model gate: already applied")

# Built-in upstream Grok gate → built-in OR explicit Sub2API grok-*.
old = "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider) {"
new = "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)\n            || use_grok_compat\n        {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: Grok compaction gate")

old = "let grok_shim_ctx = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let grok_shim_ctx = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: request shim context gate")

old = "let body = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let body = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: request Grok adapter gate")

cache_call = (
    "        let body = crate::mapper::sub2api_grok_compat::"
    "apply_sub2api_grok_free_cache_compat(body, provider);\n"
)
if cache_call not in text:
    # Migrate old unqualified call first.
    old_call = "        let body = apply_sub2api_grok_free_cache_compat(body, provider);\n"
    if old_call in text:
        text = text.replace(old_call, f"        {HOOK}\n" + cache_call, 1)
    else:
        observe_comment = "        // [MOC-234] 只读观测整合"
        idx_comment = text.find(observe_comment)
        if idx_comment < 0:
            raise SystemExit("missing anchor: observe comment after Grok body adapter")
        before = text[:idx_comment]
        block_end = before.rfind("        };\n\n")
        if block_end < 0:
            raise SystemExit("missing anchor: Grok body adapter closing block")
        insert_at = block_end + len("        };\n")
        text = text[:insert_at] + f"        {HOOK}\n" + cache_call + text[insert_at:]
    print("[ok] Free cache body routing: applied")
else:
    print("[ok] Free cache body routing: already applied")

old = "if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "if crate::mapper::sub2api_grok_compat::should_use_grok_compat(provider, &request_plan.body) {"
legacy = "if should_use_grok_compat(provider, &request_plan.body) {"
if legacy in text:
    text = text.replace(legacy, new, 1)
elif old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: response Grok shim gate")

RESPONSES.write_text(text, encoding="utf-8")
print(f"[ok] thin responses hooks refreshed: {RESPONSES}")
