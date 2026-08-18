from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R39-PROXY-LIFECYCLE-RELIABILITY"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r39 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r39 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Proxy runtime lifecycle: explicit graceful signal -> bounded force abort ->
# runtime shutdown -> port-release verification. Runtime destruction is no longer
# treated as a synchronous listener-close barrier.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/proxy_runner.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "//! 内嵌 axum 代理生命周期管理。\n",
        "//! 内嵌 axum 代理生命周期管理。\n//! CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
        "proxy runner marker",
    )
    body = replace_once(
        body,
        "use std::net::SocketAddr;\nuse std::sync::Arc;\nuse std::sync::Mutex;\n",
        "use std::net::{SocketAddr, TcpListener as StdTcpListener};\n"
        "use std::sync::{\n"
        "    atomic::{AtomicBool, AtomicU64, Ordering},\n"
        "    Arc, Mutex,\n"
        "};\n"
        "use std::thread::JoinHandle as ThreadJoinHandle;\n"
        "use std::time::{Duration, Instant};\n",
        "proxy runner std imports",
    )
    body = replace_once(
        body,
        "use tokio::sync::oneshot;\n",
        "use tokio::sync::oneshot;\nuse tokio::task::AbortHandle;\n",
        "abort handle import",
    )

    start = body.index("struct ProxyHandle {")
    end = body.index("\nstruct ResolverSnapshot {")
    lifecycle = r'''const PROXY_GRACEFUL_STOP_TIMEOUT: Duration = Duration::from_millis(750);
const PROXY_FORCE_STOP_TIMEOUT: Duration = Duration::from_millis(750);
const PROXY_RUNTIME_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(500);
const PROXY_PORT_RELEASE_TIMEOUT: Duration = Duration::from_millis(1500);
const PROXY_PORT_RELEASE_POLL: Duration = Duration::from_millis(25);
const PROXY_START_FINISH_TIMEOUT: Duration = Duration::from_millis(2000);
static PROXY_LISTENER_SEQUENCE: AtomicU64 = AtomicU64::new(1);

struct ProxyBootstrapReady {
    addr: SocketAddr,
    shutdown_tx: oneshot::Sender<()>,
    abort_handle: AbortHandle,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ProxyStopReport {
    pub was_running: bool,
    pub listener_id: Option<u64>,
    pub addr: Option<String>,
    pub graceful: bool,
    pub forced: bool,
    pub server_stopped: bool,
    pub port_released: bool,
    pub elapsed_ms: u64,
    pub last_bind_error: Option<String>,
    pub error: Option<String>,
}

impl ProxyStopReport {
    fn not_running() -> Self {
        Self {
            was_running: false,
            listener_id: None,
            addr: None,
            graceful: true,
            forced: false,
            server_stopped: true,
            port_released: true,
            elapsed_ms: 0,
            last_bind_error: None,
            error: None,
        }
    }

    fn busy(reason: impl Into<String>) -> Self {
        Self {
            was_running: false,
            listener_id: None,
            addr: None,
            graceful: false,
            forced: false,
            server_stopped: false,
            port_released: false,
            elapsed_ms: 0,
            last_bind_error: None,
            error: Some(reason.into()),
        }
    }
}

#[derive(Debug, Clone)]
struct ProxyLifecycleFault {
    code: String,
    message: String,
}

struct ProxyHandle {
    addr: SocketAddr,
    listener_id: u64,
    shutdown_tx: Option<oneshot::Sender<()>>,
    abort_handle: AbortHandle,
    stopped_rx: oneshot::Receiver<()>,
    thread: Option<ThreadJoinHandle<()>>,
    gateway_auth: bool,
    provider_count: usize,
    active_provider: Option<String>,
}

impl ProxyHandle {
    fn thread_finished(&self) -> bool {
        self.thread
            .as_ref()
            .map(|thread| thread.is_finished())
            .unwrap_or(true)
    }
}

impl Drop for ProxyHandle {
    fn drop(&mut self) {
        // A cancelled start/stop future must never strand a listener thread. Dropping
        // the handle sends graceful shutdown first and then aborts the server task as
        // a final safety net. The runtime remains owned by its dedicated OS thread.
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
        }
        self.abort_handle.abort();
    }
}

#[derive(Default)]
pub struct ProxyManager {
    handle: Mutex<Option<ProxyHandle>>,
    starting: AtomicBool,
    stopping: AtomicBool,
    last_fault: Mutex<Option<ProxyLifecycleFault>>,
}

struct AtomicFlagReset<'a>(&'a AtomicBool);

impl Drop for AtomicFlagReset<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn elapsed_ms(started: Instant) -> u64 {
    started.elapsed().as_millis().min(u64::MAX as u128) as u64
}

fn address_in_use_message(message: &str) -> bool {
    let lower = message.to_ascii_lowercase();
    lower.contains("os error 10048")
        || lower.contains("address already in use")
        || lower.contains("only one usage of each socket address")
}

fn wait_stopped_sync(rx: &mut oneshot::Receiver<()>, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match rx.try_recv() {
            Ok(()) => return true,
            Err(oneshot::error::TryRecvError::Closed) => return true,
            Err(oneshot::error::TryRecvError::Empty) => {}
        }
        if Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

async fn wait_stopped_async(rx: &mut oneshot::Receiver<()>, timeout: Duration) -> bool {
    match tokio::time::timeout(timeout, &mut *rx).await {
        Ok(Ok(())) | Ok(Err(_)) => true,
        Err(_) => false,
    }
}

fn probe_port_release_once(addr: SocketAddr) -> Result<(), String> {
    match StdTcpListener::bind(addr) {
        Ok(listener) => {
            drop(listener);
            Ok(())
        }
        Err(error) => Err(error.to_string()),
    }
}

fn wait_port_release_sync(addr: SocketAddr) -> (bool, Option<String>) {
    let deadline = Instant::now() + PROXY_PORT_RELEASE_TIMEOUT;
    let mut last = None;
    loop {
        match probe_port_release_once(addr) {
            Ok(()) => return (true, None),
            Err(error) => last = Some(error),
        }
        if Instant::now() >= deadline {
            return (false, last);
        }
        std::thread::sleep(PROXY_PORT_RELEASE_POLL);
    }
}

async fn wait_port_release_async(addr: SocketAddr) -> (bool, Option<String>) {
    let deadline = Instant::now() + PROXY_PORT_RELEASE_TIMEOUT;
    let mut last = None;
    loop {
        match probe_port_release_once(addr) {
            Ok(()) => return (true, None),
            Err(error) => last = Some(error),
        }
        if Instant::now() >= deadline {
            return (false, last);
        }
        tokio::time::sleep(PROXY_PORT_RELEASE_POLL).await;
    }
}

fn join_server_thread_if_stopped(handle: &mut ProxyHandle, server_stopped: bool) -> Option<String> {
    if !server_stopped {
        return None;
    }
    let Some(thread) = handle.thread.take() else {
        return None;
    };
    match thread.join() {
        Ok(()) => None,
        Err(_) => Some("proxy runtime thread panicked while shutting down".to_owned()),
    }
}

fn shutdown_handle_sync(mut handle: ProxyHandle) -> ProxyStopReport {
    let started = Instant::now();
    let listener_id = handle.listener_id;
    let addr = handle.addr;
    let app_pid = std::process::id();
    codex_app_transfer_proxy::proxy_telemetry().logs.add(
        "INFO",
        format!(
            "[proxy-lifecycle-r39] stop_requested listener_id={listener_id} app_pid={app_pid} addr={addr}"
        ),
    );

    if let Some(tx) = handle.shutdown_tx.take() {
        let _ = tx.send(());
    }

    let mut forced = false;
    let mut server_stopped = wait_stopped_sync(&mut handle.stopped_rx, PROXY_GRACEFUL_STOP_TIMEOUT);
    if !server_stopped {
        forced = true;
        codex_app_transfer_proxy::proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[proxy-lifecycle-r39] graceful_timeout listener_id={listener_id} action=abort_server"
            ),
        );
        handle.abort_handle.abort();
        server_stopped = wait_stopped_sync(&mut handle.stopped_rx, PROXY_FORCE_STOP_TIMEOUT);
    }

    let mut error = join_server_thread_if_stopped(&mut handle, server_stopped);
    let (port_released, last_bind_error) = wait_port_release_sync(addr);
    if !port_released && error.is_none() {
        error = Some("listener thread stopped but Windows bind probe still reports the port busy".to_owned());
    }

    let report = ProxyStopReport {
        was_running: true,
        listener_id: Some(listener_id),
        addr: Some(addr.to_string()),
        graceful: server_stopped && !forced,
        forced,
        server_stopped,
        port_released,
        elapsed_ms: elapsed_ms(started),
        last_bind_error,
        error,
    };
    let level = if report.port_released { "INFO" } else { "ERROR" };
    codex_app_transfer_proxy::proxy_telemetry().logs.add(
        level,
        format!(
            "[proxy-lifecycle-r39] port_release_verified={} listener_id={listener_id} app_pid={app_pid} addr={addr} graceful={} forced={} server_stopped={} elapsed_ms={} last_bind_error={}",
            report.port_released,
            report.graceful,
            report.forced,
            report.server_stopped,
            report.elapsed_ms,
            report.last_bind_error.as_deref().unwrap_or("none")
        ),
    );
    report
}

async fn shutdown_handle_async(mut handle: ProxyHandle) -> ProxyStopReport {
    let started = Instant::now();
    let listener_id = handle.listener_id;
    let addr = handle.addr;
    let app_pid = std::process::id();
    codex_app_transfer_proxy::proxy_telemetry().logs.add(
        "INFO",
        format!(
            "[proxy-lifecycle-r39] stop_requested listener_id={listener_id} app_pid={app_pid} addr={addr}"
        ),
    );

    if let Some(tx) = handle.shutdown_tx.take() {
        let _ = tx.send(());
    }

    let mut forced = false;
    let mut server_stopped = wait_stopped_async(&mut handle.stopped_rx, PROXY_GRACEFUL_STOP_TIMEOUT).await;
    if !server_stopped {
        forced = true;
        codex_app_transfer_proxy::proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[proxy-lifecycle-r39] graceful_timeout listener_id={listener_id} action=abort_server"
            ),
        );
        handle.abort_handle.abort();
        server_stopped = wait_stopped_async(&mut handle.stopped_rx, PROXY_FORCE_STOP_TIMEOUT).await;
    }

    let mut error = join_server_thread_if_stopped(&mut handle, server_stopped);
    let (port_released, last_bind_error) = wait_port_release_async(addr).await;
    if !port_released && error.is_none() {
        error = Some("listener thread stopped but Windows bind probe still reports the port busy".to_owned());
    }

    let report = ProxyStopReport {
        was_running: true,
        listener_id: Some(listener_id),
        addr: Some(addr.to_string()),
        graceful: server_stopped && !forced,
        forced,
        server_stopped,
        port_released,
        elapsed_ms: elapsed_ms(started),
        last_bind_error,
        error,
    };
    let level = if report.port_released { "INFO" } else { "ERROR" };
    codex_app_transfer_proxy::proxy_telemetry().logs.add(
        level,
        format!(
            "[proxy-lifecycle-r39] port_release_verified={} listener_id={listener_id} app_pid={app_pid} addr={addr} graceful={} forced={} server_stopped={} elapsed_ms={} last_bind_error={}",
            report.port_released,
            report.graceful,
            report.forced,
            report.server_stopped,
            report.elapsed_ms,
            report.last_bind_error.as_deref().unwrap_or("none")
        ),
    );
    report
}

impl ProxyManager {
    pub fn new() -> Self {
        Self::default()
    }

    fn set_fault(&self, code: &str, message: impl Into<String>) {
        let mut fault = self.last_fault.lock().unwrap();
        *fault = Some(ProxyLifecycleFault {
            code: code.to_owned(),
            message: message.into(),
        });
    }

    fn clear_fault(&self) {
        *self.last_fault.lock().unwrap() = None;
    }

    fn fault_snapshot(&self) -> (Option<String>, Option<String>) {
        let fault = self.last_fault.lock().unwrap();
        match fault.as_ref() {
            Some(fault) => (Some(fault.code.clone()), Some(fault.message.clone())),
            None => (None, None),
        }
    }

    async fn wait_for_start_to_finish(&self) -> bool {
        let deadline = Instant::now() + PROXY_START_FINISH_TIMEOUT;
        while self.starting.load(Ordering::Acquire) {
            if Instant::now() >= deadline {
                return false;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        true
    }

    fn wait_for_start_to_finish_sync(&self) -> bool {
        let deadline = Instant::now() + PROXY_START_FINISH_TIMEOUT;
        while self.starting.load(Ordering::Acquire) {
            if Instant::now() >= deadline {
                return false;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        true
    }

    /// Start the local proxy on `127.0.0.1:<port>`. The listener is owned by a
    /// dedicated runtime thread. Shutdown is signalled explicitly and the runtime
    /// never crosses into the Tauri runtime as an owned value.
    pub async fn start(&self, port: u16) -> Result<ProxyStatus, String> {
        if self.stopping.load(Ordering::Acquire) {
            return Err("proxy lifecycle busy: stop is still in progress".to_owned());
        }
        if self.starting.swap(true, Ordering::AcqRel) {
            return Err("proxy lifecycle busy: another start is already in progress".to_owned());
        }
        let _starting_reset = AtomicFlagReset(&self.starting);

        // If a previous server thread ended unexpectedly, remove its stale manager
        // handle and verify the OS port before creating a replacement.
        let stale = {
            let mut guard = self.handle.lock().unwrap();
            match guard.as_ref() {
                Some(handle) if !handle.thread_finished() => {
                    return Ok(self.status_from_handle(handle));
                }
                Some(_) => guard.take(),
                None => None,
            }
        };
        if let Some(stale) = stale {
            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                "WARN",
                format!(
                    "[proxy-lifecycle-r39] dead_server_handle listener_id={} addr={} action=verified_cleanup",
                    stale.listener_id, stale.addr
                ),
            );
            let report = shutdown_handle_async(stale).await;
            if !report.port_released {
                let message = format!(
                    "previous proxy thread ended but {} is still busy after verified cleanup: {}",
                    report.addr.as_deref().unwrap_or("configured port"),
                    report.last_bind_error.as_deref().unwrap_or("unknown bind error")
                );
                self.set_fault("proxy_port_not_released", &message);
                return Err(message);
            }
        }

        let snapshot = load_resolver_snapshot()?;
        let listener_id = PROXY_LISTENER_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let app_pid = std::process::id();
        let (ready_tx, ready_rx) = oneshot::channel::<Result<ProxyBootstrapReady, String>>();
        let (stopped_tx, stopped_rx) = oneshot::channel::<()>();
        let resolver = Arc::new(snapshot.resolver);

        let thread = std::thread::Builder::new()
            .name(format!("cas-proxy-runtime-{listener_id}-{port}"))
            .spawn(move || {
                let rt = match tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .worker_threads(2)
                    .thread_name("cas-proxy")
                    .build()
                {
                    Ok(rt) => rt,
                    Err(error) => {
                        let _ = ready_tx.send(Err(format!("create proxy runtime failed: {error}")));
                        let _ = stopped_tx.send(());
                        return;
                    }
                };

                rt.block_on(async move {
                    let listener = match tokio::net::TcpListener::bind(format!("127.0.0.1:{port}")).await {
                        Ok(listener) => listener,
                        Err(error) => {
                            let _ = ready_tx.send(Err(format!(
                                "bind 127.0.0.1:{port} failed: {error}"
                            )));
                            return;
                        }
                    };
                    let addr = match listener.local_addr() {
                        Ok(addr) => addr,
                        Err(error) => {
                            let _ = ready_tx.send(Err(format!(
                                "cannot read listener address: {error}"
                            )));
                            return;
                        }
                    };
                    let router = build_router_with_relogin_and_mcp_auth(
                        resolver,
                        Arc::new(crate::codex_real_account::mark_relogin_required_from_proxy),
                        Arc::new(|| {
                            crate::codex_real_account::active_chatgpt_mcp_relay_auth().map(
                                |(access_token, account_id)| ChatgptMcpRelayAuth {
                                    access_token,
                                    account_id,
                                },
                            )
                        }),
                    );
                    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
                    let server = tokio::spawn(async move {
                        let _ = axum::serve(listener, router.into_make_service())
                            .with_graceful_shutdown(async move {
                                let _ = shutdown_rx.await;
                            })
                            .await;
                    });
                    let abort_handle = server.abort_handle();
                    codex_app_transfer_proxy::proxy_telemetry().logs.add(
                        "INFO",
                        format!(
                            "[proxy-lifecycle-r39] listener_created listener_id={listener_id} app_pid={app_pid} addr={addr}"
                        ),
                    );

                    let ready = ProxyBootstrapReady {
                        addr,
                        shutdown_tx,
                        abort_handle,
                    };
                    if let Err(unsent) = ready_tx.send(Ok(ready)) {
                        if let Ok(orphan) = unsent {
                            let _ = orphan.shutdown_tx.send(());
                            orphan.abort_handle.abort();
                        }
                    }

                    match server.await {
                        Ok(()) => {
                            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                                "INFO",
                                format!(
                                    "[proxy-lifecycle-r39] server_task_exited listener_id={listener_id} app_pid={app_pid}"
                                ),
                            );
                        }
                        Err(error) if error.is_cancelled() => {
                            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                                "WARN",
                                format!(
                                    "[proxy-lifecycle-r39] server_task_aborted listener_id={listener_id} app_pid={app_pid}"
                                ),
                            );
                        }
                        Err(error) => {
                            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                                "ERROR",
                                format!(
                                    "[proxy-lifecycle-r39] server_task_failed listener_id={listener_id} app_pid={app_pid} error={error}"
                                ),
                            );
                        }
                    }
                });

                // Consume the runtime on its own OS thread. A bounded timeout is only
                // the final fallback after the server future has exited/been aborted;
                // it is never used as the listener lifecycle signal itself.
                rt.shutdown_timeout(PROXY_RUNTIME_SHUTDOWN_TIMEOUT);
                let _ = stopped_tx.send(());
            })
            .map_err(|error| format!("spawn proxy runtime thread failed: {error}"))?;

        let ready = match ready_rx.await {
            Ok(Ok(ready)) => ready,
            Ok(Err(message)) => {
                if address_in_use_message(&message) {
                    self.set_fault("proxy_port_in_use", &message);
                } else {
                    self.set_fault("proxy_start_failed", &message);
                }
                if thread.is_finished() {
                    let _ = thread.join();
                }
                return Err(message);
            }
            Err(_) => {
                let message = "proxy bootstrap channel closed".to_owned();
                self.set_fault("proxy_start_failed", &message);
                if thread.is_finished() {
                    let _ = thread.join();
                }
                return Err(message);
            }
        };

        let new_handle = ProxyHandle {
            addr: ready.addr,
            listener_id,
            shutdown_tx: Some(ready.shutdown_tx),
            abort_handle: ready.abort_handle,
            stopped_rx,
            thread: Some(thread),
            gateway_auth: snapshot.gateway_auth,
            provider_count: snapshot.provider_count,
            active_provider: snapshot.active_provider.clone(),
        };
        let status = self.status_from_handle(&new_handle);
        let mut pending = Some(new_handle);
        {
            let mut guard = self.handle.lock().unwrap();
            if guard.is_none() {
                *guard = pending.take();
            }
        }
        if let Some(orphan) = pending {
            let report = shutdown_handle_async(orphan).await;
            let message = format!(
                "proxy already started by another path; duplicate listener cleanup released_port={} listener_id={}",
                report.port_released,
                report.listener_id.unwrap_or_default()
            );
            self.set_fault("proxy_duplicate_start", &message);
            return Err(message);
        }
        self.clear_fault();
        Ok(status)
    }

    fn status_from_handle(&self, handle: &ProxyHandle) -> ProxyStatus {
        let (last_error_code, last_error) = self.fault_snapshot();
        ProxyStatus {
            running: !handle.thread_finished(),
            addr: (!handle.thread_finished()).then(|| handle.addr.to_string()),
            gateway_auth: handle.gateway_auth,
            provider_count: handle.provider_count,
            active_provider: handle.active_provider.clone(),
            listener_id: Some(handle.listener_id),
            app_pid: std::process::id(),
            last_error_code,
            last_error,
        }
    }

    fn flush_session_cache(&self) {
        let (total, failed) =
            codex_app_transfer_adapters::responses::session::global_response_session_cache()
                .flush_to_persistent();
        if total > 0 {
            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                "INFO",
                format!("session cache flush before stop: {total} entries, {failed} failed"),
            );
        }
    }

    /// Synchronous bounded stop for tray/app-exit paths.
    pub fn stop_verified(&self) -> ProxyStopReport {
        self.flush_session_cache();
        if !self.wait_for_start_to_finish_sync() {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        let handle = self.handle.lock().unwrap().take();
        let Some(handle) = handle else {
            return ProxyStopReport::not_running();
        };
        let report = shutdown_handle_sync(handle);
        if report.port_released {
            self.clear_fault();
        } else {
            self.set_fault(
                "proxy_port_not_released",
                format!(
                    "{} remained busy after proxy shutdown: {}",
                    report.addr.as_deref().unwrap_or("proxy port"),
                    report.last_bind_error.as_deref().unwrap_or("unknown bind error")
                ),
            );
        }
        report
    }

    /// Async bounded stop for HTTP/recovery paths. No fixed sleeps: the caller
    /// receives a report only after server completion/force-abort and bind probing.
    pub async fn stop_verified_async(&self) -> ProxyStopReport {
        self.flush_session_cache();
        if !self.wait_for_start_to_finish().await {
            let report = ProxyStopReport::busy("proxy start did not finish before shutdown deadline");
            self.set_fault("proxy_lifecycle_busy", report.error.clone().unwrap_or_default());
            return report;
        }
        if self.stopping.swap(true, Ordering::AcqRel) {
            return ProxyStopReport::busy("proxy stop is already in progress");
        }
        let _stopping_reset = AtomicFlagReset(&self.stopping);
        let handle = self.handle.lock().unwrap().take();
        let Some(handle) = handle else {
            return ProxyStopReport::not_running();
        };
        let report = shutdown_handle_async(handle).await;
        if report.port_released {
            self.clear_fault();
        } else {
            self.set_fault(
                "proxy_port_not_released",
                format!(
                    "{} remained busy after proxy shutdown: {}",
                    report.addr.as_deref().unwrap_or("proxy port"),
                    report.last_bind_error.as_deref().unwrap_or("unknown bind error")
                ),
            );
        }
        report
    }

    #[allow(dead_code)]
    pub fn stop(&self) -> Result<(), String> {
        let report = self.stop_verified();
        if !report.was_running {
            return Err(report.error.unwrap_or_else(|| "proxy is not running".to_owned()));
        }
        if report.port_released {
            Ok(())
        } else {
            Err(report.error.unwrap_or_else(|| "proxy port was not released".to_owned()))
        }
    }

    /// App-exit best effort still uses the exact same bounded lifecycle barrier.
    pub fn stop_silent(&self) -> ProxyStopReport {
        let report = self.stop_verified();
        if report.was_running && !report.port_released {
            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                "ERROR",
                format!(
                    "[proxy-lifecycle-r39] exit_cleanup_incomplete listener_id={} addr={} error={}",
                    report.listener_id.unwrap_or_default(),
                    report.addr.as_deref().unwrap_or("unknown"),
                    report.error.as_deref().unwrap_or("unknown")
                ),
            );
        }
        report
    }

    pub fn status(&self) -> ProxyStatus {
        let guard = self.handle.lock().unwrap();
        if let Some(handle) = guard.as_ref() {
            return self.status_from_handle(handle);
        }
        let (last_error_code, last_error) = self.fault_snapshot();
        ProxyStatus {
            running: false,
            addr: None,
            gateway_auth: false,
            provider_count: 0,
            active_provider: None,
            listener_id: None,
            app_pid: std::process::id(),
            last_error_code,
            last_error,
        }
    }
}
'''
    body = body[:start] + lifecycle + body[end:]

    body = replace_once(
        body,
        "    pub active_provider: Option<String>,\n}",
        "    pub active_provider: Option<String>,\n"
        "    // CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n"
        "    pub listener_id: Option<u64>,\n"
        "    pub app_pid: u32,\n"
        "    pub last_error_code: Option<String>,\n"
        "    pub last_error: Option<String>,\n"
        "}",
        "proxy status diagnostics",
    )

    # Add focused lifecycle regression tests without changing the existing security tests.
    body += r'''

#[cfg(test)]
mod lifecycle_r39_tests {
    use super::*;
    use axum::{body::Body, extract::Request, response::Response, routing::any, Router};
    use serde_json::json;
    use tokio::net::TcpListener;

    use crate::admin::handlers::common::test_support::with_isolated_home;
    use crate::admin::registry_io::save_for_test as save_registry;

    async fn spawn_upstream() -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let router = Router::new().fallback(any(|_req: Request| async move {
                Response::builder().status(200).body(Body::from("{}")).unwrap()
            }));
            let _ = axum::serve(listener, router.into_make_service()).await;
        });
        addr
    }

    fn save_minimal_config(upstream: SocketAddr, proxy_port: u16) {
        save_registry(&json!({
            "version": "2.1.15",
            "activeProvider": "p1",
            "gatewayApiKey": "cas_r39_test_key",
            "providers": [{
                "id": "p1",
                "name": "Provider One",
                "baseUrl": format!("http://{upstream}"),
                "authScheme": "bearer",
                "apiFormat": "openai_chat",
                "apiKey": "sk-upstream",
                "models": {"default": "model-one"},
                "extraHeaders": {},
                "modelCapabilities": {},
                "requestOptions": {},
                "sortIndex": 0
            }],
            "settings": {
                "theme": "default",
                "language": "zh",
                "proxyPort": proxy_port,
                "adminPort": 18081,
                "autoStart": false,
                "autoApplyOnStart": true,
                "exposeAllProviderModels": false,
                "restoreCodexOnExit": true,
                "updateUrl": codex_app_transfer_registry::DEFAULT_UPDATE_URL
            }
        }))
        .unwrap();
    }

    #[test]
    fn lifecycle_r39_stop_verifies_immediate_rebind() {
        with_isolated_home(|_| {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .unwrap();
            runtime.block_on(async {
                let upstream = spawn_upstream().await;
                let reservation = StdTcpListener::bind("127.0.0.1:0").unwrap();
                let port = reservation.local_addr().unwrap().port();
                drop(reservation);
                save_minimal_config(upstream, port);

                let manager = ProxyManager::new();
                let status = manager.start(port).await.unwrap();
                let expected_addr = format!("127.0.0.1:{port}");
                assert_eq!(status.addr.as_deref(), Some(expected_addr.as_str()));
                let report = manager.stop_verified_async().await;
                assert!(report.server_stopped, "server must stop: {report:?}");
                assert!(report.port_released, "port must be verified free: {report:?}");
                let rebound = StdTcpListener::bind(("127.0.0.1", port));
                assert!(rebound.is_ok(), "same port must be immediately re-bindable: {rebound:?}");
            });
        });
    }

    #[test]
    fn lifecycle_r39_rapid_same_port_restart_loop() {
        with_isolated_home(|_| {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .unwrap();
            runtime.block_on(async {
                let upstream = spawn_upstream().await;
                let reservation = StdTcpListener::bind("127.0.0.1:0").unwrap();
                let port = reservation.local_addr().unwrap().port();
                drop(reservation);
                save_minimal_config(upstream, port);

                let manager = ProxyManager::new();
                for iteration in 0..50 {
                    manager.start(port).await.unwrap_or_else(|error| {
                        panic!("iteration {iteration} start failed: {error}")
                    });
                    let report = manager.stop_verified_async().await;
                    assert!(
                        report.port_released,
                        "iteration {iteration} failed release verification: {report:?}"
                    );
                }
            });
        });
    }

    #[test]
    fn lifecycle_r39_external_listener_is_never_reused_or_killed() {
        with_isolated_home(|_| {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .unwrap();
            runtime.block_on(async {
                let upstream = spawn_upstream().await;
                let external = StdTcpListener::bind("127.0.0.1:0").unwrap();
                let port = external.local_addr().unwrap().port();
                save_minimal_config(upstream, port);

                let manager = ProxyManager::new();
                let error = manager.start(port).await.expect_err("external owner must block bind");
                assert!(address_in_use_message(&error));
                assert!(external.local_addr().is_ok(), "external listener must remain untouched");
                let status = manager.status();
                assert_eq!(status.last_error_code.as_deref(), Some("proxy_port_in_use"));
            });
        });
    }
}
'''
    save(rel, body)


# ---------------------------------------------------------------------------
# Serialized start/reload path: verified stop barrier replaces fixed sleep/retry
# assumptions. A final 10048 is classified as external/stale, not auto-killed.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/handlers/proxy.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "//! `/api/proxy/*` —— 代理生命周期 + 网关密钥 + 端口.\n",
        "//! `/api/proxy/*` —— 代理生命周期 + 网关密钥 + 端口.\n//! CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
        "proxy handler marker",
    )
    body = replace_once(
        body,
        "        manager.stop_silent();\n    }\n\n    const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];",
        r'''        let stop = manager.stop_verified_async().await;
        if !stop.port_released {
            return Err(format!(
                "r39 verified shutdown could not release {} (listener_id={}, server_stopped={}, forced={}): {}",
                stop.addr.as_deref().unwrap_or("proxy port"),
                stop.listener_id.unwrap_or_default(),
                stop.server_stopped,
                stop.forced,
                stop.last_bind_error.as_deref().or(stop.error.as_deref()).unwrap_or("unknown")
            ));
        }
    }

    // Bounded retry remains only for an external race between release verification and
    // bind. It is no longer used as a substitute for waiting for our own listener.
    const RETRY_MS: &[u64] = &[100, 250, 500];''',
        "verified reload stop",
    )
    body = replace_once(
        body,
        '                        "{message}; r28 已避免同端口自重启并按 provider 刷新 resolver，若端口 {port} 仍失败说明此刻确有 listener/Windows socket 占用"\n',
        '                        "{message}; r39 已完成内部 listener 生命周期串行化/释放验证；端口 {port} 仍被占用时按 external_or_stale_listener 处理，不自动 kill、不启用 SO_REUSEADDR"\n',
        "final bind classification",
    )
    body = replace_once(
        body,
        '''pub async fn stop_proxy(State(state): State<AdminState>) -> impl IntoResponse {
    state.proxy_manager.stop_silent();
    proxy_telemetry()
        .logs
        .add("INFO", "forwarding stopped".to_owned());
    Json(json!({"success": true, "running": false})).into_response()
}
''',
        r'''pub async fn stop_proxy(State(state): State<AdminState>) -> impl IntoResponse {
    let report = state.proxy_manager.stop_verified_async().await;
    let success = !report.was_running || report.port_released;
    proxy_telemetry().logs.add(
        if success { "INFO" } else { "ERROR" },
        format!(
            "forwarding stop complete success={success} released={} listener_id={} elapsed_ms={}",
            report.port_released,
            report.listener_id.unwrap_or_default(),
            report.elapsed_ms
        ),
    );
    Json(json!({"success": success, "running": false, "stop": report})).into_response()
}
''',
        "verified manual stop",
    )
    save(rel, body)


# ---------------------------------------------------------------------------
# Safe recovery: distinct in-progress gate, cooldown after completion, no 150ms
# guessed listener sleep, and structured stale-listener diagnosis.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/handlers/chain_health.rs"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "//! CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        "//! CAS-R38-MODEL-ROUTE-OBSERVABILITY\n//! CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "fn recovery_last() -> &'static Mutex<Option<Instant>> {\n    RECOVERY_LAST.get_or_init(|| Mutex::new(None))\n}\n",
        r'''fn recovery_last() -> &'static Mutex<Option<Instant>> {
    RECOVERY_LAST.get_or_init(|| Mutex::new(None))
}

static RECOVERY_ACTIVE_R39: OnceLock<Mutex<()>> = OnceLock::new();

fn recovery_active_r39() -> &'static Mutex<()> {
    RECOVERY_ACTIVE_R39.get_or_init(|| Mutex::new(()))
}
''',
        "recovery active gate",
    )
    body = replace_once(
        body,
        "    after_summary: String,\n}",
        "    after_summary: String,\n    cooldown_ms: u64,\n}",
        "recovery cooldown field",
    )
    body = replace_once(
        body,
        '''pub async fn recover_chain(State(state): State<AdminState>) -> impl IntoResponse {
    {
        let mut gate = recovery_last().lock().await;
        if let Some(previous) = *gate {
            let elapsed = previous.elapsed();
            if elapsed < RECOVERY_COOLDOWN {
                let retry_after_ms = (RECOVERY_COOLDOWN - elapsed).as_millis() as u64;
                return Json(json!({
                    "success": false,
                    "error": "recovery_cooldown",
                    "retryAfterMs": retry_after_ms,
                }));
            }
        }
        *gate = Some(Instant::now());
    }

    let before = build_snapshot(&state).await;
''',
        r'''pub async fn recover_chain(State(state): State<AdminState>) -> impl IntoResponse {
    let _active = match recovery_active_r39().try_lock() {
        Ok(guard) => guard,
        Err(_) => {
            return Json(json!({
                "success": false,
                "error": "recovery_in_progress",
                "message": "已有一次恢复正在执行；不会重复启动/绑定 Transfer",
            }));
        }
    };
    {
        let gate = recovery_last().lock().await;
        if let Some(previous) = *gate {
            let elapsed = previous.elapsed();
            if elapsed < RECOVERY_COOLDOWN {
                let retry_after_ms = (RECOVERY_COOLDOWN - elapsed).as_millis() as u64;
                return Json(json!({
                    "success": false,
                    "error": "recovery_cooldown",
                    "message": format!("上一次恢复已完成，冷却剩余约 {} 秒", (retry_after_ms + 999) / 1000),
                    "retryAfterMs": retry_after_ms,
                }));
            }
        }
    }

    let before = build_snapshot(&state).await;
''',
        "recovery gate semantics",
    )
    body = replace_once(
        body,
        '''    *cache().lock().await = None;
    let after = build_snapshot(&state).await;
    Json(json!({
''',
        '''    *cache().lock().await = None;
    let after = build_snapshot(&state).await;
    *recovery_last().lock().await = Some(Instant::now());
    Json(json!({
''',
        "cooldown begins after recovery",
    )
    body = replace_once(
        body,
        "            after_summary: after.overall_summary.clone(),\n",
        "            after_summary: after.overall_summary.clone(),\n            cooldown_ms: RECOVERY_COOLDOWN.as_millis() as u64,\n",
        "recovery response cooldown",
    )
    body = replace_once(
        body,
        '''    if force_refresh && state.proxy_manager.status().running {
        state.proxy_manager.stop_silent();
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
''',
        r'''    if force_refresh && state.proxy_manager.status().running {
        let stop = state.proxy_manager.stop_verified_async().await;
        if !stop.port_released {
            return RecoveryAction::failed(
                "refresh_transfer",
                format!(
                    "Transfer 停止后端口仍未释放：addr={} listener_id={} server_stopped={} forced={} bind_error={}；已停止继续 bind，保留现场，不自动结束其他进程",
                    stop.addr.as_deref().unwrap_or("unknown"),
                    stop.listener_id.unwrap_or_default(),
                    stop.server_stopped,
                    stop.forced,
                    stop.last_bind_error.as_deref().or(stop.error.as_deref()).unwrap_or("unknown")
                ),
            );
        }
    }
''',
        "verified recovery stop",
    )
    body = replace_once(
        body,
        '''    let transfer = if proxy_status.running {
''',
        '''    let transfer = if proxy_status.running {
''',
        "transfer block anchor",
    )
    body = replace_once(
        body,
        '''    } else {
        HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
            .fact(format!("requests={} failed={}", stats.total, stats.failed))
    };
''',
        r'''    } else if matches!(proxy_status.last_error_code.as_deref(), Some("proxy_port_in_use" | "proxy_port_not_released")) {
        HealthLayer::new(
            "error",
            "transfer_port_in_use",
            "Transfer 未运行，但配置端口仍被占用/未释放",
        )
        .fact(format!("app_pid={}", proxy_status.app_pid))
        .fact(format!("listener_id={}", proxy_status.listener_id.unwrap_or_default()))
        .fact(format!(
            "lifecycle_fault={}",
            proxy_status.last_error.as_deref().unwrap_or("unknown")
        ))
        .fact(format!("requests={} failed={}", stats.total, stats.failed))
    } else {
        HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
            .fact(format!("app_pid={}", proxy_status.app_pid))
            .fact(format!("requests={} failed={}", stats.total, stats.failed))
    };
''',
        "stale listener health layer",
    )
    body = body.replace(
        'if snapshot.transfer.code == "transfer_stopped" {',
        'if matches!(snapshot.transfer.code.as_str(), "transfer_stopped" | "transfer_port_in_use") {',
        1,
    )
    save(rel, body)


# ---------------------------------------------------------------------------
# Frontend: explicit recovery progress/cooldown instead of a button that silently
# re-enables and then surfaces a generic cooldown error on the next click.
# ---------------------------------------------------------------------------
rel = "frontend/src/api/chainHealth.ts"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n// CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "  afterSummary: string\n}",
        "  afterSummary: string\n  cooldownMs: number\n}",
        "frontend recovery cooldown type",
    )
    save(rel, body)

rel = "frontend/src/pages/ProxyPage.vue"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n// CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "import { useToast } from '@/composables/useToast'\n",
        "import { useToast } from '@/composables/useToast'\nimport type { ApiError } from '@/api/http'\n",
        "api error import",
    )
    body = replace_once(
        body,
        "let chainTimer: number | undefined\n",
        "let chainTimer: number | undefined\nlet chainRecoveryCooldownTimer: number | undefined\n",
        "cooldown timer",
    )
    body = replace_once(
        body,
        "const chainRecovery = ref<ChainRecoveryReport | null>(null)\n",
        "const chainRecovery = ref<ChainRecoveryReport | null>(null)\nconst chainRecoveryCooldownSeconds = ref(0)\n",
        "cooldown state",
    )
    old_handler = '''async function onRecoverChain() {
  if (chainRecovering.value) return
  chainRecovering.value = true
  try {
    const result = await recoverChainHealth()
    chainRecovery.value = result.recovery
    chainHealth.value = result.health
    toast(t('chainHealth.recoveryComplete'), 'info')
  } catch (e) {
    toast((e as Error).message || t('chainHealth.recoveryFailed'), 'error')
  } finally {
    chainRecovering.value = false
  }
}
'''
    new_handler = '''function startRecoveryCooldown(ms: number) {
  if (chainRecoveryCooldownTimer) window.clearInterval(chainRecoveryCooldownTimer)
  const deadline = Date.now() + Math.max(0, ms)
  const update = () => {
    chainRecoveryCooldownSeconds.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
    if (chainRecoveryCooldownSeconds.value <= 0 && chainRecoveryCooldownTimer) {
      window.clearInterval(chainRecoveryCooldownTimer)
      chainRecoveryCooldownTimer = undefined
    }
  }
  update()
  if (chainRecoveryCooldownSeconds.value > 0) {
    chainRecoveryCooldownTimer = window.setInterval(update, 250)
  }
}

async function onRecoverChain() {
  if (chainRecovering.value || chainRecoveryCooldownSeconds.value > 0) return
  chainRecovering.value = true
  try {
    const result = await recoverChainHealth()
    chainRecovery.value = result.recovery
    chainHealth.value = result.health
    startRecoveryCooldown(result.recovery.cooldownMs)
    toast(t('chainHealth.recoveryComplete'), 'info')
  } catch (e) {
    const apiError = e as ApiError
    const response = (apiError.responseData || {}) as { error?: string; retryAfterMs?: number }
    if (response.retryAfterMs && response.retryAfterMs > 0) {
      startRecoveryCooldown(response.retryAfterMs)
    }
    if (response.error === 'recovery_in_progress') {
      toast(t('chainHealth.recoveryInProgress'), 'info')
    } else {
      toast(apiError.message || t('chainHealth.recoveryFailed'), 'error')
    }
  } finally {
    chainRecovering.value = false
  }
}
'''
    body = replace_once(body, old_handler, new_handler, "recovery progress handler")
    body = replace_once(
        body,
        "  if (chainTimer) clearInterval(chainTimer)\n",
        "  if (chainTimer) clearInterval(chainTimer)\n  if (chainRecoveryCooldownTimer) clearInterval(chainRecoveryCooldownTimer)\n",
        "cooldown unmount cleanup",
    )
    body = replace_once(
        body,
        ':disabled="chainRecovering"\n            @click="onRecoverChain"',
        ':disabled="chainRecovering || chainRecoveryCooldownSeconds > 0"\n            @click="onRecoverChain"',
        "recovery button disable",
    )
    body = replace_once(
        body,
        "            {{ t('chainHealth.recover') }}\n",
        "            {{ chainRecovering ? t('chainHealth.recovering') : chainRecoveryCooldownSeconds > 0 ? `${t('chainHealth.recoveryCooldown')} ${chainRecoveryCooldownSeconds}s` : t('chainHealth.recover') }}\n",
        "recovery button state label",
    )
    save(rel, body)

for rel, translations in {
    "frontend/src/i18n/zh.ts": {
        "chainHealth.recovering": "正在恢复…",
        "chainHealth.recoveryCooldown": "恢复冷却",
        "chainHealth.recoveryInProgress": "已有一次恢复正在执行，请等待当前恢复完成",
    },
    "frontend/src/i18n/en.ts": {
        "chainHealth.recovering": "Recovering…",
        "chainHealth.recoveryCooldown": "Recovery cooldown",
        "chainHealth.recoveryInProgress": "A recovery is already running; wait for it to finish",
    },
}.items():
    body = load(rel)
    if MARKER not in body:
        lines = [f'  "{key}": {value!r},' for key, value in translations.items()]
        marker_anchor = "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n" if "// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n" in body else "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n"
        body = replace_once(
            body,
            marker_anchor,
            marker_anchor + "// CAS-R39-PROXY-LIFECYCLE-RELIABILITY\n",
            f"{rel} marker",
        )
        anchor = "  'chainHealth.recover': '尝试恢复',\n" if rel.endswith("zh.ts") else "  'chainHealth.recover': 'Try recovery',\n"
        body = replace_once(body, anchor, anchor + "\n".join(lines) + "\n", f"{rel} recovery labels")
        save(rel, body)

print("r39 proxy lifecycle reliability: COMPLETE")
