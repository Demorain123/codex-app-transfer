use axum::{
    extract::Query,
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::admin::handlers::common::err;
use crate::admin::services::desktop::no_micro;

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

/// A/B 对照的 A 路径。要求 Codex 已完全退出，然后直接用官方 Windows MSIX
/// ActivateApplication 拉起当前 Codex，参数为空，不走 No Micro、provider/config sync、
/// CDP 注入或“先杀再重启”路径，尽量让它等价于用户从开始菜单做一次普通启动。
#[cfg(target_os = "windows")]
async fn launch_normal() -> Response {
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
        return err(StatusCode::CONFLICT, "未找到可用于 A/B 普通启动的 Codex Desktop").into_response();
    }
    if report.process_state != "not-running" {
        return err(
            StatusCode::CONFLICT,
            "Codex 仍在运行或进程状态无法可靠确认。请先完全退出 Codex，再开始 A/B 普通启动。",
        )
        .into_response();
    }

    let run_id = next_ab_run_id();
    ab_log("INFO", &run_id, "normal", "launch_requested", None);
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
                &run_id,
                "normal",
                "launch_success",
                Some(&format!("pid={pid}")),
            );
            Json(json!({
                "success": true,
                "abRunId": run_id,
                "mode": "normal",
                "processId": pid
            }))
            .into_response()
        }
        Ok(Err(message)) => {
            ab_log("ERROR", &run_id, "normal", "launch_failed", Some(&format!("error={message}")));
            err(StatusCode::CONFLICT, message).into_response()
        }
        Err(e) => {
            let message = format!("Normal A/B launch task failed: {e}");
            ab_log("ERROR", &run_id, "normal", "launch_task_failed", Some(&format!("error={message}")));
            err(StatusCode::INTERNAL_SERVER_ERROR, message).into_response()
        }
    }
}

#[cfg(not(target_os = "windows"))]
async fn launch_normal() -> Response {
    err(StatusCode::NOT_IMPLEMENTED, "A/B 普通启动目前仅支持 Windows").into_response()
}

/// POST /api/desktop/no-micro/launch[?mode=normal]
///
/// 默认执行 fail-closed 的 No Micro 旁路实验启动；`mode=normal` 则执行 A/B 对照的普通启动。
/// 两条路径都会把稳定的 `[codex-ab]` marker 写进同一份 proxy-YYYY-MM-DD.log。
pub async fn launch(Query(query): Query<LaunchQuery>) -> Response {
    match query.mode.as_deref() {
        Some("normal") => return launch_normal().await,
        None | Some("no-micro") => {}
        Some(other) => {
            return err(
                StatusCode::BAD_REQUEST,
                format!("unsupported A/B launch mode: {other}"),
            )
            .into_response()
        }
    }

    let run_id = next_ab_run_id();
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
