from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R60-POST-COMPACTION-BORROW-SAFETY"

text = FORWARD.read_text(encoding="utf-8")
if MARKER in text:
    print("r60 post-compaction borrow-safety repair already applied")
    raise SystemExit(0)

if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" not in text:
    raise SystemExit("r60 borrow-safety repair requires the post-compaction replay overlay first")

old = '''    if translated > 0 {
        // serde_json::Value containing only parsed JSON is infallibly serializable in
'''
new = '''    // CAS-R60-POST-COMPACTION-BORROW-SAFETY
    // Capture the array length before serializing `root`.  This lets the mutable
    // `input` borrow end before `serde_json::to_vec(&root)`, avoiding an overlapping
    // mutable/immutable borrow on Rust's ownership checker.
    let after = input.len();

    if translated > 0 {
        // serde_json::Value containing only parsed JSON is infallibly serializable in
'''
if old not in text:
    raise SystemExit("r60 borrow-safety anchor missing before serialization")
text = text.replace(old, new, 1)

old_after = "        input_items_after: input.len(),\n"
new_after = "        input_items_after: after,\n"
if old_after not in text:
    raise SystemExit("r60 borrow-safety input_items_after anchor missing")
text = text.replace(old_after, new_after, 1)

for marker in (
    MARKER,
    "let after = input.len();",
    "input_items_after: after",
):
    if marker not in text:
        raise SystemExit(f"r60 borrow-safety invariant missing: {marker}")

FORWARD.write_text(text, encoding="utf-8")
print("R60 POST-COMPACTION BORROW-SAFETY PASS")
