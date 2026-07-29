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
use crate::admin::handlers::desktop as desktop_handler;
use crate::admin::services::desktop::{no_micro, process};
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

// CAS-NO-MICRO-R23-AB-SHARED-PIPELINE
// CAS-NO-LAGGING-R32-AB-MODE
/// Wrap the exact legacy Restart config/provider preparation with deterministic A/B markers.
async fn prepare_ab_environment(
    state: &AdminState,
    run_id: &str,
    mode: &str,
) -> Result<Value, String> {
    ab_log(
        "INFO",
        run_id,
        mode,
        "environment_prepare",
        Some("pipeline=legacy-restart-shared"),
    );
    match desktop_handler::prepare_codex_restart_runtime(state).await {
        Ok(desktop_sync) => {
            ab_log(
                "INFO",
                run_id,
                mode,
                "environment_ready",
                Some("pipeline=legacy-restart-shared"),
            );
            Ok(desktop_sync)
        }
        Err(message) => {
            ab_log(
                "ERROR",
                run_id,
                mode,
                "environment_failed",
                Some(&format!("pipeline=legacy-restart-shared error={message}")),
            );
            Err(message)
        }
    }
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
            format!("No Lagging doctor task failed: {e}"),
        )
        .into_response(),
    }
}

/// A/B 对照的 A 路径：完全复用已知正常的 legacy Restart pipeline。
/// 唯一新增行为是稳定 `[codex-ab]` marker；Micro 正常加载。
#[cfg(target_os = "windows")]
async fn launch_normal(state: &AdminState, run_id: &str) -> Response {
    let desktop_sync = match prepare_ab_environment(state, run_id, "normal").await {
        Ok(value) => value,
        Err(message) => return err(StatusCode::CONFLICT, message).into_response(),
    };

    ab_log(
        "INFO",
        run_id,
        "normal",
        "launch_requested",
        Some("pipeline=legacy-restart"),
    );
    match process::launch_codex_app_restart(std::env::consts::OS) {
        Ok(()) => {
            desktop_handler::reinject_after_codex_restart().await;
            ab_log(
                "INFO",
                run_id,
                "normal",
                "launch_success",
                Some("pipeline=legacy-restart"),
            );
            Json(json!({
                "success": true,
                "abRunId": run_id,
                "mode": "normal",
                "configScope": "legacy-restart-shared",
                "desktopSync": desktop_sync,
            }))
            .into_response()
        }
        Err(message) => {
            ab_log(
                "ERROR",
                run_id,
                "normal",
                "launch_failed",
                Some(&format!("pipeline=legacy-restart error={message}")),
            );
            err(StatusCode::CONFLICT, message).into_response()
        }
    }
}

#[cfg(not(target_os = "windows"))]
async fn launch_normal(_state: &AdminState, _run_id: &str) -> Response {
    err(
        StatusCode::NOT_IMPLEMENTED,
        "A/B 标准启动目前仅支持 Windows",
    )
    .into_response()
}

/// POST /api/desktop/no-micro/launch[?mode=normal]
///
/// 两条 A/B 路径先使用同一个 Transfer-managed config/proxy preflight：
/// - `mode=normal`：标准 Electron/MSIX 启动，Micro 正常加载；
/// - 默认 / `mode=no-micro`：同样配置下执行 No Micro 注入。
/// 稳定 `[codex-ab]` marker 写进同一份 proxy-YYYY-MM-DD.log。
pub async fn launch(State(state): State<AdminState>, Query(query): Query<LaunchQuery>) -> Response {
    let mode = match query.mode.as_deref() {
        Some("normal") => "normal",
        None | Some("no-micro") | Some("no-lagging") => "no-lagging",
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
                format!("No Lagging doctor task failed: {e}"),
            )
            .into_response()
        }
    };
    // Compatibility is checked before touching the runtime, but running Codex is allowed:
    // the shared legacy restart primitive will close/reap it safely before No Micro launches.
    if !report.compatible {
        return err(
            StatusCode::CONFLICT,
            report
                .warnings
                .first()
                .cloned()
                .unwrap_or_else(|| "No Lagging B 当前未通过兼容性检查".to_owned()),
        )
        .into_response();
    }

    if let Err(message) = prepare_ab_environment(&state, &run_id, "no-lagging").await {
        return err(StatusCode::CONFLICT, message).into_response();
    }

    ab_log(
        "INFO",
        &run_id,
        "no-lagging",
        "launch_requested",
        Some("pipeline=legacy-restart-shared final_launcher=no-lagging"),
    );
    match process::launch_codex_app_restart_with(std::env::consts::OS, || {
        let extra_args = process::prepare_codex_alternate_launch_args();
        no_micro::launch_with_args(&extra_args)
    }) {
        Ok(mut result) => {
            desktop_handler::reinject_after_codex_restart().await;
            let pid = result
                .pointer("/launch/processId")
                .and_then(Value::as_u64)
                .map(|v| v.to_string())
                .unwrap_or_else(|| "unknown".to_owned());
            ab_log(
                "INFO",
                &run_id,
                "no-lagging",
                "injection_success",
                Some(&format!("pid={pid} pipeline=legacy-restart-shared")),
            );
            if let Some(obj) = result.as_object_mut() {
                obj.insert("abRunId".to_owned(), Value::String(run_id.clone()));
                obj.insert("mode".to_owned(), Value::String("no-lagging".to_owned()));
                obj.insert(
                    "configScope".to_owned(),
                    Value::String("legacy-restart-shared".to_owned()),
                );
            }
            Json(result).into_response()
        }
        Err(message) => {
            ab_log(
                "ERROR",
                &run_id,
                "no-lagging",
                "launch_failed",
                Some(&format!("pipeline=legacy-restart-shared error={message}")),
            );
            err(StatusCode::CONFLICT, message).into_response()
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
