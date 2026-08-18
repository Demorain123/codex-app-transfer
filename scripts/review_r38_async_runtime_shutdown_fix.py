from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"

body = PATH.read_text(encoding="utf-8")

required = [
    "CAS-R38-PROXY-LIFECYCLE-HARDENING",
    "CAS-R38-ASYNC-RUNTIME-SHUTDOWN-FIX",
    "tokio::runtime::Handle::try_current().is_ok()",
    "h.runtime.shutdown_background();",
    "h.runtime.shutdown_timeout(RUNTIME_FORCE_WAIT);",
    '"background_async_safe"',
    '"bounded_timeout"',
    "server_done_rx.recv_timeout(GRACEFUL_SERVER_WAIT)",
    "wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT)",
]
for token in required:
    if token not in body:
        raise SystemExit(f"r38 async runtime shutdown review missing: {token}")

unsafe = '''    // Even after a graceful signal, bound the fallback. Unlike r37's
    // shutdown_background(), shutdown_timeout actually waits up to this duration.
    h.runtime.shutdown_timeout(RUNTIME_FORCE_WAIT);
'''
if unsafe in body:
    raise SystemExit(
        "r38 async runtime shutdown review: unconditional shutdown_timeout still reachable from async callers"
    )

# The async-safe fallback is intentionally paired with the pre-existing graceful
# completion acknowledgement and the post-shutdown bind probe. This preserves r38's
# deterministic listener-release contract while complying with Tokio's runtime-drop rules.
idx_guard = body.index("CAS-R38-ASYNC-RUNTIME-SHUTDOWN-FIX")
idx_done = body.index("server_done_rx.recv_timeout(GRACEFUL_SERVER_WAIT)")
idx_probe = body.index("wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT)")
if not idx_done < idx_guard < idx_probe:
    raise SystemExit(
        "r38 async runtime shutdown review: shutdown guard is not bracketed by server-done ack and port-release verification"
    )

print(
    "r38 async runtime shutdown review: PASS "
    "(Tokio-safe async shutdown + graceful ack + verified port release)"
)
