from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
GROK = Path("crates/adapters/src/mapper/grok_build.rs")
ARGS_MARKER = "CAS-SUB2API-GROK-TOOLSEARCH-ARGS-HOOK"
SCHEMA_MARKER = "CAS-SUB2API-GROK-REPLAY-SCHEMA-HOOK"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. Grok may emit tool_search.limit in a JSON shape Codex's strongly typed
#    SearchToolCallParams rejects. Repair only the Grok response shim before
#    it is re-packed as ResponseItem::ToolSearchCall.
# ---------------------------------------------------------------------------
text = read(SHIM)
if ARGS_MARKER not in text:
    old = '''fn parse_tool_search_arguments(args_acc: &str) -> Value {
    let v: Value =
        serde_json::from_str(args_acc).unwrap_or_else(|_| json!({ "raw": args_acc.to_owned() }));
    normalize_tool_search_arguments(v)
}
'''
    new = '''// CAS-SUB2API-GROK-TOOLSEARCH-ARGS-HOOK
// Grok's function-call decoder is not constrained by Codex's native tool_search
// grammar. In real traffic it can emit a query with a non-usize `limit` (float,
// numeric string, negative, etc.). Codex deserializes ToolSearchCall.arguments
// into SearchToolCallParams before dispatch and rejects the whole call with
// `failed to parse tool_search arguments: ...`. Keep the repair local to the
// Grok shim: native GPT/Luna Responses traffic remains byte-for-byte passthrough.
fn normalize_grok_tool_search_call_arguments(args: Value) -> Value {
    let mut obj = match args {
        Value::Object(obj) => obj,
        Value::String(query) => return json!({ "query": query }),
        other => {
            tracing::warn!(
                target: "adapters::grok_tool_search",
                raw = %other,
                "Grok tool_search arguments were not an object; coercing to a query string"
            );
            return json!({ "query": other.to_string() });
        }
    };

    let before = Value::Object(obj.clone());

    // Codex SearchToolCallParams requires query: String. Preserve normal strings;
    // for malformed scalar/container values stringify rather than surfacing a
    // deserialization failure. Missing query may come from our JSON-parse fallback
    // (`raw`) or a legacy redirect (`server`).
    let query = match obj.get("query").cloned() {
        Some(Value::String(query)) => query,
        Some(Value::Null) | None => obj
            .get("raw")
            .and_then(Value::as_str)
            .or_else(|| obj.get("server").and_then(Value::as_str))
            .unwrap_or("")
            .to_owned(),
        Some(other) => other.to_string(),
    };
    obj.insert("query".into(), Value::String(query));
    obj.remove("raw");
    obj.remove("server");

    // `limit` is optional in Codex. A malformed value should therefore be
    // dropped so Codex uses its own default rather than failing the tool call.
    if let Some(limit) = obj.get("limit").cloned() {
        let parsed = match limit {
            Value::Number(n) => n.as_u64().or_else(|| {
                n.as_f64().and_then(|f| {
                    (f.is_finite() && f >= 1.0 && f.fract() == 0.0 && f <= u64::MAX as f64)
                        .then_some(f as u64)
                })
            }),
            Value::String(s) => s.trim().parse::<u64>().ok(),
            _ => None,
        }
        .filter(|n| *n > 0)
        .filter(|n| usize::try_from(*n).is_ok());

        match parsed {
            Some(n) => {
                obj.insert("limit".into(), Value::Number(n.into()));
            }
            None => {
                obj.remove("limit");
            }
        }
    }

    let after = Value::Object(obj);
    if after != before {
        tracing::warn!(
            target: "adapters::grok_tool_search",
            before = %before,
            after = %after,
            "normalized Grok tool_search arguments for Codex"
        );
    }
    after
}

fn parse_tool_search_arguments(args_acc: &str) -> Value {
    let parsed: Value = match serde_json::from_str(args_acc) {
        Ok(value) => value,
        Err(error) => {
            tracing::warn!(
                target: "adapters::grok_tool_search",
                raw = %args_acc,
                %error,
                "Grok emitted invalid JSON for tool_search; preserving it as a searchable query"
            );
            json!({ "raw": args_acc.to_owned() })
        }
    };
    normalize_grok_tool_search_call_arguments(normalize_tool_search_arguments(parsed))
}
'''
    text = replace_once(text, old, new, "Grok tool_search argument normalization")

    test_anchor = '''    #[test]
    fn regular_function_call_passes_through_unchanged() {'''
    test = '''    #[test]
    fn tool_search_malformed_numeric_limit_is_repaired_before_codex() {
        let args = normalize_grok_tool_search_call_arguments(json!({
            "query": "ask_user_questions",
            "limit": 2.5
        }));
        assert_eq!(args["query"], "ask_user_questions");
        assert!(args.get("limit").is_none(), "non-integer limit must fall back to Codex default");

        let numeric_string = normalize_grok_tool_search_call_arguments(json!({
            "query": "auq",
            "limit": "8"
        }));
        assert_eq!(numeric_string["limit"], 8);
    }

'''
    text = replace_once(text, test_anchor, test + test_anchor, "Grok tool_search regression test")
else:
    print("[ok] Grok tool_search argument normalization: already applied")
write(SHIM, text)


# ---------------------------------------------------------------------------
# 2. Old Codex conversations can replay tools discovered by tool_search. Some
#    dynamic tools (observed: automation_update) use a root anyOf/oneOf schema
#    containing a non-object branch. Grok/Sub2API requires function parameter
#    roots to be an object, so a resumed thread can 502 even though a fresh
#    thread works. Normalize only the function schemas sent through Grok compat.
# ---------------------------------------------------------------------------
text = read(GROK)
if SCHEMA_MARKER not in text:
    old = '''fn push_grok_adapted_tool(t: &Value, provider: &Provider, out: &mut Vec<Value>) {
    match t.get("type").and_then(Value::as_str).unwrap_or("") {
        // 已是 grok 兼容的 responses-flat function,原样保留。
        "function" => out.push(t.clone()),
        // web_search:grok 认 bare `{type:web_search}`,剥 Codex 的 external_web_access 等子字段。
        "web_search" | "web_search_preview" => out.push(json!({ "type": "web_search" })),
        // namespace(MCP 包):复用 chat 路径转换决策(摊平成 function),再 unwrap 回 flat。
        // custom(apply_patch freeform)/ tool_search:[MOC-301 / MOC-304] 同款请求侧转 function,
        // 响应侧由 grok passthrough 的 tool-call shim 把 grok 回的 `function_call` 重打包回 Codex 的
        // `custom_tool_call` / `tool_search_call`(见 `responses.rs::map_response` + `grok_tool_shim`)。
        // - apply_patch:`{input:string}` schema + chat 友好 V4A 指引(convert 内特判)。
        // - tool_search:透传 name/desc/params,让 grok 看到 deferred MCP/连接器 server 列表。
        "namespace" | "custom" | "tool_search" => {
            for ct in convert_responses_tool_to_chat_tool(t, Some(provider)) {
                out.push(unwrap_chat_tool_to_responses_flat(ct));
            }
        }
        // image_generation / 未知:grok 无等价 → drop(支持度探索见 MOC-305)。
        _ => {}
    }
}
'''
    new = '''// CAS-SUB2API-GROK-REPLAY-SCHEMA-HOOK
// Grok validates the *root* of every function parameter schema as an object.
// Codex deferred/dynamic tools can legitimately expose a root anyOf/oneOf (for
// example automation_update); those tools are often absent on turn 1 and are
// replayed later inside tool_search_output. A fresh Grok thread therefore works
// while an older/resumed one can fail before generation. Flatten only the root
// union for the Grok wire. The local Codex executor remains authoritative for
// validating the selected tool's real arguments.
fn normalize_grok_function_tool_schema(mut tool: Value) -> Value {
    if tool.get("type").and_then(Value::as_str) != Some("function") {
        return tool;
    }
    let name = tool
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let current = tool
        .get("parameters")
        .cloned()
        .unwrap_or_else(|| json!({}));

    let already_plain_object = current.as_object().is_some_and(|root| {
        root.get("type").and_then(Value::as_str) == Some("object")
            && !root.contains_key("anyOf")
            && !root.contains_key("oneOf")
    });
    if already_plain_object {
        return tool;
    }

    let mut flattened = current
        .as_object()
        .cloned()
        .unwrap_or_else(serde_json::Map::new);
    let mut properties = flattened
        .remove("properties")
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_else(serde_json::Map::new);

    // Merge every object-like branch's properties. Non-object branches are
    // intentionally discarded at the Grok wire boundary; additionalProperties
    // stays permissive so $ref-only or unusual branches are not accidentally
    // made impossible.
    for union_key in ["anyOf", "oneOf"] {
        if let Some(Value::Array(branches)) = flattened.remove(union_key) {
            for branch in branches {
                if let Some(branch_obj) = branch.as_object() {
                    if let Some(Value::Object(branch_props)) = branch_obj.get("properties") {
                        for (key, value) in branch_props {
                            properties.entry(key.clone()).or_insert_with(|| value.clone());
                        }
                    }
                    // Preserve definitions referenced by merged properties.
                    for defs_key in ["$defs", "definitions"] {
                        if let Some(Value::Object(branch_defs)) = branch_obj.get(defs_key) {
                            let defs = flattened
                                .entry(defs_key.to_owned())
                                .or_insert_with(|| Value::Object(serde_json::Map::new()));
                            if let Some(defs_obj) = defs.as_object_mut() {
                                for (key, value) in branch_defs {
                                    defs_obj.entry(key.clone()).or_insert_with(|| value.clone());
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    flattened.insert("type".into(), Value::String("object".into()));
    flattened.insert("properties".into(), Value::Object(properties));
    // A union's required sets are branch-specific. Combining them would make
    // mutually exclusive modes impossible, so let Codex's real executor enforce
    // the selected mode after the model calls the tool.
    flattened.insert("required".into(), Value::Array(Vec::new()));
    flattened.insert("additionalProperties".into(), Value::Bool(true));

    if let Some(obj) = tool.as_object_mut() {
        obj.insert("parameters".into(), Value::Object(flattened));
    }
    tracing::warn!(
        target: "adapters::grok_tools",
        tool = %name,
        "normalized non-object/root-union function schema for Grok replay compatibility"
    );
    tool
}

fn push_grok_adapted_tool(t: &Value, provider: &Provider, out: &mut Vec<Value>) {
    match t.get("type").and_then(Value::as_str).unwrap_or("") {
        // 已是 responses-flat function,但 Grok 的 root schema 约束比 Codex 更窄。
        "function" => out.push(normalize_grok_function_tool_schema(t.clone())),
        // web_search:grok 认 bare `{type:web_search}`,剥 Codex 的 external_web_access 等子字段。
        "web_search" | "web_search_preview" => out.push(json!({ "type": "web_search" })),
        // namespace(MCP 包):复用 chat 路径转换决策(摊平成 function),再 unwrap 回 flat。
        // custom(apply_patch freeform)/ tool_search:[MOC-301 / MOC-304] 同款请求侧转 function,
        // 响应侧由 grok passthrough 的 tool-call shim 把 grok 回的 `function_call` 重打包回 Codex 的
        // `custom_tool_call` / `tool_search_call`(见 `responses.rs::map_response` + `grok_tool_shim`)。
        "namespace" | "custom" | "tool_search" => {
            for ct in convert_responses_tool_to_chat_tool(t, Some(provider)) {
                let flat = unwrap_chat_tool_to_responses_flat(ct);
                out.push(normalize_grok_function_tool_schema(flat));
            }
        }
        // image_generation / 未知:grok 无等价 → drop(支持度探索见 MOC-305)。
        _ => {}
    }
}
'''
    text = replace_once(text, old, new, "Grok replayed function schema normalization")

    test_anchor = '''    #[test]
    fn adapts_tools_and_normalizes_reasoning() {'''
    test = '''    #[test]
    fn replayed_root_union_function_schema_is_flattened_for_grok() {
        let body = serde_json::to_vec(&json!({
            "model": "grok-4.5",
            "input": [{
                "type": "tool_search_output",
                "call_id": "search-1",
                "tools": [{
                    "type": "function",
                    "name": "automation_update",
                    "description": "update an automation",
                    "parameters": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "mode": {"type": "string"},
                                    "schedule": {"type": "string"}
                                },
                                "required": ["mode"]
                            },
                            {"type": "null"}
                        ]
                    }
                }]
            }],
            "tools": []
        }))
        .unwrap();

        let out = adapt_grok_build_request_body(&Bytes::from(body), &grok_provider())
            .expect("discovered replay tool should be injected and normalized");
        let v: Value = serde_json::from_slice(&out).unwrap();
        let tool = v["tools"]
            .as_array()
            .and_then(|tools| tools.iter().find(|t| t["name"] == "automation_update"))
            .expect("automation_update should be replayed into top-level tools");
        let parameters = &tool["parameters"];
        assert_eq!(parameters["type"], "object");
        assert!(parameters.get("anyOf").is_none());
        assert!(parameters.get("oneOf").is_none());
        assert_eq!(parameters["required"], json!([]));
        assert!(parameters["properties"].get("mode").is_some());
        assert!(parameters["properties"].get("schedule").is_some());
    }

'''
    text = replace_once(text, test_anchor, test + test_anchor, "Grok replay schema regression test")
else:
    print("[ok] Grok replayed function schema normalization: already applied")
write(GROK, text)
