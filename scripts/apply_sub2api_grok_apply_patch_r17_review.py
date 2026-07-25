#!/usr/bin/env python3
"""Second r17 self-review pass for Grok apply_patch compatibility.

This pass intentionally stays separate from the main r17 hardening overlay so
it can be audited/reverted independently. It fixes one subtle false-positive:
`detect_json_truncation` must only inspect JSON-wrapped function arguments.
Bare V4A is a supported recovery shape and may legitimately contain unmatched
source-code braces/quotes that have no JSON structural meaning.

It also contains a migration guard for the earliest r17 prompt-marker draft,
where the internal marker could have landed inside model-visible text.
"""
from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
TOOLS = Path("crates/adapters/src/responses/request/tools.rs")

BARE_V4A_MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-R17-BARE-V4A-NOT-JSON"
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
# 1. Bare V4A must not be scanned as JSON. Example: a perfectly valid Add File
#    patch containing `+fn main() {` has an unmatched `{` in source text; r16's
#    JSON scanner would otherwise classify that bare V4A as transport-truncated.
# ---------------------------------------------------------------------------
text = read(SHIM)
if BARE_V4A_MARKER not in text:
    old = "    let json_trunc = detect_json_truncation(&normalized_args);\n"
    new = f'''    // {BARE_V4A_MARKER}
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
    text = replace_once(text, old, new, "apply_patch JSON truncation gate")

    test_anchor = '''    #[test]
    fn completed_terminal_without_output_item_done_recovers_apply_patch() {
'''
    test = r'''    #[test]
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

'''
    text = replace_once(text, test_anchor, test + test_anchor, "bare V4A regression anchor")
    write(SHIM, text)
else:
    print("[ok] r17 bare-V4A JSON-truncation hardening: already applied")


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
