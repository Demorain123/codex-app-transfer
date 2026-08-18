# r39 Proxy Lifecycle Reliability — research and implementation decision

Date: 2026-08-18
Scope: Sub2API Grok Compat thin overlay on r38; Windows localhost proxy lifecycle / recovery only.

## Incident evidence driving r39

The current r37 incident is not a normal "user forgot to exit" case. The tray Quit path calls `ProxyManager::stop_silent()` and then exits the app, while the observed Windows TCP endpoint on `127.0.0.1:18089` survived after its original PID disappeared and later caused repeated WSAEADDRINUSE / 10048 failures.

r37 also treats `tokio::runtime::Runtime::shutdown_background()` as if it were a synchronous listener-close barrier. Tokio explicitly documents the opposite: it does **not wait** for spawned work to stop and is equivalent to a zero-duration shutdown timeout.

## External research

### Tokio / Axum

- Tokio runtime shutdown documentation:
  - https://docs.rs/tokio/latest/tokio/runtime/struct.Runtime.html
  - https://docs.rs/tokio/latest/src/tokio/runtime/runtime.rs.html
- Tokio graceful shutdown topic:
  - https://tokio.rs/tokio/topics/shutdown
- Axum built-in graceful server shutdown:
  - https://docs.rs/axum/latest/axum/serve/struct.Serve.html#method.with_graceful_shutdown

The common lifecycle is: signal shutdown, wait for the server future to finish, use a bounded fallback if necessary, and only then consider the listener lifecycle complete. Runtime destruction is not the shutdown protocol.

### Official Model Context Protocol Rust SDK

The official Rust SDK uses `CancellationToken` with `axum::serve(...).with_graceful_shutdown(...)`, and its child-process transport implements graceful shutdown as close -> wait with timeout -> kill only the owned child as fallback.

- https://github.com/modelcontextprotocol/rust-sdk/blob/main/examples/servers/src/counter_streamhttp.rs
- https://github.com/modelcontextprotocol/rust-sdk/blob/main/crates/rmcp/src/transport/child_process.rs

This supports an explicit lifecycle signal plus completion wait rather than fixed sleeps.

### Cloudflare Pingora

Pingora makes graceful shutdown/restart a first-class server lifecycle feature. It stops accepting new work, finishes in-flight work, and when developers bypass the built-in `Server`, community guidance explicitly joins/waits for service tasks during shutdown.

- https://github.com/cloudflare/pingora/blob/main/docs/quick_start.md
- https://github.com/cloudflare/pingora/discussions/641

### Tauri community

A 2025 Tauri plugins feature request describes the same production lifecycle requirements for local infrastructure/sidecars: process monitoring, health checks, port conflict resolution, graceful shutdown, orphan cleanup, crash detection/backoff and cross-platform shutdown handling.

- https://github.com/tauri-apps/plugins-workspace/issues/3062

### Windows socket behavior

Do **not** solve this by setting `SO_REUSEADDR` or `SO_LINGER`.

Microsoft documents that Windows `SO_REUSEADDR` can allow another socket to overtake a port with undefined packet dispatch, while `SO_EXCLUSIVEADDRUSE` has its own delayed-reuse semantics when accepted connections remain active.

- https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse

The correct solution is lifecycle ownership and release verification, not socket-option bypass.

### Similar real-world failure

Mitmproxy has also received reports where users hit "Address already in use" even though ordinary process inspection did not make the owner obvious. The lesson for r39 is to expose ownership/lifecycle evidence in the app rather than returning a generic bind error.

- https://github.com/mitmproxy/mitmproxy/issues/5492

## r39 design decisions

1. Preserve r38 completely; r39 is a replayable outer-shell overlay.
2. Replace `shutdown_background()` as proxy lifecycle control.
3. Keep proxy runtime on a dedicated OS thread, but own the runtime entirely on that thread.
4. Server shutdown protocol:
   - send explicit graceful signal;
   - await server future for a bounded grace period;
   - abort only the app-owned server task if grace expires;
   - wait again;
   - shut down runtime with a bounded timeout on the runtime thread;
   - verify the exact listen address can be rebound before reporting stop complete.
5. A new start is forbidden while start/stop is in progress.
6. A port still busy after verified internal shutdown is classified as external/stale. r39 must not kill an unknown process and must not enable `SO_REUSEADDR`.
7. Replace recovery's fixed `sleep(150ms)` correctness assumption with the verified stop barrier.
8. Recovery is single-flight. Cooldown begins after recovery completes, not when the button is first clicked.
9. Add lifecycle evidence:
   - app PID;
   - monotonic listener ID;
   - address;
   - listener created;
   - stop requested;
   - graceful timeout / force abort;
   - server task exit/abort;
   - port-release verification result;
   - last bind error.
10. Chain Health distinguishes ordinary `transfer_stopped` from `transfer_port_in_use`.

## Required regression tests

- Stop then immediate same-port rebind succeeds.
- 50 rapid same-port start/verified-stop cycles succeed.
- An externally owned listener blocks start but is never killed/reused.
- Windows CI runs proxy lifecycle tests on `x86_64-pc-windows-msvc`.
- Full r38->r39 composer is idempotent after rustfmt.
- Existing proxy security/auth tests and adapter tests remain green.

## Deliberately excluded from r39

- No process killing for unknown port owners.
- No WFP/driver manipulation.
- No `SO_REUSEADDR` / `SO_LINGER` workaround.
- No automatic port number hopping that hides the root cause.
- No change to Grok/Luna routing semantics, Auto Review, Hybrid Direct, quota attribution, or r38 model-route observability except where lifecycle status is surfaced.
