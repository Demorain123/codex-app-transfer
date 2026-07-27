from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/proxy.rs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


text = TARGET.read_text(encoding="utf-8")

# CAS-PROXY-LIFECYCLE-R27
# The old helper unconditionally stopped an already-running local proxy before every
# desktop sync / A-B launch, then immediately rebound the same Windows port. That can
# turn a healthy in-process listener into WSAEADDRINUSE (10048), especially while the
# previous Tokio runtime/socket is still being torn down. Reuse the live listener when
# it already owns the requested port; only restart when the requested port actually
# changes. Serialize helper callers and add a short bounded retry for genuine teardown
# races. This does not auto-select a different port, so config/Codex routing never drift.
if "CAS-PROXY-LIFECYCLE-R27" not in text:
    old = '''pub(crate) async fn start_proxy_if_needed(
    manager: &ProxyManager,
    port: u16,
) -> Result<bool, String> {
    if manager.status().running {
        manager.stop_silent();
    }
    manager.start(port).await.map(|_| true)
}
'''
    new = '''// CAS-PROXY-LIFECYCLE-R27
static PROXY_LIFECYCLE_R27: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn proxy_status_port(addr: Option<&str>) -> Option<u16> {
    addr.and_then(|value| value.rsplit(':').next())
        .and_then(|value| value.parse::<u16>().ok())
}

fn proxy_bind_address_in_use(message: &str) -> bool {
    let lower = message.to_ascii_lowercase();
    lower.contains("os error 10048")
        || lower.contains("address already in use")
        || lower.contains("only one usage of each socket address")
}

pub(crate) async fn start_proxy_if_needed(
    manager: &ProxyManager,
    port: u16,
) -> Result<bool, String> {
    let _lifecycle = PROXY_LIFECYCLE_R27.lock().await;
    let status = manager.status();
    let current_port = proxy_status_port(status.addr.as_deref());

    if status.running {
        // Requested port 0 means "any OS-assigned port"; an existing healthy listener
        // already satisfies that request. Most importantly, an exact same-port request
        // must be a no-op instead of stop -> immediate rebind.
        if port == 0 || current_port == Some(port) {
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[proxy-lifecycle-r27] reuse running listener requested_port={port} actual_port={}",
                    current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned())
                ),
            );
            return Ok(false);
        }
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[proxy-lifecycle-r27] switch listener old_port={} new_port={port}",
                current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned())
            ),
        );
        manager.stop_silent();
    }

    const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];
    for attempt in 0..=RETRY_MS.len() {
        match manager.start(port).await {
            Ok(_) => return Ok(true),
            Err(message) if proxy_bind_address_in_use(&message) && attempt < RETRY_MS.len() => {
                let delay = RETRY_MS[attempt];
                proxy_telemetry().logs.add(
                    "WARN",
                    format!(
                        "[proxy-lifecycle-r27] bind busy requested_port={port} retry={} delay_ms={delay}",
                        attempt + 1
                    ),
                );
                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
            }
            Err(message) => {
                return Err(if proxy_bind_address_in_use(&message) {
                    format!(
                        "{message}; r27 已避免同端口自重启并重试端口 {port}，若仍失败说明该端口此刻确实仍有 listener/Windows socket 占用"
                    )
                } else {
                    message
                });
            }
        }
    }
    unreachable!("bounded proxy start retry loop always returns")
}

#[cfg(test)]
mod proxy_lifecycle_r27_tests {
    use super::*;

    #[test]
    fn parses_listener_port_without_assuming_fixed_default() {
        assert_eq!(proxy_status_port(Some("127.0.0.1:18082")), Some(18082));
        assert_eq!(proxy_status_port(Some("127.0.0.1:49152")), Some(49152));
        assert_eq!(proxy_status_port(None), None);
    }

    #[test]
    fn recognizes_windows_and_cross_platform_address_in_use_errors() {
        assert!(proxy_bind_address_in_use(
            "bind 127.0.0.1:18082 failed: Only one usage of each socket address (protocol/network address/port) is normally permitted. (os error 10048)"
        ));
        assert!(proxy_bind_address_in_use("Address already in use (os error 98)"));
        assert!(!proxy_bind_address_in_use("permission denied"));
    }
}
'''
    text = replace_once(text, old, new, label="r27 start_proxy_if_needed lifecycle")

if "CAS-PROXY-LIFECYCLE-R27-START-HANDLER" not in text:
    old = '''    match state.proxy_manager.start(port).await {
        Ok(s) => {
            let actual_port = s
                .addr
                .as_ref()
                .and_then(|a| a.split(':').last().and_then(|p| p.parse::<u16>().ok()))
                .unwrap_or(port);
'''
    new = '''    // CAS-PROXY-LIFECYCLE-R27-START-HANDLER: route the manual UI button through
    // the same serialized/reuse-aware lifecycle path as desktop sync and A/B launch.
    match start_proxy_if_needed(&state.proxy_manager, port).await {
        Ok(_) => {
            let s = state.proxy_manager.status();
            let actual_port = s
                .addr
                .as_ref()
                .and_then(|a| a.split(':').last().and_then(|p| p.parse::<u16>().ok()))
                .unwrap_or(port);
'''
    text = replace_once(text, old, new, label="r27 manual start handler")

TARGET.write_text(text, encoding="utf-8")

for marker in (
    "CAS-PROXY-LIFECYCLE-R27",
    "PROXY_LIFECYCLE_R27.lock().await",
    "current_port == Some(port)",
    "CAS-PROXY-LIFECYCLE-R27-START-HANDLER",
    "proxy_lifecycle_r27_tests",
):
    if marker not in text:
        raise SystemExit(f"r27 proxy lifecycle materialization missing marker: {marker}")

print("r27 proxy same-port reuse / serialized restart overlay: complete")
