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


def _matching_brace(text: str, opening: int) -> int:
    # Return one-past the matching body brace, ignoring Rust strings/comments.
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

    raise SystemExit("r43 runtime classifier repair: classify() closing brace missing")


def locate_function_span(text: str, name: str) -> tuple[int, int]:
    matches = [m for m in FN_DECL.finditer(text) if m.group(1) == name]
    if len(matches) != 1:
        raise SystemExit(
            f"r43 runtime classifier repair: expected exactly one {name}() declaration, found {len(matches)}"
        )
    match = matches[0]
    opening = text.find("{", match.end())
    if opening < 0:
        raise SystemExit(f"r43 runtime classifier repair: {name}() body opening brace missing")
    return match.start(), _matching_brace(text, opening)


# Boundary regression: no following function is required, and a following renamed
# function must not be consumed. Braces in ordinary/raw strings and comments are ignored.
_probe = r'''fn classify(lower: &str) -> Option<()> {
    let a = "{ string }";
    let b = r#"{ raw }"#;
    // }
    /* { nested /* } */ } */
    if lower.contains("x") { return Some(()); }
    None
}

pub(crate) async fn renamed_sink(line: &str) { let _ = line; }
'''
_probe_start, _probe_end = locate_function_span(_probe, "classify")
if _probe_start != 0 or not _probe[_probe_end:].lstrip().startswith("pub(crate) async fn renamed_sink"):
    raise SystemExit("r43 runtime classifier repair: structural-boundary self-test failed")

_probe_last = 'fn classify(lower: &str) -> Option<()> {\n    None\n}'
if locate_function_span(_probe_last, "classify") != (0, len(_probe_last)):
    raise SystemExit("r43 runtime classifier repair: final-function self-test failed")

start, end = locate_function_span(runtime, "classify")
segment = runtime[start:end]

for marker in (
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
):
    if marker not in segment:
        raise SystemExit(
            f"r43 runtime classifier repair: expected semantic marker missing: {marker}"
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

replace_end = end
while replace_end < len(runtime) and runtime[replace_end] in " \t\r\n":
    replace_end += 1

runtime = runtime[:start] + canonical + runtime[replace_end:]
RUNTIME.write_text(runtime, encoding="utf-8")
print("r43 runtime classifier repair: balanced-brace self-tests PASS")
print("r43 runtime classifier repair: canonical classify() rebuilt after semantic verification")
print("r43 runtime classifier repair: PASS")
