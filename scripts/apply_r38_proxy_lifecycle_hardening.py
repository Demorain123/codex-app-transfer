from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R38-PROXY-LIFECYCLE-HARDENING"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 proxy lifecycle hardening: already applied")
    raise SystemExit(0)

split_marker = "struct ResolverSnapshot {"
if split_marker not in body:
    raise SystemExit("r38 proxy lifecycle hardening: proxy_runner.rs shape changed (ResolverSnapshot missing)")

_, suffix = body.split(split_marker, 1)

prefix = r'''//! 内嵌 axum 代理生命周期管理。
//!
//! CAS-R38-PROXY-LIFECYCLE-HARDENING
//! r38 不再把 `Runtime::shutdown_background()` 当成同步 listener-close barrier。
//! 每个 proxy generation 都有显式 graceful-shutdown signal + server-done ack；stop
//! 在返回前做 bounded teardown + port-release verification。并用 start guard + stop epoch
//! 防 concurrent start / exit-during-bootstrap 把一个无人管理的 listener 发布出来。

use std::net::{SocketAddr, TcpListener as StdTcpListener};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
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
    /// 当前生效的 gateway 鉴权状态。代理启动边界会自动生成缺失的
    /// gateway_api_key,所以 running 时必须为 `true`。
    pub gateway_auth: bool,
    pub provider_count: usize,
    pub active_provider: Option<String>,
}

struct ProxyHandle {
    addr: SocketAddr,
    runtime: tokio::runtime::Runtime,
    shutdown_tx: Option<oneshot::Sender<()>>,
    server_done_rx: std::sync::mpsc::Receiver<()>,
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
        .add(level, format!("[proxy-lifecycle-r38] {}", message.into()));
}

fn wait_until_port_bindable(addr: SocketAddr, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match StdTcpListener::bind(addr) {
            Ok(listener) => {
                drop(listener);
                return true;
            }
            Err(_) if Instant::now() < deadline => std::thread::sleep(PORT_RELEASE_POLL),
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

    let signal_sent = h.shutdown_tx.take().map(|tx| tx.send(()).is_ok()).unwrap_or(false);
    lifecycle_log(
        "INFO",
        format!(
            "graceful_signal_sent listener_id={} app_pid={} sent={signal_sent}",
            h.listener_id, pid
        ),
    );

    let server_done = h.server_done_rx.recv_timeout(GRACEFUL_SERVER_WAIT).is_ok();
    lifecycle_log(
        if server_done { "INFO" } else { "WARN" },
        format!(
            "{} listener_id={} app_pid={} grace_ms={}",
            if server_done { "server_done" } else { "server_done_timeout" },
            h.listener_id,
            pid,
            GRACEFUL_SERVER_WAIT.as_millis()
        ),
    );

    // Even after a graceful signal, bound the fallback. Unlike r37's
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

    let released = wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT);
    lifecycle_log(
        if released { "INFO" } else { "ERROR" },
        format!(
            "{} listener_id={} app_pid={} addr={} wait_ms={}",
            if released { "port_release_verified" } else { "stale_listener_detected" },
            h.listener_id,
            pid,
            h.addr,
            PORT_RELEASE_WAIT.as_millis()
        ),
    );
    released
}

impl ProxyManager {
    pub fn new() -> Self {
        Self::default()
    }

    /// 启动代理监听 `127.0.0.1:<port>`。已 running 时沿用旧版语义返回当前状态。
    pub async fn start(&self, port: u16) -> Result<ProxyStatus, String> {
        // Fast path: already-published generation is the only state that may be reused.
        {
            let guard = self.handle.lock().unwrap();
            if let Some(h) = guard.as_ref() {
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
        }

        if self.start_in_progress.swap(true, Ordering::AcqRel) {
            lifecycle_log(
                "WARN",
                format!("duplicate_start_rejected app_pid={} requested_port={port}", std::process::id()),
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

        let (addr_tx, addr_rx) = oneshot::channel::<
            Result<
                (
                    SocketAddr,
                    tokio::runtime::Runtime,
                    oneshot::Sender<()>,
                    std::sync::mpsc::Receiver<()>,
                ),
                String,
            >,
        >();
        let resolver = Arc::new(snapshot.resolver);
        std::thread::Builder::new()
            .name(format!("cas-proxy-bootstrap-{port}"))
            .spawn(move || {
                let rt = match tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .worker_threads(2)
                    .thread_name("cas-proxy")
                    .build()
                {
                    Ok(rt) => rt,
                    Err(e) => {
                        let _ = addr_tx.send(Err(format!("create proxy runtime failed: {e}")));
                        return;
                    }
                };

                let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
                let (server_done_tx, server_done_rx) = std::sync::mpsc::channel::<()>();
                let bind_result = rt.block_on(async {
                    let listener = tokio::net::TcpListener::bind(format!("127.0.0.1:{port}"))
                        .await
                        .map_err(|e| format!("bind 127.0.0.1:{port} failed: {e}"))?;
                    let addr = listener
                        .local_addr()
                        .map_err(|e| format!("cannot read listener address: {e}"))?;

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

                    rt.spawn(async move {
                        let _ = axum::serve(listener, router.into_make_service())
                            .with_graceful_shutdown(async move {
                                let _ = shutdown_rx.await;
                            })
                            .await;
                        let _ = server_done_tx.send(());
                    });
                    Ok::<SocketAddr, String>(addr)
                });

                match bind_result {
                    Ok(addr) => {
                        let _ = addr_tx.send(Ok((addr, rt, shutdown_tx, server_done_rx)));
                    }
                    Err(e) => {
                        rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                        let _ = addr_tx.send(Err(e));
                    }
                }
            })
            .map_err(|e| format!("spawn proxy thread failed: {e}"))?;

        let (addr, runtime, shutdown_tx, server_done_rx) = addr_rx
            .await
            .map_err(|_| "proxy bootstrap channel closed".to_owned())??;

        lifecycle_log(
            "INFO",
            format!(
                "listener_bound listener_id={listener_id} app_pid={} requested_port={port} actual_addr={addr}",
                std::process::id()
            ),
        );

        let new_handle = ProxyHandle {
            addr,
            runtime,
            shutdown_tx: Some(shutdown_tx),
            server_done_rx,
            listener_id,
            gateway_auth: snapshot.gateway_auth,
            provider_count: snapshot.provider_count,
            active_provider: snapshot.active_provider.clone(),
        };

        // A stop/exit may happen while the bootstrap thread is binding. Never publish a
        // generation created before that stop boundary.
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
                    Err("proxy stopped but listener port did not become bindable in time".to_owned())
                }
            }
            None => Err("proxy is not running".to_owned()),
        }
    }

    /// 静默 stop: tray Quit / RunEvent::Exit / recovery 路径均可重复调用。
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
                format!("stop_silent_no_handle app_pid={} stop_epoch={}", std::process::id(), self.stop_epoch.load(Ordering::Acquire)),
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

new_body = prefix + split_marker + suffix
PATH.write_text(new_body, encoding="utf-8")

check = PATH.read_text(encoding="utf-8")
required = [
    MARKER,
    "with_graceful_shutdown",
    "server_done_timeout",
    "port_release_verified",
    "stale_listener_detected",
    "duplicate_start_rejected",
    "bootstrap_cancelled_by_stop",
    "shutdown_timeout(RUNTIME_FORCE_WAIT)",
]
for token in required:
    if token not in check:
        raise SystemExit(f"r38 proxy lifecycle hardening missing marker: {token}")
if "shutdown_background() 一键 abort" in check:
    raise SystemExit("r38 proxy lifecycle hardening: stale r37 shutdown_background assumption survived")

print("r38 proxy lifecycle hardening: applied")
