#!/usr/bin/env python3
"""Third r17 self-review: preserve raw bare-V4A byte shape while unwrapping JSON.

The first bare-V4A regression exposed that `normalize_apply_patch_arguments`
started from `args_acc.trim()`. That did not affect syntax, but it silently
removed a valid trailing newline from raw V4A and contradicted the intended
raw-passthrough recovery behavior. Parse JSON from a trimmed *view* instead,
while keeping the original string untouched unless a real JSON string layer is
successfully unwrapped.
"""
from pathlib import Path


SHIM = Path("crates/adapters/src/responses/grok_tool_shim.rs")
MARKER = "CAS-SUB2API-GROK-APPLY-PATCH-R17-PRESERVE-RAW-V4A"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


text = read(SHIM)
if MARKER in text:
    print("[ok] r17 raw-V4A byte-preservation hardening: already applied")
    raise SystemExit(0)

old = '''fn normalize_apply_patch_arguments(args_acc: &str) -> String {
    let mut current = args_acc.trim().to_owned();
    for _ in 0..2 {
        let Ok(Value::String(inner)) = serde_json::from_str::<Value>(&current) else {
            break;
        };
        let trimmed = inner.trim_start();
        if !trimmed.starts_with('{') && !inner.contains("*** Begin Patch") {
            break;
        }
        current = inner;
    }
    current
}
'''
new = f'''// {MARKER}
fn normalize_apply_patch_arguments(args_acc: &str) -> String {{
    // Preserve raw bare V4A byte-for-byte (notably a trailing newline). Trimming is only a
    // temporary JSON-parse view; `current` changes only after a real JSON string unwrap.
    let mut current = args_acc.to_owned();
    for _ in 0..2 {{
        let parse_view = current.trim();
        let Ok(Value::String(inner)) = serde_json::from_str::<Value>(parse_view) else {{
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
'''
if old not in text:
    raise SystemExit("anchor not found: normalize_apply_patch_arguments")
text = text.replace(old, new, 1)

anchor = '''    #[test]
    fn apply_patch_unwraps_double_encoded_arguments() {
'''
test = r'''    #[test]
    fn normalize_apply_patch_arguments_preserves_raw_v4a_trailing_newline() {
        let patch = "*** Begin Patch\n*** Add File: preserve.txt\n+ok\n*** End Patch\n";
        assert_eq!(normalize_apply_patch_arguments(patch), patch);
    }

'''
if anchor not in text:
    raise SystemExit("anchor not found: double-encoded regression")
text = text.replace(anchor, test + anchor, 1)

write(SHIM, text)
print("[ok] Grok apply_patch r17 third self-review overlay applied")
