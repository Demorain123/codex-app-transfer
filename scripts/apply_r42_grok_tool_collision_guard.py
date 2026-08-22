from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "crates/adapters/src/mapper/grok_build.rs"
MARKER = "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD"

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("r42 Grok effective tool collision guard: already applied")
    raise SystemExit(0)

start_marker = "/// 按 responses-flat function `name` 去重"
end_marker = "\n/// 规整一个 input item"
start = text.find(start_marker)
if start < 0:
    raise SystemExit("r42 grok tool collision guard: legacy dedup start anchor missing")
end = text.find(end_marker, start)
if end < 0:
    raise SystemExit("r42 grok tool collision guard: legacy dedup end anchor missing")

replacement = r'''// CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD
/// Grok validates one provider-visible namespace across native tools and client functions.
/// A native `{type:"web_search"}` and a function `{type:"function",name:"web_search"}`
/// therefore collide even though their JSON shapes differ. Return the name Grok actually
/// sees on the wire; for native tools the type itself is the effective name.
fn grok_effective_tool_name(tool: &Value) -> Option<&str> {
    let ty = tool.get("type").and_then(Value::as_str).unwrap_or("");
    if ty == "function" {
        return tool
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty());
    }
    (!ty.is_empty()).then_some(ty)
}

/// Final-wire deduplication. Preserve the first stable declaration because top-level
/// Codex tools are pushed before tool_search-discovered tools, matching the historical
/// function/function precedence and avoiding response-routing surprises.
fn dedup_grok_tools_by_name(out: &mut Vec<Value>) {
    let mut counts: std::collections::BTreeMap<String, usize> =
        std::collections::BTreeMap::new();
    for tool in out.iter() {
        if let Some(name) = grok_effective_tool_name(tool) {
            *counts.entry(name.to_owned()).or_default() += 1;
        }
    }
    for (name, count) in counts.iter().filter(|(_, count)| **count > 1) {
        tracing::warn!(
            target: "adapters::grok_tools",
            effective_name = %name,
            before = *count,
            after = 1usize,
            action = "deduplicated",
            "[grok-tool-collision] repaired duplicate provider-visible Grok tool name"
        );
    }

    let mut seen = std::collections::HashSet::new();
    out.retain(|tool| match grok_effective_tool_name(tool) {
        Some(name) => seen.insert(name.to_owned()),
        None => true,
    });

    // This algorithm is intentionally total for every named wire tool. Keep the invariant
    // next to the mutation so future tool-shape changes are caught immediately in tests/dev.
    debug_assert!({
        let mut verify = std::collections::HashSet::new();
        out.iter().all(|tool| {
            grok_effective_tool_name(tool)
                .map(|name| verify.insert(name.to_owned()))
                .unwrap_or(true)
        })
    });
}
'''
text = text[:start] + replacement + text[end:]

anchor = "    #[test]\n    fn leg3_rewrites_tool_call_history_and_injects_discovered() {"
if anchor not in text:
    raise SystemExit("r42 grok tool collision guard: test insertion anchor missing")

tests = r'''    fn r42_effective_count(tools: &[Value], expected: &str) -> usize {
        tools
            .iter()
            .filter(|tool| grok_effective_tool_name(tool) == Some(expected))
            .count()
    }

    #[test]
    fn grok_tool_collision_r42_native_plus_function_web_search_is_one() {
        let mut tools = vec![
            json!({"type":"web_search"}),
            json!({"type":"function","name":"web_search","parameters":{"type":"object"}}),
        ];
        dedup_grok_tools_by_name(&mut tools);
        assert_eq!(r42_effective_count(&tools, "web_search"), 1);
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0]["type"], "web_search", "first stable declaration wins");
    }

    #[test]
    fn grok_tool_collision_r42_duplicate_native_web_search_is_one() {
        let mut tools = vec![json!({"type":"web_search"}), json!({"type":"web_search"})];
        dedup_grok_tools_by_name(&mut tools);
        assert_eq!(tools, vec![json!({"type":"web_search"})]);
    }

    #[test]
    fn grok_tool_collision_r42_function_first_preserves_client_routing() {
        let mut tools = vec![
            json!({"type":"function","name":"web_search","parameters":{"type":"object"}}),
            json!({"type":"web_search"}),
        ];
        dedup_grok_tools_by_name(&mut tools);
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0]["type"], "function", "do not silently replace an earlier client tool");
        assert_eq!(tools[0]["name"], "web_search");
    }

    #[test]
    fn grok_tool_collision_r42_ordinary_function_duplicate_still_dedups() {
        let mut tools = vec![
            json!({"type":"function","name":"foo","parameters":{"type":"object"}}),
            json!({"type":"function","name":"foo","parameters":{"type":"object"}}),
        ];
        dedup_grok_tools_by_name(&mut tools);
        assert_eq!(r42_effective_count(&tools, "foo"), 1);
    }

    #[test]
    fn grok_tool_collision_r42_unique_tools_are_preserved() {
        let mut tools = vec![
            json!({"type":"function","name":"foo","parameters":{"type":"object"}}),
            json!({"type":"web_search"}),
            json!({"type":"x_search"}),
        ];
        dedup_grok_tools_by_name(&mut tools);
        assert_eq!(tools.len(), 3);
        assert_eq!(r42_effective_count(&tools, "foo"), 1);
        assert_eq!(r42_effective_count(&tools, "web_search"), 1);
        assert_eq!(r42_effective_count(&tools, "x_search"), 1);
    }

    #[test]
    fn grok_tool_collision_r42_discovered_function_cannot_duplicate_native_web_search() {
        let body = serde_json::to_vec(&json!({
            "model":"grok-4.6",
            "tools":[{"type":"web_search_preview","external_web_access":true}],
            "input":[{
                "type":"tool_search_output",
                "call_id":"discover-web",
                "status":"completed",
                "tools":[{
                    "type":"function",
                    "name":"web_search",
                    "description":"client-side discovered web tool",
                    "parameters":{"type":"object","properties":{}}
                }]
            }]
        })).unwrap();
        let out = adapt_grok_build_request_body(&Bytes::from(body), &grok_provider())
            .expect("wire should be adapted");
        let value: Value = serde_json::from_slice(&out).unwrap();
        let tools = value["tools"].as_array().expect("adapted tools array");
        assert_eq!(r42_effective_count(tools, "web_search"), 1,
            "final Grok wire must never contain duplicate provider-visible web_search names");
    }

'''
text = text.replace(anchor, tests + anchor, 1)
TARGET.write_text(text, encoding="utf-8")
print("r42 Grok effective tool collision guard: applied")
