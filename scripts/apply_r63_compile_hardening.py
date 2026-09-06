from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R63-COMPILE-HARDENING"
HELPER = "fn portableize_input_item_r63("

source = FORWARD.read_text(encoding="utf-8")

if "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE" not in source:
    raise SystemExit("r63 compile hardening requires the r63 auth-epoch overlay first")

if MARKER in source and HELPER in source and "let mut lower = |item:" not in source:
    print("r63 compile hardening already applied")
    raise SystemExit(0)

# The initial r63 overlay used a closure that captured `stats` mutably and then read
# `stats` while the closure remained alive. Rust correctly rejects that borrow shape.
# Move item lowering into a normal helper taking `&mut EncryptedReplayStatsR63`; this
# preserves semantics while making the borrow end after each call.
if HELPER not in source:
    anchor = "fn portableize_encrypted_history_r63(\n"
    if anchor not in source:
        raise SystemExit("r63 compile hardening: portableize function anchor missing")
    helper = r'''// CAS-R63-COMPILE-HARDENING
fn portableize_input_item_r63(
    item: serde_json::Value,
    stats: &mut EncryptedReplayStatsR63,
    drop_unknown_encrypted_items: bool,
) -> Option<serde_json::Value> {
    let kind = item
        .get("type")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("");
    match kind {
        "reasoning" => {
            stats.reasoning_dropped += 1;
            None
        }
        "compaction" | "context_compaction" | "compaction_summary" => {
            let summary = item
                .get("encrypted_content")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .trim();
            if summary.is_empty() {
                stats.empty_compactions_dropped += 1;
                None
            } else {
                stats.compaction_portable_messages += 1;
                Some(serde_json::json!({
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": summary}],
                }))
            }
        }
        _ if drop_unknown_encrypted_items
            && item
                .get("encrypted_content")
                .and_then(serde_json::Value::as_str)
                .is_some_and(|value| !value.trim().is_empty()) =>
        {
            stats.unknown_encrypted_items_dropped += 1;
            None
        }
        _ => Some(item),
    }
}

'''
    source = source.replace(anchor, helper + anchor, 1)

closure_start = "    let mut lower = |item: serde_json::Value| -> Option<serde_json::Value> {\n"
closure_end = "    };\n\n    if let Some(input) = obj.get_mut(\"input\") {\n"
if closure_start in source:
    start = source.index(closure_start)
    end = source.find(closure_end, start)
    if end < 0:
        raise SystemExit("r63 compile hardening: closure end anchor missing")
    end += len("    };\n\n")
    source = source[:start] + source[end:]

old_array = "                    if let Some(item) = lower(item) {\n"
new_array = "                    if let Some(item) = portableize_input_item_r63(\n                        item,\n                        &mut stats,\n                        drop_unknown_encrypted_items,\n                    ) {\n"
if old_array in source:
    source = source.replace(old_array, new_array, 1)

old_object = "                match lower(item) {\n"
new_object = "                match portableize_input_item_r63(\n                    item,\n                    &mut stats,\n                    drop_unknown_encrypted_items,\n                ) {\n"
if old_object in source:
    source = source.replace(old_object, new_object, 1)

# serde_json::Map::new() is supported across all serde_json versions used by this
# repository; avoid relying on a capacity constructor in a generated hotfix layer.
source = source.replace(
    "    let mut serial = serde_json::Map::with_capacity(sessions.len());\n",
    "    let mut serial = serde_json::Map::new();\n",
    1,
)

for invariant in (
    MARKER,
    HELPER,
    "portableize_input_item_r63(\n                        item,",
    "portableize_input_item_r63(\n                    item,",
):
    if invariant not in source:
        raise SystemExit(f"r63 compile hardening invariant missing: {invariant}")
if "let mut lower = |item:" in source:
    raise SystemExit("r63 compile hardening failed: mutable-capture closure still present")

FORWARD.write_text(source, encoding="utf-8")
print("R63 COMPILE HARDENING PASS")
print("- encrypted-history item lowering now uses an explicit &mut stats helper")
print("- no long-lived mutable closure borrow remains")
print("- serde_json Map construction uses the conservative stable constructor")
