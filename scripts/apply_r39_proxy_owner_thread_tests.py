from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R39-PROXY-OWNER-THREAD-TESTS"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r39 proxy owner-thread tests: already applied")
    raise SystemExit(0)

tests = r'''

#[cfg(test)]
mod proxy_lifecycle_r39_tests {
    // CAS-R39-PROXY-OWNER-THREAD-TESTS
    use super::*;

    fn reserve_addr() -> SocketAddr {
        let listener = StdTcpListener::bind("127.0.0.1:0").expect("reserve r39 test port");
        let addr = listener.local_addr().expect("r39 test addr");
        drop(listener);
        addr
    }

    #[test]
    fn proxy_lifecycle_r39_owner_thread_join_rebind_100_generations() {
        let addr = reserve_addr();
        for generation in 0..100u64 {
            let (ready_tx, ready_rx) = std::sync::mpsc::sync_channel::<()>(1);
            let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
            let owner = std::thread::Builder::new()
                .name(format!("r39-test-owner-{generation}"))
                .spawn(move || {
                    let rt = tokio::runtime::Builder::new_current_thread()
                        .enable_all()
                        .build()
                        .expect("r39 owner runtime");
                    let listener = rt.block_on(tokio::net::TcpListener::bind(addr))
                        .unwrap_or_else(|e| panic!("generation {generation} bind failed: {e}"));
                    let router = axum::Router::new()
                        .route("/", axum::routing::get(|| async { "ok" }));
                    ready_tx.send(()).expect("signal r39 ready");
                    rt.block_on(async move {
                        axum::serve(listener, router.into_make_service())
                            .with_graceful_shutdown(async move {
                                let _ = shutdown_rx.await;
                            })
                            .await
                            .expect("r39 test server");
                    });
                    rt.shutdown_timeout(Duration::from_secs(1));
                })
                .expect("spawn r39 owner test thread");

            ready_rx.recv_timeout(Duration::from_secs(2))
                .unwrap_or_else(|_| panic!("generation {generation} did not become ready"));
            shutdown_tx.send(()).expect("signal r39 shutdown");
            owner.join()
                .unwrap_or_else(|_| panic!("generation {generation} owner thread panicked"));
            assert!(
                wait_until_port_bindable(addr, Duration::from_secs(1)),
                "generation {generation} did not release the same port after owner join"
            );
        }
    }

    #[test]
    fn proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier() {
        let addr = reserve_addr();
        let listener = StdTcpListener::bind(addr).expect("bind barrier fixture");
        let owner = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(50));
            drop(listener);
        });
        assert!(
            !wait_until_port_bindable(addr, Duration::from_millis(20)),
            "port must remain busy before the owner drops its listener"
        );
        owner.join().expect("barrier fixture owner join");
        assert!(wait_until_port_bindable(addr, Duration::from_secs(1)));
    }
}
'''

PATH.write_text(body + tests, encoding="utf-8")

for token in (
    MARKER,
    "proxy_lifecycle_r39_owner_thread_join_rebind_100_generations",
    "proxy_lifecycle_r39_owner_thread_is_the_teardown_barrier",
    "0..100u64",
):
    if token not in (body + tests):
        raise SystemExit(f"r39 owner-thread stress marker missing: {token}")

print("r39 proxy owner-thread tests: applied")
