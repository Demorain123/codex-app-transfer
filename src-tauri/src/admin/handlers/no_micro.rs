use axum::{http::StatusCode, response::IntoResponse, Json};

use crate::admin::handlers::common::err;
use crate::admin::services::desktop::no_micro;

/// GET /api/desktop/no-micro/doctor
///
/// 只读检查 Windows AppX / ChatGPT.exe / bundled Node / app.asar 目标模块与
/// 当前进程状态。不会启动 Codex、不会修改 AppX/config/auth/session。
pub async fn doctor() -> impl IntoResponse {
    match tokio::task::spawn_blocking(no_micro::doctor).await {
        Ok(report) => Json(report).into_response(),
        Err(e) => err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("No Micro doctor task failed: {e}"),
        )
        .into_response(),
    }
}

/// POST /api/desktop/no-micro/launch
///
/// 仅执行 fail-closed 的旁路实验启动，不同步/改写 config.toml。若 Codex 仍在运行
/// 或进程身份无法确认，会拒绝启动，而不是自动杀用户现有进程。
pub async fn launch() -> impl IntoResponse {
    match tokio::task::spawn_blocking(no_micro::launch).await {
        Ok(Ok(result)) => Json(result).into_response(),
        Ok(Err(message)) => err(StatusCode::CONFLICT, message).into_response(),
        Err(e) => err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("No Micro launch task failed: {e}"),
        )
        .into_response(),
    }
}
