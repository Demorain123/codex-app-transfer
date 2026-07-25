#!/usr/bin/env python3
"""Apply r17 hardening after the r16 Grok apply_patch recovery layer.

This overlay is intentionally narrow and idempotent. It keeps the proven r16
behavior, then adds:
- fail-closed terminal-envelope matching by output index + item id + call id;
- Add/Update/Delete and body-sentinel regression coverage;
- privacy-safe apply_patch diagnostics (length/error only, no patch previews);
- stronger prompt wording that forbids Markdown-style trailing stars on the
  two V4A envelope sentinels;
- lower-noise logging for successfully repaired sentinel drift.
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


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. Terminal fail-closed identity: response.incomplete/failed must keep the
#    terminal envelope poisoned even if Grok omits or drifts item/call ids.
#    Match by output index first, then item id and call id as stable fallbacks.
# ---------------------------------------------------------------------------
text = read(SHIM)
if SHIM_MARKER not in text:
    old_sets = "        let mut interrupted: std::collections::HashSet<String> = std::collections::HashSet::new();\n"
    new_sets = f'''        // {SHIM_MARKER}
        // A failed/incomplete terminal response is a hard safety boundary for apply_patch.
        // Grok/Sub2API may omit item ids or call ids in the terminal envelope, so tracking only
        // `item_id` can accidentally let the envelope be rewritten back to status=completed.
        // Keep three independent identities; any one match is enough to preserve fail-closed.
        let mut interrupted_indices: std::collections::HashSet<u64> =
            std::collections::HashSet::new();
        let mut interrupted_item_ids: std::collections::HashSet<String> =
            std::collections::HashSet::new();
        let mut interrupted_call_ids: std::collections::HashSet<String> =
            std::collections::HashSet::new();
'''
    text = replace_once(text, old_sets, new_sets, "terminal interrupted set")

    old_insert = '''                if treat_as_interrupted {
                    interrupted.insert(p.item_id.clone());
                }
'''
    new_insert = '''                if treat_as_interrupted {
                    interrupted_indices.insert(output_index);
                    if !p.item_id.is_empty() {
                        interrupted_item_ids.insert(p.item_id.clone());
                    }
                    if !p.call_id.is_empty() {
                        interrupted_call_ids.insert(p.call_id.clone());
                    }
                }
'''
    text = replace_once(text, old_insert, new_insert, "terminal interrupted insert")

    old_loop = '''            for item in output.iter_mut() {
                let id = item.get("id").and_then(|v| v.as_str()).map(str::to_owned);
                self.rewrite_envelope_item(item);
                if let Some(id) = id {
                    if interrupted.contains(&id) {
                        if let Some(o) = item.as_object_mut() {
                            o.insert("status".into(), Value::String("incomplete".into()));
                            // Keep incomplete/failed terminal envelopes fail-closed too.
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
                    }
                }
            }
'''
    new_loop = '''            for (terminal_index, item) in output.iter_mut().enumerate() {
                let id = item.get("id").and_then(|v| v.as_str()).map(str::to_owned);
                let call_id = item
                    .get("call_id")
                    .and_then(|v| v.as_str())
                    .map(str::to_owned);
                self.rewrite_envelope_item(item);
                let item_was_interrupted = u64::try_from(terminal_index)
                    .ok()
                    .is_some_and(|idx| interrupted_indices.contains(&idx))
                    || id
                        .as_ref()
                        .is_some_and(|id| interrupted_item_ids.contains(id))
                    || call_id
                        .as_ref()
                        .is_some_and(|call_id| interrupted_call_ids.contains(call_id));
                if item_was_interrupted {
                    if let Some(o) = item.as_object_mut() {
                        o.insert("status".into(), Value::String("incomplete".into()));
                        // Keep incomplete/failed terminal envelopes fail-closed too.
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
                }
            }
'''
    text = replace_once(text, old_loop, new_loop, "terminal envelope loop")

    # A successful sentinel normalization is expected compatibility work, not a warning.
    text = replace_once(
        text,
        '''        tracing::warn!(
            target: "adapters::grok_tool_diag",
            begin_repaired,
            end_repaired,
            input_len = input.len(),
            "repaired Grok Markdown-style V4A envelope sentinel"
        );
''',
        '''        tracing::info!(
            target: "adapters::grok_tool_diag",
            begin_repaired,
            end_repaired,
            input_len = input.len(),
            "repaired Grok Markdown-style V4A envelope sentinel"
        );
''',
        "sentinel repair log level",
    )

    # Add regression coverage immediately before the existing completed-terminal test.
    anchor = '''    #[test]
    fn completed_terminal_without_output_item_done_recovers_apply_patch() {
'''
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
    text = replace_once(text, anchor, tests + anchor, "completed terminal regression")
    write(SHIM, text)
else:
    print("[ok] Grok apply_patch r17 terminal/test hardening: already applied")


# ---------------------------------------------------------------------------
# 2. Privacy: the generic apply_patch extractor is used by the Grok shim. On
#    malformed input it must not log the first 120 characters of user code.
#    Scope edits to extract_apply_patch_input so unrelated custom-tool logging
#    is not accidentally rewritten if the file gains earlier args_preview uses.
# ---------------------------------------------------------------------------
text = read(CONVERTER)
if PRIVACY_MARKER not in text:
    fn_anchor = "pub(crate) fn extract_apply_patch_input(args_acc: &str) -> String {"
    next_anchor = "pub(crate) fn extract_custom_tool_input(args_acc: &str) -> String {"
    fn_start = text.index(fn_anchor)
    fn_end = text.index(next_anchor, fn_start)
    segment = text[fn_start:fn_end]
    preview = '                    args_preview = %args_acc.chars().take(120).collect::<String>(),\n'
    if segment.count(preview) != 2:
        raise SystemExit(
            f"expected exactly two apply_patch args_preview anchors, found {segment.count(preview)}"
        )
    segment = segment.replace(preview, '                    args_len = args_acc.len(),\n', 1)
    # The parse-error branch already logs args_len, so remove its preview rather than duplicate it.
    segment = segment.replace(preview, '', 1)
    segment = (
        f"// {PRIVACY_MARKER}: malformed apply_patch diagnostics never include patch previews.\n"
        + segment
    )
    text = text[:fn_start] + segment + text[fn_end:]
    write(CONVERTER, text)
else:
    print("[ok] Grok apply_patch r17 privacy hardening: already applied")


# ---------------------------------------------------------------------------
# 3. Prompt prevention: r16 repairs Grok's observed `*** Begin Patch ***`
#    drift, but preventing the drift is cheaper and avoids repair churn.
#    Keep the internal marker in a Rust comment, never in model-visible text.
# ---------------------------------------------------------------------------
text = read(TOOLS)
if PROMPT_MARKER not in text:
    const_anchor = "pub(crate) const APPLY_PATCH_TOOL_DESCRIPTION_FOR_CHAT: &str = concat!("
    text = replace_once(
        text,
        const_anchor,
        f"// {PROMPT_MARKER}: explicitly forbid Markdown-style trailing stars on V4A sentinels.\n"
        + const_anchor,
        "apply_patch prompt marker",
    )

    tool_anchor = '    "**The patch MUST start with `*** Begin Patch` as the literal first line** (no leading whitespace, no other content before it), and end with `*** End Patch`. ",\n'
    tool_replacement = tool_anchor + (
        '    "**Do NOT append trailing stars to either envelope sentinel** — '
        '`*** Begin Patch ***` and `*** End Patch ***` are invalid Markdown-styled variants; use exactly '
        '`*** Begin Patch` and `*** End Patch`. ",\n'
    )
    text = replace_once(text, tool_anchor, tool_replacement, "apply_patch tool sentinel prompt")

    input_anchor = '    "A V4A patch starting with `*** Begin Patch` and ending with `*** End Patch`. ",\n'
    input_replacement = input_anchor + (
        '    "Use those two envelope sentinels EXACTLY as written — no trailing ` ***` (so never '
        '`*** Begin Patch ***` / `*** End Patch ***`). ",\n'
    )
    text = replace_once(text, input_anchor, input_replacement, "apply_patch input sentinel prompt")
    write(TOOLS, text)
else:
    print("[ok] Grok apply_patch r17 prompt hardening: already applied")

print("[ok] Grok apply_patch r17 hardening overlay applied")
