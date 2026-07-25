#!/usr/bin/env python3
"""Second r17 self-review pass for Grok apply_patch compatibility.

This pass intentionally stays separate from the main r17 hardening overlay so
it can be audited/reverted independently. It fixes two transport-shape safety
edges around the JSON/V4A boundary:

1. `detect_json_truncation` must only inspect the ORIGINAL JSON-wrapped function
   arguments. Bare V4A is a supported recovery shape and may legitimately
   contain unmatched source-code braces/quotes with no JSON structural meaning.
2. V4A envelope auto-completion (`*** Begin/End Patch`) is allowed only when the
   ORIGINAL argument had a structurally complete JSON wrapper. A raw bare-V4A
   stream that ends at EOF without `*** End Patch` cannot prove it was not
   transport-truncated, so it must remain fail-closed rather than being repaired
   into an executable patch.

It also contains a migration guard for the earliest r17 prompt-marker draft,
where the internal marker could have landed inside model-visible text.
"""
from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
TOOLS = Path("crates/adapters/src/responses/request/tools.rs")

BARE_V4A_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-R17-BARE-V4A-NOT-JSON"
WRAPPER_PROOF_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-R17-ENVELOPE-REQUIRES-JSON-PROOF"
PROMPT_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-HARDENING-R17-PROMPT"
PROMPT_COMMENT = (
    f"// {PROMPT_MARKER}: explicitly forbid Markdown-style trailing stars on V4A sentinels.\n"
)


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
# 1. JSON proof belongs to the ORIGINAL wire argument, before bounded unwrapping.
#    This both avoids false-positive JSON scans on bare V4A and prevents raw EOF
#    from gaining an EndPatch sentinel merely because optimize_patch can repair it.
# ---------------------------------------------------------------------------
text = read(SHIM)
if WRAPPER_PROOF_MARKER not in text:
    base_gate = "    let json_trunc = detect_json_truncation(&normalized_args);\n"
    prior_gate = f'''    // {BARE_V4A_MARKER}
    // Standard lowered function arguments are a JSON object. Recovery also accepts bare V4A
    // (or a JSON string that normalizes to bare V4A). Source code inside bare V4A can contain
    // unmatched braces/quotes, so running the JSON structural scanner on it creates false
    // truncation positives. Only JSON-looking wrappers get JSON truncation analysis.
    let normalized_trimmed = normalized_args.trim_start();
    let args_look_json_wrapped =
        normalized_trimmed.starts_with('{{') || normalized_trimmed.starts_with('"');
    let json_trunc = if args_look_json_wrapped {{
        detect_json_truncation(&normalized_args)
    }} else {{
        None
    }};
'''
    new_gate = f'''    // {BARE_V4A_MARKER}
    // {WRAPPER_PROOF_MARKER}
    // Decide JSON completeness from the ORIGINAL wire argument, before double-encoded JSON is
    // unwrapped. Bare V4A may contain arbitrary source braces/quotes and must never be scanned as
    // JSON. Conversely, only a structurally complete original JSON wrapper proves that a missing
    // V4A Begin/End sentinel is model/schema drift rather than a raw transport EOF truncation.
    let original_trimmed = args_acc.trim_start();
    let args_look_json_wrapped =
        original_trimmed.starts_with('{{') || original_trimmed.starts_with('"');
    let json_trunc = if args_look_json_wrapped {{
        detect_json_truncation(args_acc)
    }} else {{
        None
    }};
    let json_complete_for_envelope = args_look_json_wrapped && json_trunc.is_none();
'''
    if prior_gate in text:
        text = text.replace(prior_gate, new_gate, 1)
    elif base_gate in text:
        text = text.replace(base_gate, new_gate, 1)
    else:
        raise SystemExit("anchor not found: apply_patch JSON truncation gate")

    old_optimize = '''    let (input, _repairs) =
        apply_patch_preflight::optimize_patch(&input, cwd, json_trunc.is_none());
'''
    new_optimize = '''    let (input, _repairs) =
        apply_patch_preflight::optimize_patch(&input, cwd, json_complete_for_envelope);
'''
    text = replace_once(text, old_optimize, new_optimize, "apply_patch envelope proof gate")

    test_anchor = '''    #[test]
    fn completed_terminal_without_output_item_done_recovers_apply_patch() {
'''
    tests = r'''    #[test]
    fn bare_v4a_with_unbalanced_source_brace_is_not_misclassified_as_json_truncation() {
        let patch = "*** Begin Patch\n*** Add File: brace.rs\n+fn main() {\n*** End Patch\n";
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_bare_brace","call_id":"call_bare_brace","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_bare_brace","call_id":"call_bare_brace","name":"apply_patch","arguments":patch}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(done["input"], patch);
        assert!(!done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
    }

    #[test]
    fn bare_v4a_missing_end_at_raw_eof_stays_fail_closed() {
        // No JSON wrapper means raw EOF itself cannot prove transport completeness. Even though
        // the generic preflight knows how to append a missing EndPatch for complete JSON calls,
        // this bare-V4A shape must NOT be promoted into an executable patch.
        let patch = "*** Begin Patch\n*** Add File: raw-eof.txt\n+must-not-run\n";
        let input = frame(
            "response.output_item.added",
            json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                "item":{"type":"function_call","id":"fc_raw_eof","call_id":"call_raw_eof","name":"apply_patch","arguments":patch}}),
        );
        let frames = run(&input);
        let done = &frames[1].1["item"];
        assert_eq!(done["status"], "incomplete");
        assert!(done["input"]
            .as_str()
            .unwrap()
            .starts_with(INCOMPLETE_APPLY_PATCH_PREFIX));
    }

    #[test]
    fn complete_json_wrapper_can_still_repair_missing_v4a_end() {
        // A closed JSON object is a transport-completeness proof for its string value, so the
        // established non-destructive envelope preflight may still repair a model-omitted EndPatch.
        let patch_without_end = "*** Begin Patch\n*** Add File: json-complete.txt\n+ok\n";
        let args = serde_json::to_string(&json!({ "input": patch_without_end })).unwrap();
        let input = [
            frame(
                "response.output_item.added",
                json!({"type":"response.output_item.added","sequence_number":0,"output_index":0,
                    "item":{"type":"function_call","id":"fc_json_complete","call_id":"call_json_complete","name":"apply_patch","arguments":""}}),
            ),
            frame(
                "response.output_item.done",
                json!({"type":"response.output_item.done","sequence_number":1,"output_index":0,
                    "item":{"type":"function_call","id":"fc_json_complete","call_id":"call_json_complete","name":"apply_patch","arguments":args}}),
            ),
        ]
        .concat();
        let frames = run(&input);
        let done = &frames[3].1["item"];
        assert_eq!(done["status"], "completed");
        assert_eq!(
            done["input"],
            "*** Begin Patch\n*** Add File: json-complete.txt\n+ok\n*** End Patch"
        );
    }

'''
    # Avoid duplicating the first test if an earlier generated run already applied v1 of this overlay.
    if "fn bare_v4a_with_unbalanced_source_brace_is_not_misclassified_as_json_truncation()" in text:
        first_start = text.index(
            "    #[test]\n    fn bare_v4a_with_unbalanced_source_brace_is_not_misclassified_as_json_truncation()"
        )
        first_end = text.index(test_anchor, first_start)
        text = text[:first_start] + tests + text[first_end:]
    else:
        text = replace_once(text, test_anchor, tests + test_anchor, "bare V4A regression anchor")
    write(SHIM, text)
else:
    print("[ok] r17 original-wrapper / bare-V4A safety hardening: already applied")


# ---------------------------------------------------------------------------
# 2. Migration guard for the earliest r17 draft only. The internal overlay
#    marker belongs in a Rust comment, never in model-visible tool text.
# ---------------------------------------------------------------------------
text = read(TOOLS)
legacy_prefix = f'    "{PROMPT_MARKER}: **Do NOT append trailing stars to either envelope sentinel** — '
if legacy_prefix in text:
    legacy_full = (
        legacy_prefix
        + '`*** Begin Patch ***` and `*** End Patch ***` are invalid Markdown-styled variants; use exactly '
        + '`*** Begin Patch` and `*** End Patch`. ",\n'
    )
    clean = (
        '    "**Do NOT append trailing stars to either envelope sentinel** — '
        '`*** Begin Patch ***` and `*** End Patch ***` are invalid Markdown-styled variants; use exactly '
        '`*** Begin Patch` and `*** End Patch`. ",\n'
    )
    text = replace_once(text, legacy_full, clean, "legacy model-visible r17 prompt marker")
    const_anchor = "pub(crate) const APPLY_PATCH_TOOL_DESCRIPTION_FOR_CHAT: &str = concat!("
    if PROMPT_COMMENT not in text:
        text = replace_once(text, const_anchor, PROMPT_COMMENT + const_anchor, "prompt marker comment")
    write(TOOLS, text)
else:
    print("[ok] r17 prompt marker is not model-visible")

print("[ok] Grok apply_patch r17 second self-review overlay applied")
