from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "crates/adapters/src/mapper/grok_build.rs"
text = TARGET.read_text(encoding="utf-8")

required = [
    "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD",
    "fn grok_effective_tool_name(tool: &Value) -> Option<&str>",
    "[grok-tool-collision] repaired duplicate provider-visible Grok tool name",
    'action = "deduplicated"',
    "grok_tool_collision_r42_native_plus_function_web_search_is_one",
    "grok_tool_collision_r42_duplicate_native_web_search_is_one",
    "grok_tool_collision_r42_function_first_preserves_client_routing",
    "grok_tool_collision_r42_ordinary_function_duplicate_still_dedups",
    "grok_tool_collision_r42_unique_tools_are_preserved",
    "grok_tool_collision_r42_discovered_function_cannot_duplicate_native_web_search",
]
for marker in required:
    if marker not in text:
        raise SystemExit(f"r42 review: missing marker: {marker}")

if "非 function(web_search)不参与去重" in text:
    raise SystemExit("r42 review: legacy function-only dedup contract still present")
if text.count("dedup_grok_tools_by_name(&mut out);") != 1:
    raise SystemExit("r42 review: final tool dedup must run exactly once after top-level + discovered tools merge")
if "prompt" in text[text.find("CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD"):text.find("/// 规整一个 input item")].lower():
    raise SystemExit("r42 review: collision guard must not log/read prompt content")

print("r42 Grok effective tool collision review: PASS")
