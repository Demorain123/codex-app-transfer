from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

runtime = RUNTIME.read_text(encoding="utf-8")

FN_DECL = re.compile(
    r"(?m)^[ \t]*(?:pub(?:\([^\r\n)]*\))?[ \t]+)?"
    r"(?:(?:async|const|unsafe)[ \t]+)*fn[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*\("
)


def matching_brace(text: str, opening: int) -> int:
    """Return one-past the matching Rust body brace, ignoring strings/comments."""
    depth = 0
    block_depth = 0
    raw_hashes = 0
    state = "code"
    i = opening

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                block_depth = 1
                i += 2
                continue
            if ch == "r":
                j = i + 1
                while j < len(text) and text[j] == "#":
                    j += 1
                if j < len(text) and text[j] == '"':
                    raw_hashes = j - i - 1
                    state = "raw"
                    i = j + 1
                    continue
            if ch == '"':
                state = "string"
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
                if depth < 0:
                    raise SystemExit("r43 runtime classifier repair: negative brace depth")
            i += 1
            continue

        if state == "line":
            if ch in "\r\n":
                state = "code"
            i += 1
            continue

        if state == "block":
            if ch == "/" and nxt == "*":
                block_depth += 1
                i += 2
                continue
            if ch == "*" and nxt == "/":
                block_depth -= 1
                i += 2
                if block_depth == 0:
                    state = "code"
                continue
            i += 1
            continue

        if state == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                state = "code"
            i += 1
            continue

        if state == "raw":
            if ch == '"' and text.startswith("#" * raw_hashes, i + 1):
                i += 1 + raw_hashes
                raw_hashes = 0
                state = "code"
                continue
            i += 1

    raise SystemExit("r43 runtime classifier repair: closing brace missing")


def unique_decl(text: str, name: str) -> re.Match[str]:
    matches = [m for m in FN_DECL.finditer(text) if m.group(1) == name]
    if len(matches) != 1:
        raise SystemExit(
            f"r43 runtime classifier repair: expected exactly one {name}() declaration, found {len(matches)}"
        )
    return matches[0]


def locate_rewrite_span(text: str) -> tuple[int, int]:
    """Return the whole region owned by classify(), up to emit_native_event().

    r43 historically patched tuples inside classify() and could temporarily leave
    an extra brace or an orphan collab block.  In that state the first balanced
    closing brace is not a trustworthy rewrite boundary.  The r26 runtime contract
    has a stable emit_native_event() sink immediately after the classifier region,
    so prefer that declaration as the end boundary.  If a future source genuinely
    removes that sink, fall back to the classifier's own balanced body.
    """
    classify = unique_decl(text, "classify")
    start = classify.start()

    emit_matches = [m for m in FN_DECL.finditer(text) if m.group(1) == "emit_native_event"]
    emit_after = [m for m in emit_matches if m.start() > start]
    if len(emit_after) == 1:
        return start, emit_after[0].start()
    if len(emit_after) > 1:
        raise SystemExit(
            f"r43 runtime classifier repair: multiple emit_native_event() declarations after classify(): {len(emit_after)}"
        )

    # Last-resort compatibility fallback for a future runtime watcher layout.
    opening = text.find("{", classify.end())
    if opening < 0:
        raise SystemExit("r43 runtime classifier repair: classify() body opening brace missing")
    return start, matching_brace(text, opening)


# Regression proof: an orphan block after a prematurely-closed classify() must be
# consumed by the rewrite span rather than being left behind to break rustfmt.
_probe = '''fn classify(lower: &str) -> Option<()> {
    if lower.contains("base") { return Some(()); }
    None
}
if lower.contains("collabtoolcall") { bogus(); }
fn emit_native_event(line: &str) { let _ = line; }
'''
_probe_start, _probe_end = locate_rewrite_span(_probe)
if _probe_start != 0 or "collabtoolcall" not in _probe[_probe_start:_probe_end]:
    raise SystemExit("r43 runtime classifier repair: malformed-intermediate boundary self-test failed")
if not _probe[_probe_end:].startswith("fn emit_native_event"):
    raise SystemExit("r43 runtime classifier repair: emit boundary self-test failed")

# Also retain the fallback contract when classify() is the final function.
_probe_last = 'fn classify(lower: &str) -> Option<()> {\n    None\n}'
_last_start, _last_end = locate_rewrite_span(_probe_last)
if (_last_start, _last_end) != (0, len(_probe_last)):
    raise SystemExit("r43 runtime classifier repair: final-function fallback self-test failed")

start, replace_end = locate_rewrite_span(runtime)
source_segment = runtime[start:replace_end]

# Only identify the inherited r26 classifier here.  Do NOT require r43 markers or
# collab markers before repair: this script exists specifically to recover a
# partially-mutated intermediate classifier.  The complete behavior is enforced
# strictly after canonical reconstruction below.
for marker in (
    '"agent loop died unexpectedly"',
    '"error submitting message"',
    '"context automatically compacted"',
):
    if marker not in source_segment:
        raise SystemExit(
            f"r43 runtime classifier repair: stable r26 identity marker missing: {marker}"
        )

canonical = '''fn classify(lower: &str) -> Option<(&'static str, &'static str)> {
    // CAS-R43-RUNTIME-CLASSIFIER-CANONICAL
    for (needle, event, level) in [
        ("agent loop died unexpectedly", "agent_loop_died", "ERROR"),
        ("error submitting message", "error_submitting_message", "ERROR"),
        ("error creating task", "error_creating_task", "ERROR"),
        ("failed to start turn", "failed_to_start_turn", "ERROR"),
        ("app-server connection closed", "app_server_connection_closed", "WARN"),
        ("codex cli process exited", "cli_process_exited", "WARN"),
        ("classifiedasexpected=false", "cli_process_unexpected_exit", "WARN"),
        ("stdio_transport_spawned", "stdio_transport_spawned", "INFO"),
        ("context automatically compacting", "context_auto_compacting", "INFO"),
        ("model changed from", "model_switch_selected", "INFO"),
        ("compact v2 upstream", "compact_v2_upstream_failed", "WARN"),
        ("context automatically compacted", "context_auto_compacted", "INFO"),
        ("remote_compaction_v2", "remote_compaction_v2", "WARN"),
        // CAS-RUNTIME-DIAG-R26-STREAM-MARKER: event = "stream_disconnected"
        ("stream disconnected", "stream_disconnected", "WARN"),
        ("response.failed", "response_failed", "WARN"),
        ("reconnecting", "reconnecting", "WARN"),
        ("upstream request failed", "upstream_request_failed", "WARN"),
    ] {
        if lower.contains(needle) {
            return Some((event, level));
        }
    }
    if lower.contains("collabtoolcall") {
        for (needle, event) in [
            ("spawn_agent", "collab_spawn_agent"),
            ("send_input", "collab_send_input"),
            ("resume_agent", "collab_resume_agent"),
            ("close_agent", "collab_close_agent"),
            ("wait", "collab_wait"),
        ] {
            if lower.contains(needle) {
                return Some((event, "INFO"));
            }
        }
    }
    None
}

'''

runtime = runtime[:start] + canonical + runtime[replace_end:]
RUNTIME.write_text(runtime, encoding="utf-8")

# Post-repair contract: all inherited and r43 behavior must now live inside the
# canonical classifier region, not merely somewhere in the file.
final = RUNTIME.read_text(encoding="utf-8")
final_start, final_end = locate_rewrite_span(final)
final_segment = final[final_start:final_end]
required_after = (
    "CAS-R43-RUNTIME-CLASSIFIER-CANONICAL",
    '"agent loop died unexpectedly"',
    '"error submitting message"',
    '"error creating task"',
    '"failed to start turn"',
    '"app-server connection closed"',
    '"codex cli process exited"',
    '"classifiedasexpected=false"',
    '"stdio_transport_spawned"',
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
for marker in required_after:
    if marker not in final_segment:
        raise SystemExit(
            f"r43 runtime classifier repair: post-repair contract missing inside classify(): {marker}"
        )

# These are cardinality checks, not all "unique" checks.  The remote-compaction
# tuple intentionally contains the same string twice: once as the input needle and
# once as the emitted event name.
for marker, expected_count in (
    ("CAS-R43-RUNTIME-CLASSIFIER-CANONICAL", 1),
    ('"collabtoolcall"', 1),
    ('"remote_compaction_v2"', 2),
):
    count = final.count(marker)
    if count != expected_count:
        raise SystemExit(
            f"r43 runtime classifier repair: expected {expected_count} post-repair occurrence(s) of {marker}, found {count}"
        )

print("r43 runtime classifier repair: malformed-intermediate boundary self-tests PASS")
print("r43 runtime classifier repair: canonical classifier region rebuilt through emit boundary")
print("r43 runtime classifier repair: complete post-repair contract PASS")
