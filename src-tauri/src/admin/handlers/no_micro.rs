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
use crate::admin::services::desktop::{no_micro, process};

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
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, message);
}

fn spawn_process_exit_marker(run_id: String, mode: &'static str) {
    tokio::spawn(async move {
        // Launch APIs can return before the Windows MSIX process is visible. Wait for it first so
        // a fast initial false does not get misreported as an A/B run that already exited.
        let mut observed = false;
        for _ in 0..60 {
            if process::is_codex_app_running("windows") {
                observed = true;
                ab_log("INFO", &run_id, mode, "process_observed", None);
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }
        if !observed {
            ab_log("WARN", &run_id, mode, "process_not_observed", None);
            return;
        }

        // Keep a single lightweight watcher per controlled A/B run. The hard cap prevents a stale
        // task from living forever if Windows process enumeration becomes permanently ambiguous.
        for _ in 0..43_200 {
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            if !process::is_codex_app_running("windows") {
                ab_log("INFO", &run_id, mode, "process_exit", None);
                return;
            }
        }
        ab_log("WARN", &run_id, mode, "watch_timeout", None);
    });
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

/// A/B 对照的 A 路径。复用现有 `/api/desktop/no-micro/launch?mode=normal`，避免再扩一条
/// admin route；要求 Codex 已完全退出，且不执行 No Micro 注入。
async fn launch_normal() -> Response {
    if std::env::consts::OS != "windows" {
        return err(StatusCode::NOT_IMPLEMENTED, "A/B 普通启动目前仅支持 Windows").into_response();
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
    let launched = tokio::task::spawn_blocking(|| process::launch_codex_app_restart("windows")).await;
    match launched {
        Ok(Ok(())) => {
            ab_log("INFO", &run_id, "normal", "launch_success", None);
            spawn_process_exit_marker(run_id.clone(), "normal");
            Json(json!({
                "success": true,
                "abRunId": run_id,
                "mode": "normal"
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

/// POST /api/desktop/no-micro/launch[?mode=normal]
///
/// 默认执行 fail-closed 的 No Micro 旁路实验启动；`mode=normal` 则执行 A/B 对照的普通启动。
/// 两条路径都会把稳定的 `[codex-ab]` marker 写进同一份 proxy-YYYY-MM-DD.log。
pub async fn launch(Query(query): Query<LaunchQuery>) -> Response {
    if query.mode.as_deref() == Some("normal") {
        return launch_normal().await;
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
            spawn_process_exit_marker(run_id, "no-micro");
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
