# r38 Proxy Lifecycle Hardening Research — 2026-08-18

## Incident this revision addresses

On Windows 11, the configured Transfer listener `127.0.0.1:18089` can survive an application restart in an unusable state:

- `Get-NetTCPConnection` reports `LISTENING`, with the original `OwningProcess` and `CreationTime`.
- the original PID no longer exists in `tasklist`/`Get-Process`;
- `netstat -abno` attributes the endpoint to `[System]`;
- TCP connect succeeds but HTTP receives no application response;
- a fresh Transfer instance gets Winsock `10048 / WSAEADDRINUSE` for the same port.

The r37 tray `Quit Codex App Transfer` path is a real application exit: it calls `ProxyManager::stop_silent()` and then `app.exit(0)`. `RunEvent::Exit` calls `stop_silent()` again, so this incident is **not** explained by close-to-tray user behaviour.

## What the r37 source gets wrong

`src-tauri/src/proxy_runner.rs` treats `tokio::runtime::Runtime::shutdown_background()` as though it were a synchronous shutdown barrier that guarantees spawned server tasks, `TcpListener`, runtime workers and file descriptors have already been destroyed when the function returns.

Tokio documents the opposite: `shutdown_background()` does **not wait** for spawned work to stop and is equivalent to `shutdown_timeout(Duration::from_nanos(0))`. Therefore r37 has no proof that the old listener is gone before another start path attempts to bind the same port.

This is a confirmed lifecycle design defect even if it is not, by itself, enough to explain the multi-hour stale Windows endpoint observed in this incident.

## External research

### Tokio

Tokio's runtime shutdown documentation says:

- tasks keep running until they yield and are then dropped;
- `shutdown_background()` returns without waiting;
- `shutdown_timeout()` only waits up to the supplied duration;
- once the runtime is dropped, I/O resources bound to it no longer function.

This means the application must coordinate service shutdown explicitly if it needs a deterministic "old listener is gone before new bind" boundary.

Tokio's own graceful-shutdown guidance and `tokio-util::task::TaskTracker` documentation use an explicit cancellation signal plus an explicit wait for tasks to exit. The important property is not a sleep; it is an acknowledgement/barrier.

### axum

`axum::serve(...).with_graceful_shutdown(signal)` is the supported server mechanism for stopping acceptance of new connections and completing the server future after a shutdown signal. The r37 code currently spawns bare `axum::serve(...)` and then destroys the surrounding runtime instead of giving the server its own lifecycle signal.

Axum has supported graceful shutdown since 0.7.3. Current axum release notes also contain a fix for leaking a Tokio task when `serve` is used without graceful shutdown, reinforcing the value of using the explicit server lifecycle rather than relying on runtime destruction.

### Windows Winsock

For a TCP server, Windows returns `WSAEADDRINUSE / 10048` when the requested address/port is already bound.

Do **not** paper over this with `SO_REUSEADDR`. Microsoft documents that, on Windows, forcing a second bind with `SO_REUSEADDR` can make which socket receives traffic undefined and can permit port hijacking. If a lower-level socket is introduced later, prefer the normal exclusive server semantics / `SO_EXCLUSIVEADDRUSE`, not `SO_REUSEADDR`.

Windows `GetExtendedTcpTable(TCP_TABLE_OWNER_PID_LISTENER)` is the native API for obtaining the PID that context-bound a TCP listener. A later r38 phase can use the existing `windows` dependency to enrich diagnostics without spawning PowerShell.

### Similar open-source behaviour

RustDesk contains Windows-specific commentary around the familiar "Only one usage of each socket address is normally permitted" bind failure and keeps listener ownership explicit. Its public issue/discussion history also shows that same-port multi-instance/server conflicts should be diagnosed as ownership/lifecycle problems rather than hidden by changing ports or enabling reuse.

## r38 engineering requirements

### P0 — deterministic listener shutdown

1. Give the axum server an explicit shutdown signal (`oneshot` is enough for one server generation).
2. Keep a completion acknowledgement for the server task.
3. On stop, signal graceful shutdown and wait for an acknowledgement for a bounded interval.
4. If grace expires, perform a bounded runtime shutdown fallback.
5. Verify that the listening port is bindable again before reporting stop complete.
6. Never use a blind fixed sleep as the definition of success.

### P0 — start/stop race hardening

r37 has a start TOCTOU window: `handle == None` is checked before an async bootstrap, and another start can enter before the first stores its handle.

r38 must:

- reject/serialize concurrent starts;
- record a stop generation/epoch so an app exit occurring during bootstrap cancels the newly-created listener before it is published;
- keep `stop_silent()` idempotent because the tray quit path and `RunEvent::Exit` both call it.

### P0 — lifecycle telemetry

Every listener generation should emit:

- application PID;
- monotonically increasing `listener_id`;
- requested and actual address;
- creation timestamp;
- `start_requested`, `listener_bound`, `listener_published`;
- `stop_requested`, `graceful_signal_sent`, `server_done` or `server_done_timeout`;
- `runtime_shutdown_complete`;
- `port_release_verified` or `stale_listener_detected`;
- bind failure and OS error.

This is intentionally local-only diagnostics and must not include prompts, tokens, request bodies or account secrets.

### P0 — recovery semantics

`10048` recovery must not repeatedly launch additional bind attempts without first classifying the current port state.

A safe recovery flow should be:

1. check the app's own published listener state;
2. if the same generation is healthy, reuse it — no rebind;
3. if stopping/starting is already in progress, wait/reject duplicate recovery;
4. if the port is occupied by another owner, report owner evidence and do not kill it automatically;
5. if Windows reports a stale owner PID, surface it as a stale-listener condition and preserve forensic data;
6. only retry after a verified release boundary.

### P1 — Windows owner attribution

Add a Windows-only helper around `GetExtendedTcpTable` to report the context-bound PID for the exact listener. If the PID is alive, resolve its executable path with existing native process helpers. If the PID is dead, preserve that fact explicitly rather than relabelling it as a generic unknown error.

### P1 — UX

- While recovery is running, disable the Recovery button and show a stage (`stopping`, `waiting for port`, `starting`, `verifying`).
- Do not show repeated 10048 toasts caused by the same recovery attempt.
- Distinguish `port occupied by live process` from `stale listener / dead owner PID`.
- Keep the existing fault-attribution view and add listener-generation evidence under Details.

### P1 — tests

Add regression tests for:

- start → stop → immediate rebind to the exact same port;
- repeated restart loop (at least 50 iterations in unit/integration test, larger Windows CI stress gate);
- two concurrent start calls;
- stop while bootstrap is in progress;
- double `stop_silent()`;
- active/slow request during stop (bounded graceful period then force fallback);
- bind conflict with a deliberately occupied port, verifying that r38 does not use `SO_REUSEADDR` and does not kill the owner;
- port-release verification before a new generation is published.

## Non-goals for the first r38 slice

- Do not change the user's configured port as a workaround.
- Do not reboot Windows as an automatic recovery action.
- Do not kill arbitrary processes that happen to own the configured port.
- Do not add `SO_REUSEADDR`.
- Do not mix the unrelated Docker/Sub2API health problem into the listener lifecycle fix.

## Planned r38 slices

1. **Lifecycle barrier + telemetry** — explicit axum graceful shutdown, bounded wait, port-release verification, listener IDs, start-race guard.
2. **Windows attribution** — `GetExtendedTcpTable` owner PID/executable diagnostics and stale-owner classification.
3. **Recovery UI** — progress state, duplicate-click lock, single recovery transaction.
4. **Windows stress CI** — repeated start/stop/rebind and conflict injection.

The r38 implementation remains an outer-layer overlay/composer so it can be replayed on top of future upstream revisions rather than becoming a hard-to-rebase fork.