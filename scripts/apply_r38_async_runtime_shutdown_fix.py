from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R38-ASYNC-RUNTIME-SHUTDOWN-FIX"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 async runtime shutdown fix: already applied")
    raise SystemExit(0)

old = '''    // Even after a graceful signal, bound the fallback. Unlike r37's
    // shutdown_background(), shutdown_timeout actually waits up to this duration.
    h.runtime.shutdown_timeout(RUNTIME_FORCE_WAIT);
    lifecycle_log(
        "INFO",
        format!(
            "runtime_shutdown_complete listener_id={} app_pid={} timeout_ms={}",
            h.listener_id,
            pid,
            RUNTIME_FORCE_WAIT.as_millis()
        ),
    );
'''

new = '''    // CAS-R38-ASYNC-RUNTIME-SHUTDOWN-FIX
    // `shutdown_timeout` performs a blocking runtime drain. Tokio explicitly forbids
    // that operation when this synchronous lifecycle helper is reached from another
    // async runtime (for example provider-switch / Hybrid Direct handlers and tests).
    // In that context use Tokio's supported `shutdown_background` path; the explicit
    // graceful server-done acknowledgement above plus the port-bind verification below
    // remain the bounded listener-release barriers. Outside an async runtime keep the
    // stronger bounded `shutdown_timeout` drain.
    let inside_async_runtime = tokio::runtime::Handle::try_current().is_ok();
    if inside_async_runtime {
        h.runtime.shutdown_background();
    } else {
        h.runtime.shutdown_timeout(RUNTIME_FORCE_WAIT);
    }
    lifecycle_log(
        "INFO",
        format!(
            "runtime_shutdown_complete listener_id={} app_pid={} mode={} timeout_ms={}",
            h.listener_id,
            pid,
            if inside_async_runtime {
                "background_async_safe"
            } else {
                "bounded_timeout"
            },
            RUNTIME_FORCE_WAIT.as_millis()
        ),
    );
'''

if old not in body:
    raise SystemExit(
        "r38 async runtime shutdown fix: lifecycle shutdown anchor changed; refusing fuzzy patch"
    )

body = body.replace(old, new, 1)
PATH.write_text(body, encoding="utf-8")

check = PATH.read_text(encoding="utf-8")
required = [
    MARKER,
    "tokio::runtime::Handle::try_current().is_ok()",
    "h.runtime.shutdown_background();",
    "h.runtime.shutdown_timeout(RUNTIME_FORCE_WAIT);",
    '"background_async_safe"',
    '"bounded_timeout"',
    "port_release_verified",
]
for token in required:
    if token not in check:
        raise SystemExit(f"r38 async runtime shutdown fix missing marker: {token}")

if old in check:
    raise SystemExit("r38 async runtime shutdown fix: unsafe unconditional shutdown_timeout survived")

print("r38 async runtime shutdown fix: applied")
