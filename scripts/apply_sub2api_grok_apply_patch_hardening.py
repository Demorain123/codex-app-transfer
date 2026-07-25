#!/usr/bin/env python3
"""Apply r17 hardening after the r16 Grok apply_patch recovery layer.

This overlay is intentionally narrow and idempotent. It keeps the proven r16
behavior, then adds:
- fail-closed terminal-envelope matching by output index + item id + call id;
- Add/Update/Delete and body-sentinel regression coverage;
- privacy-safe apply_patch diagnostics (length/error only, no patch previews);
- stronger prompt wording that forbids Markdown-style trailing stars on the
  two V4A envelope sentinels.
"""
from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
CONVERTER = Path("crates/adapters/src/responses/converter.rs")
TOOLS = Path("crates/adapters/src/responses/request/tools.rs")

SHIM_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-HARDENING-R17-TERMINAL-ID"
PRIVACY_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-HARDENING-R17-PRIVACY"
PROMPT_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-HARDENING-R17-PROMPT"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


# ---------------------------------------------------------------------------
# 1. Terminal fail-closed identity: response.incomplete/failed must keep the
#    terminal envelope poisoned even if Grok omits or drifts item/call ids.
#    Match by output index first, then item id and call id as stable fallbacks.
# ---------------------------------------------------------------------------
text = read(SHIM)
if SHIM_MARKER not in text:
    old_sets = '''        let mut interrupted: std::collections::HashSet<String> = std::collections::HashSet::new();\n'''
    new_sets = f'''        // {SHIM_MARKER}\n        // A failed/incomplete terminal response is a hard safety boundary for apply_patch.\n        // Grok/Sub2API may omit item ids or call ids in the terminal envelope, so tracking only\n        // `item_id` can accidentally let the envelope be rewritten back to status=completed.\n        // Keep three independent identities; any one match is enough to preserve fail-closed.\n        let mut interrupted_indices: std::collections::HashSet<u64> =\n            std::collections::HashSet::new();\n        let mut interrupted_item_ids: std::collections::HashSet<String> =\n            std::collections::HashSet::new();\n        let mut interrupted_call_ids: std::collections::HashSet<String> =\n            std::collections::HashSet::new();\n'''
    if old_sets not in text:
        raise SystemExit("anchor not found: terminal interrupted set")
    text = text.replace(old_sets, new_sets, 1)

    old_insert = '''                if treat_as_interrupted {\n                    interrupted.insert(p.item_id.clone());\n                }\n'''
    new_insert = '''                if treat_as_interrupted {\n                    interrupted_indices.insert(output_index);\n                    if !p.item_id.is_empty() {\n                        interrupted_item_ids.insert(p.item_id.clone());\n                    }\n                    if !p.call_id.is_empty() {\n                        interrupted_call_ids.insert(p.call_id.clone());\n                    }\n                }\n'''
    if old_insert not in text:
        raise SystemExit("anchor not found: terminal interrupted insert")
    text = text.replace(old_insert, new_insert, 1)

    old_loop = '''            for item in output.iter_mut() {\n                let id = item.get("id").and_then(|v| v.as_str()).map(str::to_owned);\n                self.rewrite_envelope_item(item);\n                if let Some(id) = id {\n                    if interrupted.contains(&id) {\n                        if let Some(o) = item.as_object_mut() {\n                            o.insert("status".into(), Value::String("incomplete".into()));\n                            // Keep incomplete/failed terminal envelopes fail-closed too.\n                            if o.get("type").and_then(Value::as_str) == Some("custom_tool_call")\n                                && o.get("name").and_then(Value::as_str) == Some("apply_patch")\n                            {\n                                if let Some(input) =\n                                    o.get("input").and_then(Value::as_str).map(str::to_owned)\n                                {\n                                    o.insert(\n                                        "input".into(),\n                                        Value::String(block_incomplete_apply_patch(&input)),\n                                    );\n                                }\n                            }\n                        }\n                    }\n                }\n            }\n'''
    new_loop = '''            for (terminal_index, item) in output.iter_mut().enumerate() {\n                let id = item.get("id").and_then(|v| v.as_str()).map(str::to_owned);\n                let call_id = item\n                    .get("call_id")\n                    .and_then(|v| v.as_str())\n                    .map(str::to_owned);\n                self.rewrite_envelope_item(item);\n                let item_was_interrupted = u64::try_from(terminal_index)\n                    .ok()\n                    .is_some_and(|idx| interrupted_indices.contains(&idx))\n                    || id\n                        .as_ref()\n                        .is_some_and(|id| interrupted_item_ids.contains(id))\n                    || call_id\n                        .as_ref()\n                        .is_some_and(|call_id| interrupted_call_ids.contains(call_id));\n                if item_was_interrupted {\n                    if let Some(o) = item.as_object_mut() {\n                        o.insert("status".into(), Value::String("incomplete".into()));\n                        // Keep incomplete/failed terminal envelopes fail-closed too.\n                        if o.get("type").and_then(Value::as_str) == Some("custom_tool_call")\n                            && o.get("name").and_then(Value::as_str) == Some("apply_patch")\n                        {\n                            if let Some(input) =\n                                o.get("input").and_then(Value::as_str).map(str::to_owned)\n                            {\n                                o.insert(\n                                    "input".into(),\n                                    Value::String(block_incomplete_apply_patch(&input)),\n                                );\n                            }\n                        }\n                    }\n                }\n            }\n'''
    if old_loop not in text:
        raise SystemExit("anchor not found: terminal envelope loop")
    text = text.replace(old_loop, new_loop, 1)

    # Add regression coverage immediately before the existing completed-terminal test.
    anchor = '''    #[test]\n    fn completed_terminal_without_output_item_done_recovers_apply_patch() {\n'''
    if anchor not in text:
        raise SystemExit("anchor not found: completed terminal regression")
    tests = r'''    #[test]
    fn grok_markdown_style_v4a_sentinels_are_repaired_for_update_and_delete() {
        let cases = [
            (
                "*** Begin Patch ***\n*** Update File: probe.txt\n-old\n+new\n*** End Patch ***\n",
                "*** Begin Patch\n*** Update File: probe.txt\n-old\n+new\n*** End Patch\n",
            ),
            (
                "*** Begin Patch ***\n*** Delete File: probe.txt\n*** End Patch ***\n",
                "*** Begin Patch\n*** Delete File: probe.txt\n*** End Patch\n",
            ),
        ];

        for (case_idx, (malformed, canonical)) in cases.into_iter().enumerate() {
            let args = serde_json::to_string(&json!({ "input": malformed })).unwrap();
            let input = [
                frame(
                    "response.output_item.added",
                    json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                        "item":{"type":"function_call","id":format!("fc_case_{case_idx}"),"call_id":format!("call_case_{case_idx}"),"name":"apply_patch","arguments":""}}),
                ),
                frame(
                    "response.output_item.done",
                    json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                        "item":{"type":"function_call","id":format!("fc_case_{case_idx}"),"call_id":format!("call_case_{case_idx}"),"name":"apply_patch","arguments":args}}),
                ),
            ]
            .concat();
            let frames = run(&input);
            let done = &frames[3].1["item"];
            assert_eq!(done["status"], "completed");
            assert_eq!(done["input"], canonical);
            assert!(validate_v4a_syntax(done["input"].as_str().unwrap()).is_ok());
        }
    }

    #[test]
    fn grok_sentinel_repair_never_touches_prefixed_body_lines() {
        let malformed = "*** Begin Patch ***\n*** Add File: sentinel-body.txt\n+*** End Patch ***\n*** End Patch ***\n";
        let canonical = "*** Begin Patch\n*** Add File: sentinel-body.txt\n+*** End Patch ***\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": malformed })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_body_sentinel","call_id":"call_body_sentinel","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_body_sentinel","call_id":"call_body_sentinel","name":"apply_patch","arguments":args}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], canonical);
        assert!(done["input"].as_str().unwrap().contains("+*** End Patch ***"));
    }

    #[test]
    fn incomplete_terminal_without_item_or_call_id_stays_fail_closed() {
        let patch = "*** Begin Patch\n*** Delete File: must-not-run.txt\n*** End Patch\n";
        let args = serde_json::to_string(&json!({ "input": patch })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.incomplete",
                json!({"type":"response.incomplete","sequence_number":1,
                    "response":{"output":[{"type":"function_call","name":"apply_patch","arguments":args}]}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let streamed_done = &frames[1].1["item"];
        assert_eq!(streamed_done["status"], "incomplete");
        assert!(streamed_done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
        let terminal_item = &frames[2].1["response"]["output"][0];
        assert_eq!(terminal_item["status"], "incomplete");
        assert!(terminal_item["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
    }

'''
    text = text.replace(anchor, tests + anchor, 1)
    write(SHIM, text)
else:
    print("[ok] Grok apply_patch r17 terminal/test hardening: already applied")


# ---------------------------------------------------------------------------
# 2. Privacy: the generic apply_patch extractor is used by the Grok shim. On
#    malformed input it must not log the first 120 characters of user code.
# ---------------------------------------------------------------------------
text = read(CONVERTER)
if PRIVACY_MARKER not in text:
    fn_anchor = "pub(crate) fn extract_apply_patch_input(args_acc: &str) -> String {"
    if fn_anchor not in text:
        raise SystemExit("anchor not found: extract_apply_patch_input")
    text = text.replace(
        fn_anchor,
        f"// {PRIVACY_MARKER}: malformed apply_patch diagnostics never include patch previews.\n{fn_anchor}",
        1,
    )
    preview = '                    args_preview = %args_acc.chars().take(120).collect::<String>(),\n'
    count = text.count(preview)
    if count < 2:
        raise SystemExit(f"expected at least two apply_patch args_preview anchors, found {count}")
    # Only the first two occurrences are inside extract_apply_patch_input; later custom-tool
    # diagnostics intentionally remain untouched by this narrowly-scoped overlay.
    text = text.replace(preview, '                    args_len = args_acc.len(),\n', 1)
    # The parse-error branch already logs args_len, so remove (rather than duplicate) its preview.
    text = text.replace(preview, '', 1)
    write(CONVERTER, text)
else:
    print("[ok] Grok apply_patch r17 privacy hardening: already applied")


# ---------------------------------------------------------------------------
# 3. Prompt prevention: r16 repairs Grok's observed `*** Begin Patch ***`
#    drift, but preventing the drift is cheaper and avoids noisy repair logs.
# ---------------------------------------------------------------------------
text = read(TOOLS)
if PROMPT_MARKER not in text:
    tool_anchor = '    "**The patch MUST start with `*** Begin Patch` as the literal first line** (no leading whitespace, no other content before it), and end with `*** End Patch`. ",\n'
    tool_replacement = tool_anchor + (
        f'    "{PROMPT_MARKER}: **Do NOT append trailing stars to either envelope sentinel** — '
        '`*** Begin Patch ***` and `*** End Patch ***` are invalid Markdown-styled variants; use exactly '
        '`*** Begin Patch` and `*** End Patch`. ",\n'
    )
    if tool_anchor not in text:
        raise SystemExit("anchor not found: apply_patch tool sentinel prompt")
    text = text.replace(tool_anchor, tool_replacement, 1)

    input_anchor = '    "A V4A patch starting with `*** Begin Patch` and ending with `*** End Patch`. ",\n'
    input_replacement = input_anchor + (
        '    "Use those two envelope sentinels EXACTLY as written — no trailing ` ***` (so never '
        '`*** Begin Patch ***` / `*** End Patch ***`). ",\n'
    )
    if input_anchor not in text:
        raise SystemExit("anchor not found: apply_patch input sentinel prompt")
    text = text.replace(input_anchor, input_replacement, 1)
    write(TOOLS, text)
else:
    print("[ok] Grok apply_patch r17 prompt hardening: already applied")

print("[ok] Grok apply_patch r17 hardening overlay applied")
