use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::admin::handlers::common::err;
use crate::admin::services::desktop::{no_micro, snapshot};
use crate::admin::AdminState;

static AB_RUN_SEQ: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Default, Deserialize)]
pub struct LaunchQuery {
    mode: Option<String>,
}

fn next_ab_run_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    let seq = AB_RUN_SEQ.fetch_add(1, Ordering::Relaxed);
    format!("{millis}-{seq}")
}

fn ab_log(level: &str, run_id: &str, mode: &str, phase: &str, extra: Option<&str>) {
    let mut message = format!("[codex-ab] run_id={run_id} mode={mode} phase={phase}");
    if let Some(extra) = extra.filter(|v| !v.is_empty()) {
        message.push(' ');
        message.push_str(extra);
    }
    // Write through proxy telemetry deliberately: this is the same LogBuffer that persists
    // proxy-YYYY-MM-DD.log, so A/B markers and the traffic being compared share one timeline.
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, message);
}

/// Prepare a *shared* Transfer-managed runtime for both A and B.
///
/// The app's normal startup auto-apply is intentionally asynchronous; the UI can become clickable
/// before that background task has finished writing ~/.codex/config.toml and binding the local
/// proxy. Launching Codex in that window can therefore produce Windows `os error 10061` against a
/// just-written localhost base_url. A/B must not inherit that race.
///
/// Re-applying the active provider here is deliberate: both A and B get the exact same current
/// Transfer-managed Codex config and a confirmed live proxy. The experiment then varies only the
/// process launch path (Micro loaded vs No Micro injection). This is not a pristine/non-Transfer
/// control; the UI says so explicitly.
async fn prepare_ab_environment(state: &AdminState, run_id: &str, mode: &str) -> Result<(), String> {
    ab_log(
        "INFO",
        run_id,
        mode,
        "environment_prepare",
        Some("config_scope=transfer-managed"),
    );

    let sync = snapshot::sync_desktop_for_active_provider(state).await;
    if sync.get("attempted").and_then(Value::as_bool) == Some(true)
        && sync.get("success").and_then(Value::as_bool) != Some(true)
    {
        let message = sync
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("Codex desktop sync failed")
            .to_owned();
        ab_log(
            "ERROR",
            run_id,
            mode,
            "environment_failed",
            Some(&format!("reason=desktop_sync error={message}")),
        );
        return Err(message);
    }

    // Every current provider target is local_proxy (MOC-234). Treat a non-running proxy after a
    // successful sync as a hard A/B preflight failure rather than launching Codex into a dead port.
    let proxy = state.proxy_manager.status();
    if !proxy.running || !proxy.gateway_auth {
        let message = format!(
            "A/B 环境未就绪：Transfer 本地代理未正常监听或 gateway auth 未就绪 (running={}, gateway_auth={})",
            proxy.running, proxy.gateway_auth
        );
        ab_log(
            "ERROR",
            run_id,
            mode,
            "environment_failed",
            Some("reason=proxy_not_ready"),
        );
        return Err(message);
    }

    let addr = proxy.addr.as_deref().unwrap_or("unknown");
    ab_log(
        "INFO",
        run_id,
        mode,
        "environment_ready",
        Some(&format!("config_scope=transfer-managed proxy={addr}")),
    );
    Ok(())
}

/// GET /api/desktop/no-micro/doctor
///
/// 只读检查 Windows AppX / ChatGPT.exe / bundled Node / app.asar 目标模块与
/// 当前进程状态。不会启动 Codex、不会修改 AppX/config/auth/session。
pub async fn doctor() -> Response {
    match tokio::task::spawn_blocking(no_micro::doctor).await {
        Ok(report) => Json(report).into_response(),
        Err(e) => err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("No Micro doctor task failed: {e}"),
        )
        .into_response(),
    }
}

/// A/B 对照的 A 路径。要求 Codex 已完全退出；先用与 B 相同的当前 Transfer-managed
/// provider/config + live proxy 做共享 preflight，再直接用官方 Windows MSIX
/// ActivateApplication 空参数启动，不执行 No Micro/CDP 注入。
#[cfg(target_os = "windows")]
async fn launch_normal(state: &AdminState, run_id: &str) -> Response {
    let report = match tokio::task::spawn_blocking(no_micro::doctor).await {
        Ok(report) => report,
        Err(e) => {
            return err(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("No Micro doctor task failed: {e}"),
            )
            .into_response()
        }
    };
    if !report.package_found || report.executable_path.is_none() {
        return err(StatusCode::CONFLICT, "未找到可用于 A/B 标准启动的 Codex Desktop").into_response();
    }
    if report.process_state != "not-running" {
        return err(
            StatusCode::CONFLICT,
            "Codex 仍在运行或进程状态无法可靠确认。请先完全退出 Codex，再开始 A/B 标准启动。",
        )
        .into_response();
    }

    if let Err(message) = prepare_ab_environment(state, run_id, "normal").await {
        return err(StatusCode::CONFLICT, message).into_response();
    }

    ab_log("INFO", run_id, "normal", "launch_requested", None);
    let launched = tokio::task::spawn_blocking(|| -> Result<u32, String> {
        // Recheck immediately before activation. This path never kills an existing process: a race
        // is surfaced instead of silently changing the A control run.
        let report = no_micro::doctor();
        if report.process_state != "not-running" {
            return Err("Codex started during A/B preflight; refusing to alter the running instance".to_owned());
        }
        let aumid = crate::windows_msix::resolve_codex_aumid()
            .ok_or_else(|| "无法解析 OpenAI.Codex AUMID".to_owned())?;
        crate::windows_msix::activate_packaged_app(&aumid, "")
    })
    .await;
    match launched {
        Ok(Ok(pid)) => {
            ab_log(
                "INFO",
                run_id,
                "normal",
                "launch_success",
                Some(&format!("pid={pid}")),
            );
            Json(json!({
                "success": true,
                "abRunId": run_id,
                "mode": "normal",
                "configScope": "transfer-managed",
                "processId": pid
            }))
            .into_response()
        }
        Ok(Err(message)) => {
            ab_log("ERROR", run_id, "normal", "launch_failed", Some(&format!("error={message}")));
            err(StatusCode::CONFLICT, message).into_response()
        }
        Err(e) => {
            let message = format!("Normal A/B launch task failed: {e}");
            ab_log("ERROR", run_id, "normal", "launch_task_failed", Some(&format!("error={message}")));
            err(StatusCode::INTERNAL_SERVER_ERROR, message).into_response()
        }
    }
}

#[cfg(not(target_os = "windows"))]
async fn launch_normal(_state: &AdminState, _run_id: &str) -> Response {
    err(StatusCode::NOT_IMPLEMENTED, "A/B 标准启动目前仅支持 Windows").into_response()
}

/// POST /api/desktop/no-micro/launch[?mode=normal]
///
/// 两条 A/B 路径先使用同一个 Transfer-managed config/proxy preflight：
/// - `mode=normal`：标准 Electron/MSIX 启动，Micro 正常加载；
/// - 默认 / `mode=no-micro`：同样配置下执行 No Micro 注入。
/// 稳定 `[codex-ab]` marker 写进同一份 proxy-YYYY-MM-DD.log。
pub async fn launch(
    State(state): State<AdminState>,
    Query(query): Query<LaunchQuery>,
) -> Response {
    let mode = match query.mode.as_deref() {
        Some("normal") => "normal",
        None | Some("no-micro") => "no-micro",
        Some(other) => {
            return err(
                StatusCode::BAD_REQUEST,
                format!("unsupported A/B launch mode: {other}"),
            )
            .into_response()
        }
    };

    let run_id = next_ab_run_id();
    if mode == "normal" {
        return launch_normal(&state, &run_id).await;
    }

    let report = match tokio::task::spawn_blocking(no_micro::doctor).await {
        Ok(report) => report,
        Err(e) => {
            return err(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("No Micro doctor task failed: {e}"),
            )
            .into_response()
        }
    };
    if !report.launch_ready {
        return err(
            StatusCode::CONFLICT,
            "No Micro B 当前不满足 launch-ready 条件；请先完全退出 Codex 并重新兼容性检查。",
        )
        .into_response();
    }

    if let Err(message) = prepare_ab_environment(&state, &run_id, "no-micro").await {
        return err(StatusCode::CONFLICT, message).into_response();
    }

    ab_log("INFO", &run_id, "no-micro", "launch_requested", None);
    match tokio::task::spawn_blocking(no_micro::launch).await {
        Ok(Ok(mut result)) => {
            let pid = result
                .pointer("/launch/processId")
                .and_then(Value::as_u64)
                .map(|v| v.to_string())
                .unwrap_or_else(|| "unknown".to_owned());
            ab_log(
                "INFO",
                &run_id,
                "no-micro",
                "injection_success",
                Some(&format!("pid={pid}")),
            );
            if let Some(obj) = result.as_object_mut() {
                obj.insert("abRunId".to_owned(), Value::String(run_id.clone()));
                obj.insert("mode".to_owned(), Value::String("no-micro".to_owned()));
                obj.insert(
                    "configScope".to_owned(),
                    Value::String("transfer-managed".to_owned()),
                );
            }
            Json(result).into_response()
        }
        Ok(Err(message)) => {
            ab_log(
                "ERROR",
                &run_id,
                "no-micro",
                "launch_failed",
                Some(&format!("error={message}")),
            );
            err(StatusCode::CONFLICT, message).into_response()
        }
        Err(e) => {
            let message = format!("No Micro launch task failed: {e}");
            ab_log(
                "ERROR",
                &run_id,
                "no-micro",
                "launch_task_failed",
                Some(&format!("error={message}")),
            );
            err(StatusCode::INTERNAL_SERVER_ERROR, message).into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ab_run_ids_are_distinct() {
        assert_ne!(next_ab_run_id(), next_ab_run_id());
    }
}
