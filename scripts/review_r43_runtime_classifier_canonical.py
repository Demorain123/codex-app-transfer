from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

text = RUNTIME.read_text(encoding="utf-8")

# classify() is expected to remain a normal top-level declaration.  The sink is
# deliberately discovered more loosely: r43 review runs on a generated
# intermediate file, and earlier tuple/brace drift can temporarily glue the next
# declaration to a closing brace or change visibility/async/generic decoration.
CLASSIFY_DECL = re.compile(
    r"(?m)^[ \t]*(?:pub(?:\([^\r\n)]*\))?[ \t]+)?"
    r"(?:(?:async|const|unsafe)[ \t]+)*fn[ \t]+classify[ \t]*\("
)
SINK_DECL = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:pub(?:\([^\r\n)]*\))?[ \t]+)?"
    r"(?:(?:async|const|unsafe)[ \t]+)*"
    r"fn[ \t]+emit_native_event\b"
)


def exactly_one(pattern: re.Pattern[str], source: str, label: str) -> re.Match[str]:
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise SystemExit(
            f"r43 runtime canonical review: expected exactly one {label}, found {len(matches)}"
        )
    return matches[0]


# Regression proofs for the layouts that previously made repair/review disagree.
_probe_normal = (
    'fn classify(lower: &str) -> Option<()> { None }\n'
    'pub(crate) async fn emit_native_event(line: &str) { let _ = line; }\n'
)
_probe_glued_generic = (
    'fn classify(lower: &str) -> Option<()> { None }}'
    'pub(crate) async fn emit_native_event<T>(line: T) {}\n'
)
for probe in (_probe_normal, _probe_glued_generic):
    c = exactly_one(CLASSIFY_DECL, probe, "classify() in parser self-test")
    s = exactly_one(SINK_DECL, probe, "emit_native_event in parser self-test")
    if s.start() <= c.start():
        raise SystemExit("r43 runtime canonical review: parser ordering self-test failed")

classify_match = exactly_one(CLASSIFY_DECL, text, "classify()")
start = classify_match.start()
sink_matches = [m for m in SINK_DECL.finditer(text) if m.start() > start]
if len(sink_matches) != 1:
    raise SystemExit(
        f"r43 runtime canonical review: expected exactly one emit_native_event sink after classify(), found {len(sink_matches)}"
    )
emit = sink_matches[0].start()

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

# Cardinality is scoped to classify() itself, so unrelated future diagnostics do
# not create false positives. remote_compaction_v2 is needle + emitted event.
for marker, expected_count in (
    ("CAS-R43-RUNTIME-CLASSIFIER-CANONICAL", 1),
    ('"collabtoolcall"', 1),
    ('"remote_compaction_v2"', 2),
):
    count = segment.count(marker)
    if count != expected_count:
        raise SystemExit(
            f"r43 runtime canonical review: expected {expected_count} occurrence(s) of {marker} inside classify(), found {count}"
        )

normalized = segment.rstrip()
if not normalized.endswith("None\n}") and not normalized.endswith("None\r\n}"):
    raise SystemExit(
        "r43 runtime canonical review: classify() does not end canonically before emit_native_event()"
    )

# Classifier-only markers must not leak into the sink/tail region.
tail = text[emit:]
for marker in ('"collabtoolcall"', '"remote_compaction_v2"', '"model changed from"'):
    if marker in tail:
        raise SystemExit(
            f"r43 runtime canonical review: classifier marker leaked after classify(): {marker}"
        )

print("R43 RUNTIME CLASSIFIER CANONICAL REVIEW PASS")
print("- classify() is canonical and ends before the runtime sink")
print("- sink discovery is independent of line breaks, visibility, async, and generics")
print("- inherited + model-switch + compaction + collab markers are inside classify()")
print("- marker cardinality is scoped to classify()")
print("- no classifier marker leaks into the runtime sink/tail")
