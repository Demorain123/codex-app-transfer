from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"

runtime = RUNTIME.read_text(encoding="utf-8")

# Locate by semantic function names rather than whitespace/newline layout.  The r43
# overlay can temporarily leave classify() syntactically malformed, so the repair
# gate must not depend on rustfmt-style spacing around the following function.
start_token = "fn classify("
end_token = "fn emit_native_event("
start = runtime.find(start_token)
end = runtime.find(end_token, start + len(start_token) if start >= 0 else 0)
if start < 0:
    raise SystemExit("r43 runtime classifier repair: classify() function marker missing")
if end < 0 or end <= start:
    raise SystemExit("r43 runtime classifier repair: emit_native_event() boundary missing")

# Preserve any whitespace immediately before the following function as part of the
# replacement boundary.  This makes the rebuilt block deterministic without relying
# on CRLF/LF or one-vs-two blank lines.
replace_end = end
while replace_end > start and runtime[replace_end - 1] in " \t\r\n":
    replace_end -= 1

segment = runtime[start:end]
# Fail closed unless this is still the expected r26+r43 classifier surface.
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
print("r43 runtime classifier repair: canonical classify() rebuilt after semantic verification")
print("r43 runtime classifier repair: PASS")
