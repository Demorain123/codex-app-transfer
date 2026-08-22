from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

runtime = RUNTIME.read_text(encoding="utf-8")

# Do not depend on the *name* or formatting of the function after classify().
# Earlier overlays may rustfmt/rewrite that declaration, and r43 itself can leave
# classify() temporarily unparsable.  Top-level Rust function declarations are a
# much more stable boundary than an exact `fn emit_native_event(` substring.
FN_DECL = re.compile(
    r"(?m)^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
)


def locate_function_span(text: str, name: str) -> tuple[int, int]:
    declarations = list(FN_DECL.finditer(text))
    matches = [m for m in declarations if m.group(1) == name]
    if len(matches) != 1:
        raise SystemExit(
            f"r43 runtime classifier repair: expected exactly one {name}() declaration, found {len(matches)}"
        )

    current = matches[0]
    following = next((m for m in declarations if m.start() > current.start()), None)
    if following is None:
        raise SystemExit(
            f"r43 runtime classifier repair: no following top-level function after {name}()"
        )
    return current.start(), following.start()


# Contract probes: the boundary locator must survive a renamed/visible/async next
# function and formatting changes.  These are intentionally independent of the
# repository source so a future edit cannot silently reintroduce the old brittle
# emit_native_event-name dependency.
_probe = """fn classify (lower: &str) -> Option<()> {\n    if lower.contains(\"x\") { return Some(()); }\n    None\n}\n\npub(crate) async fn renamed_runtime_sink (line: &str) {\n    let _ = line;\n}\n"""
_probe_start, _probe_end = locate_function_span(_probe, "classify")
if _probe_start != 0 or not _probe[_probe_end:].startswith("pub(crate) async fn renamed_runtime_sink"):
    raise SystemExit("r43 runtime classifier repair: structural-boundary self-test failed")

start, end = locate_function_span(runtime, "classify")
segment = runtime[start:end]

# Fail closed unless this is still the expected r26+r43 classifier surface.  We
# tolerate formatting and delimiter drift, but never missing behavior.
for marker in (
    '"agent loop died unexpectedly"',
    '"error submitting message"',
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
        (
            "error submitting message",
            "error_submitting_message",
            "ERROR",
        ),
        ("error creating task", "error_creating_task", "ERROR"),
        ("failed to start turn", "failed_to_start_turn", "ERROR"),
        (
            "app-server connection closed",
            "app_server_connection_closed",
            "WARN",
        ),
        ("codex cli process exited", "cli_process_exited", "WARN"),
        (
            "classifiedasexpected=false",
            "cli_process_unexpected_exit",
            "WARN",
        ),
        ("stdio_transport_spawned", "stdio_transport_spawned", "INFO"),
        (
            "context automatically compacting",
            "context_auto_compacting",
            "INFO",
        ),
        ("model changed from", "model_switch_selected", "INFO"),
        (
            "compact v2 upstream",
            "compact_v2_upstream_failed",
            "WARN",
        ),
        (
            "context automatically compacted",
            "context_auto_compacted",
            "INFO",
        ),
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

runtime = runtime[:start] + canonical + runtime[end:]
RUNTIME.write_text(runtime, encoding="utf-8")
print("r43 runtime classifier repair: structural function boundary self-test PASS")
print("r43 runtime classifier repair: canonical classify() rebuilt after semantic verification")
print("r43 runtime classifier repair: PASS")
