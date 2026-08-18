from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R39-PROXY-OWNER-THREAD"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r39 proxy owner-thread lifecycle: already applied")
    raise SystemExit(0)

split_marker = "struct ResolverSnapshot {"
if split_marker not in body:
    raise SystemExit("r39 proxy owner-thread: ResolverSnapshot boundary missing")
_, suffix = body.split(split_marker, 1)

prefix = r'''//! 内嵌 axum 代理生命周期管理。
//!
//! CAS-R39-PROXY-OWNER-THREAD
//! r39 把 TcpListener、axum server future 与 Tokio Runtime 固定到同一个专用 OS owner
//! thread。ProxyManager 只保存 shutdown sender + JoinHandle；stop 必须等 owner thread join
//! 完成，再做同端口 bind probe。这样不再把 Runtime 跨线程带回 UI/async handler，也不需要
//! 在另一个 Tokio runtime 里调用 shutdown_background() 作为伪 teardown barrier。

use std::net::{SocketAddr, TcpListener as StdTcpListener};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use codex_app_transfer_proxy::{
    build_router_with_relogin_and_mcp_auth, ChatgptMcpRelayAuth, StaticResolver,
};
use codex_app_transfer_registry::{config_file, Config};
use serde::Serialize;
use tokio::sync::oneshot;

use crate::admin::handlers::proxy::ensure_gateway_key;
use crate::admin::registry_io::{with_config_write, ConfigMutation};

const GRACEFUL_SERVER_WAIT: Duration = Duration::from_millis(1500);
const RUNTIME_FORCE_WAIT: Duration = Duration::from_millis(750);
const PORT_RELEASE_WAIT: Duration = Duration::from_millis(1500);
const PORT_RELEASE_POLL: Duration = Duration::from_millis(25);

#[derive(Debug, Serialize, Clone)]
pub struct ProxyStatus {
    pub running: bool,
    pub addr: Option<String>,
    pub gateway_auth: bool,
    pub provider_count: usize,
    pub active_provider: Option<String>,
}

struct ProxyHandle {
    addr: SocketAddr,
    shutdown_tx: Option<oneshot::Sender<()>>,
    owner_thread: Option<JoinHandle<()>>,
    listener_id: u64,
    gateway_auth: bool,
    provider_count: usize,
    active_provider: Option<String>,
}

#[derive(Default)]
pub struct ProxyManager {
    handle: Mutex<Option<ProxyHandle>>,
    start_in_progress: AtomicBool,
    stop_epoch: AtomicU64,
    next_listener_id: AtomicU64,
}

struct StartInProgressGuard<'a> {
    flag: &'a AtomicBool,
}

impl Drop for StartInProgressGuard<'_> {
    fn drop(&mut self) {
        self.flag.store(false, Ordering::Release);
    }
}

fn lifecycle_log(level: &str, message: impl Into<String>) {
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, format!("[proxy-lifecycle-r39] {}", message.into()));
}

fn port_owner_evidence(port: u16) -> String {
    #[cfg(target_os = "windows")]
    {
        return crate::windows_tcp_owner::listener_owner_evidence(port);
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = port;
        "owner_probe=windows_only".to_owned()
    }
}

fn wait_until_port_bindable(addr: SocketAddr, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match StdTcpListener::bind(addr) {
            Ok(listener) => {
                drop(listener);
                return true;
            }
            Err(_) if Instant::now() < deadline => thread::sleep(PORT_RELEASE_POLL),
            Err(_) => return false,
        }
    }
}

fn shutdown_proxy_handle(mut h: ProxyHandle, reason: &str) -> bool {
    let pid = std::process::id();
    lifecycle_log(
        "INFO",
        format!(
            "stop_requested listener_id={} app_pid={} addr={} reason={reason}",
            h.listener_id, pid, h.addr
        ),
    );

    let signal_sent = h
        .shutdown_tx
        .take()
        .map(|tx| tx.send(()).is_ok())
        .unwrap_or(false);
    lifecycle_log(
        "INFO",
        format!(
            "graceful_signal_sent listener_id={} app_pid={} sent={signal_sent}",
            h.listener_id, pid
        ),
    );

    let join_started = Instant::now();
    let joined_cleanly = h
        .owner_thread
        .take()
        .map(|owner| owner.join().is_ok())
        .unwrap_or(true);
    lifecycle_log(
        if joined_cleanly { "INFO" } else { "ERROR" },
        format!(
            "owner_thread_joined listener_id={} app_pid={} clean={} elapsed_ms={}",
            h.listener_id,
            pid,
            joined_cleanly,
            join_started.elapsed().as_millis()
        ),
    );

    let released = wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT);
    let binder_evidence = if released {
        "binder_pid=<none>".to_owned()
    } else {
        port_owner_evidence(h.addr.port()).replace("owner_", "binder_")
    };
    lifecycle_log(
        if released { "INFO" } else { "ERROR" },
        format!(
            "{} listener_id={} app_pid={} addr={} wait_ms={} {}",
            if released { "port_release_verified" } else { "listener_residue_detected" },
            h.listener_id,
            pid,
            h.addr,
            PORT_RELEASE_WAIT.as_millis(),
            binder_evidence
        ),
    );
    joined_cleanly && released
}

impl ProxyManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn start(&self, port: u16) -> Result<ProxyStatus, String> {
        let running_port = {
            let guard = self.handle.lock().unwrap();
            if let Some(h) = guard.as_ref() {
                if h.addr.port() == port {
                    lifecycle_log(
                        "INFO",
                        format!(
                            "reuse_listener listener_id={} app_pid={} requested_port={} actual_addr={}",
                            h.listener_id,
                            std::process::id(),
                            port,
                            h.addr
                        ),
                    );
                    return Ok(ProxyStatus {
                        running: true,
                        addr: Some(h.addr.to_string()),
                        gateway_auth: h.gateway_auth,
                        provider_count: h.provider_count,
                        active_provider: h.active_provider.clone(),
                    });
                }
                Some(h.addr.port())
            } else {
                None
            }
        };
        if let Some(old_port) = running_port {
            lifecycle_log(
                "INFO",
                format!(
                    "port_switch_requested app_pid={} old_port={old_port} requested_port={port}",
                    std::process::id()
                ),
            );
            self.stop()
                .map_err(|e| format!("cannot switch proxy port {old_port} -> {port}: {e}"))?;
        }

        if self.start_in_progress.swap(true, Ordering::AcqRel) {
            lifecycle_log(
                "WARN",
                format!(
                    "duplicate_start_rejected app_pid={} requested_port={port}",
                    std::process::id()
                ),
            );
            return Err("proxy start already in progress".to_owned());
        }
        let _start_guard = StartInProgressGuard {
            flag: &self.start_in_progress,
        };

        let start_stop_epoch = self.stop_epoch.load(Ordering::Acquire);
        let listener_id = self.next_listener_id.fetch_add(1, Ordering::AcqRel) + 1;
        lifecycle_log(
            "INFO",
            format!(
                "start_requested listener_id={listener_id} app_pid={} requested_port={port} stop_epoch={start_stop_epoch}",
                std::process::id()
            ),
        );

        let snapshot = load_resolver_snapshot()?;
        let resolver = Arc::new(snapshot.resolver);
        let (ready_tx, ready_rx) = oneshot::channel::<Result<SocketAddr, String>>();
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

        let owner_thread = thread::Builder::new()
            .name(format!("cas-proxy-owner-{listener_id}-{port}"))
            .spawn(move || {
                let owner_tid = format!("{:?}", thread::current().id());
                lifecycle_log(
                    "INFO",
                    format!(
                        "owner_thread_started listener_id={listener_id} app_pid={} owner_tid={owner_tid} requested_port={port}",
                        std::process::id()
                    ),
                );

                let rt = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(rt) => rt,
                    Err(e) => {
                        let _ = ready_tx.send(Err(format!("create proxy owner runtime failed: {e}")));
                        lifecycle_log(
                            "ERROR",
                            format!(
                                "owner_runtime_create_failed listener_id={listener_id} app_pid={} error={e}",
                                std::process::id()
                            ),
                        );
                        return;
                    }
                };

                let listener = match rt.block_on(tokio::net::TcpListener::bind(format!(
                    "127.0.0.1:{port}"
                ))) {
                    Ok(listener) => listener,
                    Err(e) => {
                        let evidence = port_owner_evidence(port);
                        lifecycle_log(
                            "ERROR",
                            format!(
                                "bind_failed listener_id={listener_id} app_pid={} requested_port={port} os_error={:?} {evidence}",
                                std::process::id(),
                                e.raw_os_error(),
                            ),
                        );
                        let _ = ready_tx.send(Err(format!(
                            "bind 127.0.0.1:{port} failed: {e}; {evidence}"
                        )));
                        rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                        lifecycle_log(
                            "INFO",
                            format!(
                                "owner_thread_exit listener_id={listener_id} app_pid={} reason=bind_failed",
                                std::process::id()
                            ),
                        );
                        return;
                    }
                };

                let addr = match listener.local_addr() {
                    Ok(addr) => addr,
                    Err(e) => {
                        let _ = ready_tx.send(Err(format!(
                            "cannot read proxy listener address: {e}"
                        )));
                        drop(listener);
                        rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
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

                if ready_tx.send(Ok(addr)).is_err() {
                    lifecycle_log(
                        "WARN",
                        format!(
                            "startup_receiver_gone listener_id={listener_id} app_pid={} addr={addr}",
                            std::process::id()
                        ),
                    );
                    drop(listener);
                    rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                    return;
                }

                lifecycle_log(
                    "INFO",
                    format!(
                        "listener_owned listener_id={listener_id} app_pid={} owner_tid={owner_tid} addr={addr}",
                        std::process::id()
                    ),
                );

                let (shutdown_seen_tx, shutdown_seen_rx) = oneshot::channel::<()>();
                let shutdown_signal = async move {
                    let _ = shutdown_rx.await;
                    lifecycle_log(
                        "INFO",
                        format!(
                            "shutdown_signal_received listener_id={listener_id} app_pid={} owner_tid={owner_tid}",
                            std::process::id()
                        ),
                    );
                    let _ = shutdown_seen_tx.send(());
                };
                let server = axum::serve(listener, router.into_make_service())
                    .with_graceful_shutdown(shutdown_signal);
                let server_future = std::future::IntoFuture::into_future(server);

                let server_outcome = rt.block_on(async move {
                    tokio::pin!(server_future);
                    let watchdog = async move {
                        let _ = shutdown_seen_rx.await;
                        tokio::time::sleep(GRACEFUL_SERVER_WAIT).await;
                    };
                    tokio::pin!(watchdog);

                    tokio::select! {
                        result = &mut server_future => {
                            lifecycle_log(
                                "INFO",
                                format!(
                                    "server_future_complete listener_id={listener_id} app_pid={} result_ok={}",
                                    std::process::id(),
                                    result.is_ok()
                                ),
                            );
                            true
                        }
                        _ = &mut watchdog => {
                            lifecycle_log(
                                "WARN",
                                format!(
                                    "server_grace_timeout listener_id={listener_id} app_pid={} grace_ms={}",
                                    std::process::id(),
                                    GRACEFUL_SERVER_WAIT.as_millis()
                                ),
                            );
                            false
                        }
                    }
                });

                lifecycle_log(
                    "INFO",
                    format!(
                        "server_future_dropped listener_id={listener_id} app_pid={} graceful={server_outcome}",
                        std::process::id()
                    ),
                );
                rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                lifecycle_log(
                    "INFO",
                    format!(
                        "owner_runtime_shutdown_complete listener_id={listener_id} app_pid={} timeout_ms={}",
                        std::process::id(),
                        RUNTIME_FORCE_WAIT.as_millis()
                    ),
                );
                lifecycle_log(
                    "INFO",
                    format!(
                        "owner_thread_exit listener_id={listener_id} app_pid={} reason=normal_teardown",
                        std::process::id()
                    ),
                );
            })
            .map_err(|e| format!("spawn proxy owner thread failed: {e}"))?;

        let addr = match ready_rx.await {
            Ok(Ok(addr)) => addr,
            Ok(Err(error)) => {
                let _ = owner_thread.join();
                return Err(error);
            }
            Err(_) => {
                let _ = owner_thread.join();
                return Err("proxy owner thread closed before startup acknowledgement".to_owned());
            }
        };

        lifecycle_log(
            "INFO",
            format!(
                "listener_bound listener_id={listener_id} app_pid={} requested_port={port} actual_addr={addr}",
                std::process::id()
            ),
        );

        let new_handle = ProxyHandle {
            addr,
            shutdown_tx: Some(shutdown_tx),
            owner_thread: Some(owner_thread),
            listener_id,
            gateway_auth: snapshot.gateway_auth,
            provider_count: snapshot.provider_count,
            active_provider: snapshot.active_provider.clone(),
        };

        if self.stop_epoch.load(Ordering::Acquire) != start_stop_epoch {
            lifecycle_log(
                "WARN",
                format!(
                    "bootstrap_cancelled_by_stop listener_id={listener_id} app_pid={} start_epoch={start_stop_epoch} current_epoch={}",
                    std::process::id(),
                    self.stop_epoch.load(Ordering::Acquire)
                ),
            );
            let _ = shutdown_proxy_handle(new_handle, "bootstrap_cancelled_by_stop");
            return Err("proxy start cancelled by concurrent stop/exit".to_owned());
        }

        let mut guard = self.handle.lock().unwrap();
        if guard.is_some() {
            drop(guard);
            let _ = shutdown_proxy_handle(new_handle, "publish_collision");
            return Err("proxy already started by another path".to_owned());
        }
        *guard = Some(new_handle);
        lifecycle_log(
            "INFO",
            format!(
                "listener_published listener_id={listener_id} app_pid={} actual_addr={addr}",
                std::process::id()
            ),
        );

        Ok(ProxyStatus {
            running: true,
            addr: Some(addr.to_string()),
            gateway_auth: snapshot.gateway_auth,
            provider_count: snapshot.provider_count,
            active_provider: snapshot.active_provider,
        })
    }

    #[allow(dead_code)]
    pub fn stop(&self) -> Result<(), String> {
        self.stop_epoch.fetch_add(1, Ordering::AcqRel);
        let handle = self.handle.lock().unwrap().take();
        match handle {
            Some(h) => {
                if shutdown_proxy_handle(h, "explicit_stop") {
                    Ok(())
                } else {
                    Err(
                        "proxy owner thread stopped, but the same listener port did not become bindable"
                            .to_owned(),
                    )
                }
            }
            None => Err("proxy is not running".to_owned()),
        }
    }

    pub fn stop_silent(&self) {
        self.stop_epoch.fetch_add(1, Ordering::AcqRel);

        let (total, failed) =
            codex_app_transfer_adapters::responses::session::global_response_session_cache()
                .flush_to_persistent();
        if total > 0 {
            codex_app_transfer_proxy::proxy_telemetry().logs.add(
                "INFO",
                format!("session cache flush before stop: {total} entries, {failed} failed"),
            );
        }

        let handle = self.handle.lock().unwrap().take();
        if let Some(h) = handle {
            let _ = shutdown_proxy_handle(h, "stop_silent");
        } else {
            lifecycle_log(
                "INFO",
                format!(
                    "stop_silent_no_handle app_pid={} stop_epoch={}",
                    std::process::id(),
                    self.stop_epoch.load(Ordering::Acquire)
                ),
            );
        }
    }

    pub fn status(&self) -> ProxyStatus {
        let guard = self.handle.lock().unwrap();
        match guard.as_ref() {
            Some(h) => ProxyStatus {
                running: true,
                addr: Some(h.addr.to_string()),
                gateway_auth: h.gateway_auth,
                provider_count: h.provider_count,
                active_provider: h.active_provider.clone(),
            },
            None => ProxyStatus {
                running: false,
                addr: None,
                gateway_auth: false,
                provider_count: 0,
                active_provider: None,
            },
        }
    }
}

'''

PATH.write_text(prefix + split_marker + suffix, encoding="utf-8")

check = PATH.read_text(encoding="utf-8")
required = [
    MARKER,
    "cas-proxy-owner-",
    "owner_thread_joined",
    "shutdown_signal_received",
    "server_grace_timeout",
    "owner_runtime_shutdown_complete",
    "port_release_verified",
    "listener_residue_detected",
    "duplicate_start_rejected",
    "bootstrap_cancelled_by_stop",
]
for token in required:
    if token not in check:
        raise SystemExit(f"r39 proxy owner-thread missing marker: {token}")

prefix_check = check.split(split_marker, 1)[0]
for forbidden in (
    "runtime: tokio::runtime::Runtime",
    "inside_async_runtime",
    '"background_async_safe"',
):
    if forbidden in prefix_check:
        raise SystemExit(f"r39 proxy owner-thread retained forbidden ownership pattern: {forbidden}")

print("r39 proxy owner-thread lifecycle: applied")
