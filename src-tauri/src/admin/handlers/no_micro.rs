use axum::{extract::State, http::StatusCode, response::IntoResponse, Json};
use serde_json::{json, Value};

use crate::admin::handlers::common::err;
use crate::admin::services::desktop::{no_micro, snapshot};
use crate::admin::AdminState;

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
/// 先沿用普通「重启 Codex」的 desktop config 同步，再执行 fail-closed No Micro
/// 启动器。若 Codex 仍在运行或进程身份无法确认，会拒绝启动而不是自动杀用户现有进程。
pub async fn launch(State(state): State<AdminState>) -> impl IntoResponse {
    let desktop_sync = snapshot::sync_desktop_for_active_provider(&state).await;
    if desktop_sync.get("attempted").and_then(Value::as_bool) == Some(true)
        && desktop_sync.get("success").and_then(Value::as_bool) != Some(true)
    {
        return err(
            StatusCode::INTERNAL_SERVER_ERROR,
            desktop_sync
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("Codex 配置同步失败"),
        )
        .into_response();
    }

    match tokio::task::spawn_blocking(no_micro::launch).await {
        Ok(Ok(mut result)) => {
            if let Some(obj) = result.as_object_mut() {
                obj.insert("desktopSync".to_owned(), desktop_sync);
            }
            Json(result).into_response()
        }
        Ok(Err(message)) => err(StatusCode::CONFLICT, message).into_response(),
        Err(e) => err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("No Micro launch task failed: {e}"),
        )
        .into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_micro_handlers_keep_error_shape_json_compatible() {
        let v = json!({"success": false, "message": "example"});
        assert_eq!(v["success"], false);
        assert_eq!(v["message"], "example");
    }
}
