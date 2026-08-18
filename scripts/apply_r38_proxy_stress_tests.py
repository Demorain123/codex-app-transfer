from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R38-PROXY-STRESS-TESTS"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 proxy stress tests: already applied")
    raise SystemExit(0)

# Module name intentionally retains `proxy_lifecycle_r27`: the existing Windows CI already runs
# `cargo test ... proxy_lifecycle_r27`, so r38 stress coverage is exercised without a workflow-only fork.
tests = r'''

#[cfg(test)]
mod proxy_lifecycle_r27_r38_tests {
    // CAS-R38-PROXY-STRESS-TESTS
    use super::*;
    use std::sync::atomic::Ordering;

    fn reserve_test_addr() -> SocketAddr {
        let listener = StdTcpListener::bind("127.0.0.1:0").expect("reserve test port");
        let addr = listener.local_addr().expect("test addr");
        drop(listener);
        addr
    }

    #[test]
    fn proxy_lifecycle_r38_same_port_rebind_50_generations() {
        let addr = reserve_test_addr();
        for generation in 0..50u64 {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .worker_threads(2)
                .build()
                .expect("test runtime");
            let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
            let (done_tx, done_rx) = std::sync::mpsc::channel::<()>();
            rt.block_on(async {
                let listener = tokio::net::TcpListener::bind(addr)
                    .await
                    .unwrap_or_else(|e| panic!("generation {generation} bind failed: {e}"));
                let router = axum::Router::new().route("/", axum::routing::get(|| async { "ok" }));
                rt.spawn(async move {
                    let _ = axum::serve(listener, router.into_make_service())
                        .with_graceful_shutdown(async move {
                            let _ = shutdown_rx.await;
                        })
                        .await;
                    let _ = done_tx.send(());
                });
            });
            shutdown_tx.send(()).expect("send graceful stop");
            done_rx
                .recv_timeout(Duration::from_secs(2))
                .unwrap_or_else(|_| panic!("generation {generation} server did not stop"));
            rt.shutdown_timeout(Duration::from_secs(1));
            assert!(
                wait_until_port_bindable(addr, Duration::from_secs(1)),
                "generation {generation} did not release {addr}"
            );
        }
    }

    #[test]
    fn proxy_lifecycle_r38_external_owner_is_not_bypassed() {
        let listener = StdTcpListener::bind("127.0.0.1:0").expect("occupy test port");
        let addr = listener.local_addr().expect("occupied addr");
        assert!(
            !wait_until_port_bindable(addr, Duration::from_millis(75)),
            "r38 must not treat an occupied port as released"
        );
        drop(listener);
        assert!(wait_until_port_bindable(addr, Duration::from_secs(1)));
    }

    #[tokio::test]
    async fn proxy_lifecycle_r38_duplicate_start_rejected_before_bootstrap() {
        let manager = ProxyManager::new();
        manager.start_in_progress.store(true, Ordering::Release);
        let error = manager.start(18089).await.expect_err("duplicate start must be rejected");
        assert!(error.contains("already in progress"));
        manager.start_in_progress.store(false, Ordering::Release);
    }

    #[test]
    fn proxy_lifecycle_r38_double_silent_stop_is_idempotent() {
        let manager = ProxyManager::new();
        manager.stop_silent();
        manager.stop_silent();
        assert!(!manager.status().running);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn proxy_lifecycle_r38_native_owner_attribution_matches_current_pid() {
        let listener = StdTcpListener::bind("127.0.0.1:0").expect("owner fixture listener");
        let port = listener.local_addr().expect("owner fixture addr").port();
        let mut owner = None;
        for _ in 0..20 {
            owner = crate::windows_tcp_owner::listener_owner(port).expect("owner query");
            if owner.is_some() { break; }
            std::thread::sleep(Duration::from_millis(25));
        }
        let owner = owner.expect("native owner table must contain fixture listener");
        assert_eq!(owner.pid, std::process::id());
        assert!(owner.process_alive);
        drop(listener);
    }
}
'''
body += tests
PATH.write_text(body, encoding="utf-8")

for token in (
    MARKER,
    "proxy_lifecycle_r27_r38_tests",
    "proxy_lifecycle_r38_same_port_rebind_50_generations",
    "proxy_lifecycle_r38_external_owner_is_not_bypassed",
    "proxy_lifecycle_r38_duplicate_start_rejected_before_bootstrap",
    "proxy_lifecycle_r38_double_silent_stop_is_idempotent",
    "proxy_lifecycle_r38_native_owner_attribution_matches_current_pid",
):
    if token not in body:
        raise SystemExit(f"r38 proxy stress test marker missing: {token}")

print("r38 proxy stress tests: applied")
