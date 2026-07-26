#!/usr/bin/env python3
"""Reconstruct the r14 Grok apply_patch safety/argument layer on pristine upstream.

r14 was originally merged as generated source before the compat branch adopted a
thin overlay for every subsequent r15/r16/r17 change. That left a rebase gap:
newer overlays assume these r14 primitives already exist, so a pristine v2.4.5
checkout cannot replay the complete stack from scripts alone.

This bootstrap is intentionally behavior-equivalent to PR #2's r14 source diff:
- accept string or object-valued function_call.arguments;
- prefer authoritative output_item.done arguments;
- unwrap bounded double-encoded apply_patch arguments;
- poison incomplete apply_patch input because Codex 0.144 dispatches custom tools
  even when status=incomplete;
- keep terminal/non-stream envelopes fail-closed;
- add the r14 regression tests required by later overlays.

It is idempotent and safe on the current compat branch: if all r14 primitives are
already present, it only inserts an inert marker comment once.
"""
from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-R14-BOOTSTRAP"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    return text.replace(old, new, 1)


text = read(SHIM)
if MARKER in text:
    print("[ok] Grok apply_patch r14 bootstrap: already applied")
    raise SystemExit(0)

# Current compat source already contains r14. In that case do not re-run source
# replacements; add a marker beside the helper so pristine-overlay validation can
# prove the historical dependency is now represented by a replayable layer.
r14_features = (
    "fn function_arguments_to_string(value: Option<&Value>) -> String",
    "fn normalize_apply_patch_arguments(args_acc: &str) -> String",
    'const INCOMPLETE_APPLY_PATCH_PREFIX: &str = "*** BLOCKED INCOMPLETE APPLY_PATCH ***";',
    "fn block_incomplete_apply_patch(input: &str) -> String",
    "fn apply_patch_prefers_output_item_done_arguments_when_args_done_is_missing()",
)
if all(feature in text for feature in r14_features):
    helper = "fn function_arguments_to_string(value: Option<&Value>) -> String {"
    text = replace_once(
        text,
        helper,
        f"// {MARKER}: historical r14 layer is now replayable from pristine upstream.\n{helper}",
        "existing r14 helper marker",
    )
    write(SHIM, text)
    print("[ok] Grok apply_patch r14 bootstrap: existing generated source marked")
    raise SystemExit(0)

# 1. Accept direct JSON object-valued arguments on item.added.
old = '''        let args0 = item
            .get("arguments")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_owned();
'''
text = replace_once(
    text,
    old,
    '        let args0 = function_arguments_to_string(item.get("arguments"));\n',
    "item.added arguments",
)

# 2. arguments.done can also be object-valued and is authoritative.
old = '''                if let Some(args) = data.get("arguments").and_then(|v| v.as_str()) {
                    if !args.is_empty() {
                        p.args_acc = args.to_owned();
                    }
                }
'''
new = '''                let args = function_arguments_to_string(data.get("arguments"));
                if !args.is_empty() {
                    p.args_acc = args;
                }
'''
text = replace_once(text, old, new, "arguments.done authoritative value")

# 3. output_item.done.item.arguments is the last authoritative fallback.
old = '''        if let Some(p) = self.items.remove(&output_index) {
            self.id_to_index.remove(&p.item_id);
            self.emit_tool_call_done(output_index, &p, false, out);
'''
new = '''        if let Some(mut p) = self.items.remove(&output_index) {
            self.id_to_index.remove(&p.item_id);
            // r14: some Grok/Sub2API Responses streams omit arguments.done or emit a
            // partial delta but include the authoritative complete arguments on
            // output_item.done.item. Prefer that terminal value when present.
            let final_args = data
                .get("item")
                .and_then(|item| item.get("arguments"))
                .or_else(|| data.get("arguments"))
                .map(|args| function_arguments_to_string(Some(args)))
                .unwrap_or_default();
            if !final_args.is_empty() {
                p.args_acc = final_args;
            }
            self.emit_tool_call_done(output_index, &p, false, out);
'''
text = replace_once(text, old, new, "output_item.done authoritative arguments")

# 4. status=incomplete is not a Codex execution boundary; poison apply_patch.
old = '''                if incomplete {
                    let item = json!({
                        "type": "custom_tool_call", "id": p.item_id, "call_id": p.call_id,
                        "name": p.name, "input": input, "status": "incomplete",
                    });
'''
new = '''                if incomplete {
                    // Codex 0.144's ToolRouter ignores CustomToolCall.status and will still
                    // dispatch status=incomplete. apply_patch is destructive, so status is
                    // not a safety boundary: poison the first line to guarantee parse_patch
                    // rejects before touching the filesystem. Preserve the original patch
                    // below the marker for diagnostics/model retry context.
                    let input = if apply_patch {
                        block_incomplete_apply_patch(&input)
                    } else {
                        input
                    };
                    let item = json!({
                        "type": "custom_tool_call", "id": p.item_id, "call_id": p.call_id,
                        "name": p.name, "input": input, "status": "incomplete",
                    });
'''
text = replace_once(text, old, new, "streamed incomplete poison")

# 5. Keep incomplete/failed terminal envelope fail-closed as well.
old = '''                        if let Some(o) = item.as_object_mut() {
                            o.insert("status".into(), Value::String("incomplete".into()));
                        }
'''
new = '''                        if let Some(o) = item.as_object_mut() {
                            o.insert("status".into(), Value::String("incomplete".into()));
                            // Keep the terminal envelope fail-closed too. Codex currently
                            // executes output_item.done, but JSON/non-stream consumers may
                            // use the envelope directly and must not rely on status either.
                            if o.get("type").and_then(Value::as_str) == Some("custom_tool_call")
                                && o.get("name").and_then(Value::as_str) == Some("apply_patch")
                            {
                                if let Some(input) =
                                    o.get("input").and_then(Value::as_str).map(str::to_owned)
                                {
                                    o.insert(
                                        "input".into(),
                                        Value::String(block_incomplete_apply_patch(&input)),
                                    );
                                }
                            }
                        }
'''
text = replace_once(text, old, new, "terminal incomplete poison")

# 6. Non-stream/envelope arguments also accept object shape; invalid apply_patch
#    must be poisoned there too.
old = '''        let args = item
            .get("arguments")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_owned();
        if let Some(&apply_patch) = self.custom_lowered.get(&name) {
            let (input, incomplete) = if apply_patch {
                finalize_apply_patch(&args, self.cwd.as_deref(), false)
            } else {
                (generic_custom_input(&args), false)
            };
            *item = json!({
'''
new = '''        let args = function_arguments_to_string(item.get("arguments"));
        if let Some(&apply_patch) = self.custom_lowered.get(&name) {
            let (input, incomplete) = if apply_patch {
                finalize_apply_patch(&args, self.cwd.as_deref(), false)
            } else {
                (generic_custom_input(&args), false)
            };
            let input = if apply_patch && incomplete {
                block_incomplete_apply_patch(&input)
            } else {
                input
            };
            *item = json!({
'''
text = replace_once(text, old, new, "envelope argument normalization")

# 7. Insert r14 helpers and bounded double-encoding recovery before finalize.
anchor = '''/// apply_patch args(`{"input":"<V4A>"}`)→ 最终 V4A input + 是否 incomplete(截断 / 语法错 /
/// interrupted)。复用 converter 的提取 + preflight + 校验(与 chat 路径同一套逻辑,DRY)。
'''
helpers = f'''// {MARKER}: replayable bootstrap for the historical r14 layer.
/// Responses-compatible function_call.arguments is normally a JSON string, but Grok/Sub2API
/// traffic in the wild can put the JSON object directly on `arguments`. Normalize both shapes
/// into the string form consumed by the existing parser. Null/missing remains empty.
fn function_arguments_to_string(value: Option<&Value>) -> String {{
    match value {{
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => serde_json::to_string(other).unwrap_or_else(|_| other.to_string()),
    }}
}}

/// Grok gateways occasionally double-encode function arguments. Unwrap at most two string layers;
/// bounded depth covers observed drift without turning arbitrary patch content into recursion.
fn normalize_apply_patch_arguments(args_acc: &str) -> String {{
    let mut current = args_acc.trim().to_owned();
    for _ in 0..2 {{
        let Ok(Value::String(inner)) = serde_json::from_str::<Value>(&current) else {{
            break;
        }};
        let trimmed = inner.trim_start();
        if !trimmed.starts_with('{{') && !inner.contains("*** Begin Patch") {{
            break;
        }}
        current = inner;
    }}
    current
}}

const INCOMPLETE_APPLY_PATCH_PREFIX: &str = "*** BLOCKED INCOMPLETE APPLY_PATCH ***";

/// Codex 0.144 dispatches CustomToolCall even when status=incomplete. Make an incomplete
/// apply_patch syntactically non-executable while preserving the attempted body underneath.
fn block_incomplete_apply_patch(input: &str) -> String {{
    if input.starts_with(INCOMPLETE_APPLY_PATCH_PREFIX) {{
        return input.to_owned();
    }}
    if input.is_empty() {{
        return INCOMPLETE_APPLY_PATCH_PREFIX.to_owned();
    }}
    format!("{{INCOMPLETE_APPLY_PATCH_PREFIX}}\\n{{input}}")
}}

'''
text = replace_once(text, anchor, helpers + anchor, "r14 helper insertion")

# 8. finalize applies bounded argument normalization before extraction/truncation.
old = '''fn finalize_apply_patch(args_acc: &str, cwd: Option<&str>, interrupted: bool) -> (String, bool) {
    let input = extract_apply_patch_input(args_acc);
    let json_trunc = detect_json_truncation(args_acc);
'''
new = '''fn finalize_apply_patch(args_acc: &str, cwd: Option<&str>, interrupted: bool) -> (String, bool) {
    let normalized_args = normalize_apply_patch_arguments(args_acc);
    let input = extract_apply_patch_input(&normalized_args);
    let json_trunc = detect_json_truncation(&normalized_args);
'''
text = replace_once(text, old, new, "finalize normalized arguments")

# 9. Later r16 overlay intentionally replaces the interrupted test; keep the
#    original r14 name/shape as its anchor and preserve the other recovery tests.
test_anchor = '''    #[test]
    fn tool_search_function_call_rewritten_to_tool_search_call() {'''
if test_anchor not in text:
    raise SystemExit("anchor not found: r14 regression insertion")
tests = r'''    #[test]
    fn apply_patch_prefers_output_item_done_arguments_when_args_done_is_missing() {
        let patch = "*** Begin Patch\n*** Add File: terminal.txt\n+terminal\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_terminal","call_id":"call_terminal","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_terminal","call_id":"call_terminal","name":"apply_patch","arguments":args}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
    }

    #[test]
    fn apply_patch_accepts_object_arguments_from_output_item_done() {
        let patch = "*** Begin Patch\n*** Add File: object.txt\n+object\n*** End Patch\n";
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_object","call_id":"call_object","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_object","call_id":"call_object","name":"apply_patch",
                        "arguments":{"input":patch}}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
    }

    #[test]
    fn apply_patch_unwraps_double_encoded_arguments() {
        let patch = "*** Begin Patch\n*** Add File: double.txt\n+double\n*** End Patch\n";
        let once = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let twice = serde_json::to_string(&once).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_double","call_id":"call_double","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_double","call_id":"call_double","name":"apply_patch","arguments":twice}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
    }

    #[test]
    fn interrupted_apply_patch_is_poisoned_because_codex_ignores_incomplete_status() {
        let patch = "*** Begin Patch\n*** Add File: must-not-run.txt\n+blocked\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = frame(
            "response.output_item.added",
            json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                "item":{"type":"function_call","id":"fc_interrupt","call_id":"call_interrupt","name":"apply_patch","arguments":args}}),
        );
        let frames = run(&input);
        let done = &frames[1].1["item"];
        assert_eq!(done["status"], "incomplete");
        let blocked = done["input"].as_str().unwrap();
        assert!(blocked.starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
        assert!(blocked.contains("*** Begin Patch"));
        assert!(validate_v4a_syntax(blocked).is_err());
    }

'''
text = text.replace(test_anchor, tests + test_anchor, 1)

write(SHIM, text)
print("[ok] Grok apply_patch r14 bootstrap: applied")
