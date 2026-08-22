from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

text = RUNTIME.read_text(encoding="utf-8")

classify_matches = list(re.finditer(r"(?m)^\s*fn\s+classify\s*\(", text))
emit_matches = list(re.finditer(r"(?m)^\s*fn\s+emit_native_event\s*\(", text))
if len(classify_matches) != 1:
    raise SystemExit(
        f"r43 runtime canonical review: expected exactly one classify(), found {len(classify_matches)}"
    )
if len(emit_matches) != 1:
    raise SystemExit(
        f"r43 runtime canonical review: expected exactly one emit_native_event(), found {len(emit_matches)}"
    )

start = classify_matches[0].start()
emit = emit_matches[0].start()
if emit <= start:
    raise SystemExit("r43 runtime canonical review: emit_native_event() does not follow classify()")

segment = text[start:emit]
required = (
    "CAS-R43-RUNTIME-CLASSIFIER-CANONICAL",
    '"agent loop died unexpectedly"',
    '"error submitting message"',
    '"context automatically compacting"',
    '"model changed from"',
    '"compact v2 upstream"',
    '"context automatically compacted"',
    '"remote_compaction_v2"',
    '"stream disconnected"',
    '"response.failed"',
    '"reconnecting"',
    '"upstream request failed"',
    '"collabtoolcall"',
    '"spawn_agent"',
    '"send_input"',
    '"resume_agent"',
    '"close_agent"',
    '"wait"',
)
for marker in required:
    if marker not in segment:
        raise SystemExit(
            f"r43 runtime canonical review: required marker is not inside classify(): {marker}"
        )

# remote_compaction_v2 appears twice by design in its classifier tuple: needle +
# event name.  The other sentinels remain singletons.
for marker, expected_count in (
    ("CAS-R43-RUNTIME-CLASSIFIER-CANONICAL", 1),
    ('"collabtoolcall"', 1),
    ('"remote_compaction_v2"', 2),
):
    count = text.count(marker)
    if count != expected_count:
        raise SystemExit(
            f"r43 runtime canonical review: expected {expected_count} occurrence(s) of {marker}, found {count}"
        )

# The canonical function must end before the emit sink.  This catches the exact
# family of r43 failures where tuple/brace drift left classifier statements orphaned
# between a premature closing brace and emit_native_event().
normalized = segment.rstrip()
if not normalized.endswith("None\n}") and not normalized.endswith("None\r\n}"):
    raise SystemExit(
        "r43 runtime canonical review: classify() does not end canonically before emit_native_event()"
    )

# No classifier-only marker may leak into the emit/tail region.
tail = text[emit:]
for marker in ('"collabtoolcall"', '"remote_compaction_v2"', '"model changed from"'):
    if marker in tail:
        raise SystemExit(
            f"r43 runtime canonical review: classifier marker leaked after classify(): {marker}"
        )

print("R43 RUNTIME CLASSIFIER CANONICAL REVIEW PASS")
print("- exactly one classify() and one emit_native_event()")
print("- inherited + model-switch + compaction + collab markers are inside classify()")
print("- marker cardinality matches canonical classifier semantics")
print("- no orphan classifier block survives before/after the emit sink")
