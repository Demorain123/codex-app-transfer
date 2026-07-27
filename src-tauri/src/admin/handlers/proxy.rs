//! `/api/proxy/*` —— 代理生命周期 + 网关密钥 + 端口.

use std::fs;

use axum::{extract::State, http::StatusCode, response::IntoResponse, Json};
use codex_app_transfer_proxy::{proxy_log_dir, proxy_telemetry};
use codex_app_transfer_registry::RawConfig;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::proxy_runner::ProxyManager;

use super::super::registry_io::load as load_registry;
use super::super::state::AdminState;
use super::common::{err, generate_gateway_key_value, open_directory};

pub(crate) fn read_proxy_port(cfg: &RawConfig) -> u16 {
    cfg.get("settings")
        .and_then(|s| s.get("proxyPort"))
        .and_then(|v| v.as_u64())
        .and_then(|p| u16::try_from(p).ok())
        .unwrap_or(18080)
}

/// 读 `settings.codexNetworkAccess`,默认 `false`(MOC-185:full access 全权限有风险,缺省关;
/// 老用户已显式设过的 bool 值照旧,不覆盖)。
pub(crate) fn read_codex_network_access(cfg: &RawConfig) -> bool {
    cfg.get("settings")
        .and_then(|s| s.get("codexNetworkAccess"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

pub(crate) fn read_gateway_key(cfg: &RawConfig) -> String {
    cfg.get("gatewayApiKey")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_owned()
}

pub(crate) fn ensure_gateway_key(cfg: &mut RawConfig) -> Result<String, String> {
    let existing = read_gateway_key(cfg);
    if !existing.trim().is_empty() {
        return Ok(existing);
    }
    let gateway_key = generate_gateway_key_value()?;
    cfg.as_object_mut()
        .unwrap()
        .insert("gatewayApiKey".into(), Value::String(gateway_key.clone()));
    Ok(gateway_key)
}

// CAS-PROXY-LIFECYCLE-R27
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

// CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH
async fn start_proxy_r28_inner(
    manager: &ProxyManager,
    port: u16,
    expected_provider: Option<&str>,
) -> Result<bool, String> {
    let _lifecycle = PROXY_LIFECYCLE_R27.lock().await;
    let status = manager.status();
    let current_port = proxy_status_port(status.addr.as_deref());
    let provider_matches = expected_provider
        .map(|expected| status.active_provider.as_deref() == Some(expected))
        .unwrap_or(true);

    if status.running {
        // r27 same-port reuse remains valid only when the resolver snapshot also
        // belongs to the requested provider. Port 0 still means any bound port.
        if (port == 0 || current_port == Some(port)) && provider_matches {
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[proxy-lifecycle-r28] reuse listener requested_port={port} actual_port={} provider={}",
                    current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned()),
                    status.active_provider.as_deref().unwrap_or("none")
                ),
            );
            return Ok(false);
        }
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[proxy-lifecycle-r28] reload listener old_port={} new_port={port} old_provider={} new_provider={}",
                current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned()),
                status.active_provider.as_deref().unwrap_or("none"),
                expected_provider.unwrap_or("unchanged")
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
                        "[proxy-lifecycle-r28] bind busy requested_port={port} retry={} delay_ms={delay}",
                        attempt + 1
                    ),
                );
                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
            }
            Err(message) => {
                return Err(if proxy_bind_address_in_use(&message) {
                    format!(
                        "{message}; r28 已避免同端口自重启并按 provider 刷新 resolver，若端口 {port} 仍失败说明此刻确有 listener/Windows socket 占用"
                    )
                } else {
                    message
                });
            }
        }
    }
    unreachable!("bounded proxy start retry loop always returns")
}

pub(crate) async fn start_proxy_if_needed(
    manager: &ProxyManager,
    port: u16,
) -> Result<bool, String> {
    start_proxy_r28_inner(manager, port, None).await
}

pub(crate) async fn start_proxy_for_provider_if_needed(
    manager: &ProxyManager,
    port: u16,
    expected_provider: &str,
) -> Result<bool, String> {
    start_proxy_r28_inner(manager, port, Some(expected_provider)).await
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
        assert!(proxy_bind_address_in_use(
            "Address already in use (os error 98)"
        ));
        assert!(!proxy_bind_address_in_use("permission denied"));
    }
}

// ── /api/proxy/* ─────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct StartProxyInput {
    pub port: Option<u16>,
}

pub async fn start_proxy(
    State(state): State<AdminState>,
    body: Option<Json<StartProxyInput>>,
) -> impl IntoResponse {
    let port = body
        .and_then(|b| b.0.port)
        .or_else(|| load_registry().ok().map(|cfg| read_proxy_port(&cfg)))
        .unwrap_or(18080);
    // CAS-PROXY-LIFECYCLE-R27-START-HANDLER: route the manual UI button through
    // the same serialized/reuse-aware lifecycle path as desktop sync and A/B launch.
    match start_proxy_if_needed(&state.proxy_manager, port).await {
        Ok(_) => {
            let s = state.proxy_manager.status();
            let actual_port = s
                .addr
                .as_ref()
                .and_then(|a| a.split(':').last().and_then(|p| p.parse::<u16>().ok()))
                .unwrap_or(port);
            proxy_telemetry()
                .logs
                .add("INFO", format!("forwarding started :{actual_port}"));
            Json(json!({
                "success": true,
                "running": s.running,
                "port": actual_port,
            }))
            .into_response()
        }
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    }
}

pub async fn stop_proxy(State(state): State<AdminState>) -> impl IntoResponse {
    state.proxy_manager.stop_silent();
    proxy_telemetry()
        .logs
        .add("INFO", "forwarding stopped".to_owned());
    Json(json!({"success": true, "running": false})).into_response()
}

pub async fn proxy_status(State(state): State<AdminState>) -> impl IntoResponse {
    let s = state.proxy_manager.status();
    let cfg = load_registry().unwrap_or_else(|_| json!({}));
    let port = s
        .addr
        .as_ref()
        .and_then(|a| a.split(':').last().and_then(|p| p.parse::<u16>().ok()))
        .unwrap_or_else(|| read_proxy_port(&cfg));
    Json(json!({
        "running": s.running,
        "port": port,
        "stats": proxy_telemetry().stats.snapshot(),
        "hybridDirectMode": crate::admin::services::desktop::hybrid_direct::enabled_from_config(&cfg),
    }))
    .into_response()
}

/// GET /api/system-proxy/status —— MOC-114 系统代理(梯子)连通性探测。
///
/// 注意:这跟 [`proxy_status`] 是两回事 —— `proxy_status` 报的是 transfer **本地转发
/// 进程**(127.0.0.1,恒可达);本接口报的是**系统代理(科学上网梯子)**是否挂 + 端口
/// 是否可连。relay 真账号模式的 chatgpt backend 透传与第三方路由都依赖后者,前端据此
/// 显示「网络代理:已连接/未连接」并 gate plugins 解锁。只探代理端口、不碰 chatgpt.com。
pub async fn system_proxy_status() -> impl IntoResponse {
    let st = crate::system_proxy::probe().await;
    Json(json!({ "success": true, "systemProxy": st })).into_response()
}

pub async fn proxy_logs() -> impl IntoResponse {
    Json(json!({"logs": proxy_telemetry().logs.get_all()})).into_response()
}

pub async fn proxy_logs_clear() -> impl IntoResponse {
    proxy_telemetry().logs.clear();
    Json(json!({"success": true})).into_response()
}

pub async fn proxy_logs_open_dir() -> impl IntoResponse {
    let Some(path) = proxy_log_dir() else {
        return err(
            StatusCode::INTERNAL_SERVER_ERROR,
            "cannot locate log directory",
        )
        .into_response();
    };
    if let Err(e) = fs::create_dir_all(&path) {
        return err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("create log directory failed: {e}"),
        )
        .into_response();
    }
    match open_directory(&path) {
        Ok(_) => Json(json!({"success": true, "path": path.to_string_lossy()})).into_response(),
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    }
}
