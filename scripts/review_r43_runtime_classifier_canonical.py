from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

text = RUNTIME.read_text(encoding="utf-8")

# Keep declaration discovery identical to the canonical repair script.  The
# previous review used a narrower `^\s*fn ...` regex and could disagree with the
# repair even after the repair had already proved the generated classifier/sink
# structure was valid.  A review gate must not use a different parser contract.
FN_DECL = re.compile(
    r"(?m)^[ \t]*(?:pub(?:\([^\r\n)]*\))?[ \t]+)?"
    r"(?:(?:async|const|unsafe)[ \t]+)*fn[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*\("
)


def unique_decl(source: str, name: str) -> re.Match[str]:
    matches = [m for m in FN_DECL.finditer(source) if m.group(1) == name]
    if len(matches) != 1:
        discovered = ",".join(m.group(1) for m in FN_DECL.finditer(source)) or "<none>"
        raise SystemExit(
            f"r43 runtime canonical review: expected exactly one {name}(), found {len(matches)}; "
            f"discovered top-level fn names={discovered}"
        )
    return matches[0]


# Regression proof: visibility/async decoration must not make the review disagree
# with the repair script's declaration scanner.
_probe = '''fn classify(lower: &str) -> Option<()> { None }\npub(crate) async fn emit_native_event(line: &str) { let _ = line; }\n'''
if unique_decl(_probe, "classify").start() != 0:
    raise SystemExit("r43 runtime canonical review: classifier declaration self-test failed")
if unique_decl(_probe, "emit_native_event").start() <= 0:
    raise SystemExit("r43 runtime canonical review: emit declaration self-test failed")

classify_match = unique_decl(text, "classify")
emit_match = unique_decl(text, "emit_native_event")
start = classify_match.start()
emit = emit_match.start()
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
print("- repair/review use the same Rust function-declaration scanner")
print("- exactly one classify() and one emit_native_event()")
print("- inherited + model-switch + compaction + collab markers are inside classify()")
print("- marker cardinality matches canonical classifier semantics")
print("- no orphan classifier block survives before/after the emit sink")
