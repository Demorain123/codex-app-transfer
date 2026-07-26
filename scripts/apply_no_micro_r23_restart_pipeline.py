#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
NO_MICRO_SERVICE = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
DESKTOP_HANDLER = ROOT / "src-tauri/src/admin/handlers/desktop.rs"
NO_MICRO_HANDLER = ROOT / "src-tauri/src/admin/handlers/no_micro.rs"

PROCESS_MARKER = "CAS-NO-MICRO-R23-SHARED-RESTART-PIPELINE"
DESKTOP_MARKER = "CAS-NO-MICRO-R23-SHARED-DESKTOP-PREP"
HANDLER_MARKER = "CAS-NO-MICRO-R23-AB-SHARED-PIPELINE"
SERVICE_MARKER = "CAS-NO-MICRO-R23-LAUNCH-ARGS"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r23 restart overlay: anchor {label!r} count={count}, expected 1")
    return text.replace(old, new, 1)


def patch_process(text: str) -> str:
    if PROCESS_MARKER in text:
        return text

    old = '''fn open_codex_app(platform: &str) -> Result<(), String> {
    sync_codex_pet_state();
    // [MOC-285] Codex 启动前补齐 enabled-reasoning-efforts 持久 atom,让 GLM 等的 none/max 档
    // 在 reasoning 选择器正常显示(Codex 26.623+ 默认启用集不含这两档)。
    sync_codex_reasoning_efforts_state();

    // Windows MSIX activation: 见 `windows_msix.rs` module docs。失败时
    // fallthrough 到 explorer.exe shell:AppsFolder 老路径(args 丢失)。
    #[cfg(target_os = "windows")]
    if crate::windows_msix::try_launch_codex(&should_attach_debug_port()) {
        return Ok(());
    }

    let resolved = if platform == "macos" {
        resolve_macos_app_path()
    } else {
        None
    };
    let extra_args = should_attach_debug_port();
    let chat_env = chat_launch_env(platform);
    let cmd = open_command(platform, resolved.as_deref(), &extra_args, &chat_env);
    let Some((program, args)) = cmd.split_first() else {
        return Err("open command is empty".to_owned());
    };
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console_window(&mut command)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("cannot launch Codex App: {e}"))
}

pub fn launch_codex_app_restart(platform: &str) -> Result<(), String> {
    let _guard = CODEX_MAINTENANCE_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let was_running = is_codex_app_running(platform);
    quit_codex_app_with_retries(platform)?;
    // 退出确认后给 launchd 一段 grace 让它 reap 完旧进程,LaunchServices 才会
    // 把"Codex 在运行"的缓存清掉。否则紧跟的 `open -a` 会被当成 activate
    // 一个不存在的实例,啥也不发生(2026-05-06 现场实测)。
    // 跳过条件:本来就没在运行,根本不需要等。
    if was_running {
        std::thread::sleep(POST_QUIT_LAUNCHD_GRACE);
    }
    open_codex_app(platform)
}
'''

    new = '''// CAS-NO-MICRO-R23-SHARED-RESTART-PIPELINE
// Produce the exact launch-time state/arguments used by the proven legacy restart path.
// No Micro B receives these same arguments; only the final process launcher differs.
fn prepare_codex_process_launch() -> Vec<String> {
    sync_codex_pet_state();
    // [MOC-285] Codex 启动前补齐 enabled-reasoning-efforts 持久 atom,让 GLM 等的 none/max 档
    // 在 reasoning 选择器正常显示(Codex 26.623+ 默认启用集不含这两档)。
    sync_codex_reasoning_efforts_state();
    should_attach_debug_port()
}

fn open_codex_app_prepared(platform: &str, extra_args: &[String]) -> Result<(), String> {
    // Windows MSIX activation: 见 `windows_msix.rs` module docs。失败时
    // fallthrough 到 explorer.exe shell:AppsFolder 老路径(args 丢失)。
    #[cfg(target_os = "windows")]
    if crate::windows_msix::try_launch_codex(extra_args) {
        return Ok(());
    }

    let resolved = if platform == "macos" {
        resolve_macos_app_path()
    } else {
        None
    };
    let chat_env = chat_launch_env(platform);
    let cmd = open_command(platform, resolved.as_deref(), extra_args, &chat_env);
    let Some((program, args)) = cmd.split_first() else {
        return Err("open command is empty".to_owned());
    };
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    hide_console_window(&mut command)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("cannot launch Codex App: {e}"))
}

fn open_codex_app(platform: &str) -> Result<(), String> {
    let extra_args = prepare_codex_process_launch();
    open_codex_app_prepared(platform, &extra_args)
}

/// Shared restart primitive used by the legacy Restart button and No Micro A/B.
/// It owns the exact maintenance lock, quit/reap/grace sequence and pre-launch state.
/// Callers may change only the final launcher closure.
pub fn launch_codex_app_restart_with<T, F>(platform: &str, launcher: F) -> Result<T, String>
where
    F: FnOnce(&[String]) -> Result<T, String>,
{
    let _guard = CODEX_MAINTENANCE_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let was_running = is_codex_app_running(platform);
    quit_codex_app_with_retries(platform)?;
    // 退出确认后给 launchd 一段 grace 让它 reap 完旧进程,LaunchServices 才会
    // 把"Codex 在运行"的缓存清掉。否则紧跟的 `open -a` 会被当成 activate
    // 一个不存在的实例,啥也不发生(2026-05-06 现场实测)。
    // 跳过条件:本来就没在运行,根本不需要等。
    if was_running {
        std::thread::sleep(POST_QUIT_LAUNCHD_GRACE);
    }
    let extra_args = prepare_codex_process_launch();
    launcher(&extra_args)
}

pub fn launch_codex_app_restart(platform: &str) -> Result<(), String> {
    launch_codex_app_restart_with(platform, |extra_args| {
        open_codex_app_prepared(platform, extra_args)
    })
}
'''
    return replace_once(text, old, new, "process shared restart")


def patch_no_micro_service(text: str) -> str:
    if SERVICE_MARKER in text:
        return text

    text = replace_once(
        text,
        '''pub fn launch() -> Result<Value, String> {
    #[cfg(target_os = "windows")]
    {
        launch_windows()
    }
    #[cfg(not(target_os = "windows"))]
    {
        Err("Codex No Micro 目前仅支持 Windows".to_owned())
    }
}
''',
        '''// CAS-NO-MICRO-R23-LAUNCH-ARGS
pub fn launch() -> Result<Value, String> {
    launch_with_args(&[])
}

/// Launch through the hardened No Micro injector while preserving the same Codex
/// launch arguments prepared by the legacy Restart pipeline (CDP/theme/quota/etc.).
pub fn launch_with_args(extra_args: &[String]) -> Result<Value, String> {
    #[cfg(target_os = "windows")]
    {
        launch_windows(extra_args)
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = extra_args;
        Err("Codex No Micro 目前仅支持 Windows".to_owned())
    }
}
''',
        "no-micro launch API",
    )
    text = replace_once(
        text,
        'fn launch_windows() -> Result<Value, String> {',
        'fn launch_windows(extra_args: &[String]) -> Result<Value, String> {',
        "launch_windows signature",
    )
    text = replace_once(
        text,
        '''    command
        .arg(&launcher)
        .arg(&executable)
        .env("CAS_NO_MICRO_STATUS_PATH", &status_path)
''',
        '''    command
        .arg(&launcher)
        .arg(&executable)
        .args(extra_args)
        .env("CAS_NO_MICRO_STATUS_PATH", &status_path)
''',
        "launcher extra args",
    )
    return text


def patch_desktop_handler(text: str) -> str:
    if DESKTOP_MARKER in text:
        return text

    old = '''pub async fn restart_codex_app(State(state): State<crate::admin::AdminState>) -> impl IntoResponse {
    let desktop_sync = snapshot::sync_desktop_for_active_provider(&state).await;
    if desktop_sync.get("attempted").and_then(|v| v.as_bool()) == Some(true)
        && desktop_sync.get("success").and_then(|v| v.as_bool()) != Some(true)
    {
        return err(
            StatusCode::INTERNAL_SERVER_ERROR,
            desktop_sync
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("Codex 配置同步失败"),
        )
        .into_response();
    }
    match process::launch_codex_app_restart(std::env::consts::OS) {
        Ok(_) => {
            // 通知 plugin_unlock daemon 重置 backoff 立刻重新 detect_cdp。
            let service = super::plugin_unlock::get_service().await;
            service.reinject().await;
            Json(json!({"success": true, "desktopSync": desktop_sync})).into_response()
        }
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    }
}
'''
    new = '''// CAS-NO-MICRO-R23-SHARED-DESKTOP-PREP
/// The exact config/provider preparation used by the proven legacy Restart Codex App path.
/// No Micro A/B must call this helper instead of maintaining a second approximation.
pub(crate) async fn prepare_codex_restart_runtime(
    state: &crate::admin::AdminState,
) -> Result<Value, String> {
    let desktop_sync = snapshot::sync_desktop_for_active_provider(state).await;
    if desktop_sync.get("attempted").and_then(|v| v.as_bool()) == Some(true)
        && desktop_sync.get("success").and_then(|v| v.as_bool()) != Some(true)
    {
        return Err(
            desktop_sync
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("Codex 配置同步失败")
                .to_owned(),
        );
    }
    Ok(desktop_sync)
}

/// Mirror the legacy Restart button's post-launch CDP reinjection behavior.
pub(crate) async fn reinject_after_codex_restart() {
    let service = super::plugin_unlock::get_service().await;
    service.reinject().await;
}

pub async fn restart_codex_app(State(state): State<crate::admin::AdminState>) -> impl IntoResponse {
    let desktop_sync = match prepare_codex_restart_runtime(&state).await {
        Ok(value) => value,
        Err(message) => {
            return err(StatusCode::INTERNAL_SERVER_ERROR, message).into_response();
        }
    };
    match process::launch_codex_app_restart(std::env::consts::OS) {
        Ok(_) => {
            reinject_after_codex_restart().await;
            Json(json!({"success": true, "desktopSync": desktop_sync})).into_response()
        }
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    }
}
'''
    return replace_once(text, old, new, "desktop restart handler")


def patch_no_micro_handler(text: str) -> str:
    if HANDLER_MARKER in text:
        return text

    text = replace_once(
        text,
        'use crate::admin::services::desktop::{no_micro, snapshot};\n',
        'use crate::admin::handlers::desktop as desktop_handler;\nuse crate::admin::services::desktop::{no_micro, process};\n',
        "handler imports",
    )

    start = text.index('/// Prepare a *shared* Transfer-managed runtime for both A and B.')
    end = text.index('/// GET /api/desktop/no-micro/doctor', start)
    helper = '''// CAS-NO-MICRO-R23-AB-SHARED-PIPELINE
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

'''
    text = text[:start] + helper + text[end:]

    normal_start = text.index('/// A/B 对照的 A 路径。')
    normal_end = text.index('#[cfg(not(target_os = "windows"))]', normal_start)
    normal = '''/// A/B 对照的 A 路径：完全复用已知正常的 legacy Restart pipeline。
/// 唯一新增行为是稳定 `[codex-ab]` marker；Micro 正常加载。
#[cfg(target_os = "windows")]
async fn launch_normal(state: &AdminState, run_id: &str) -> Response {
    let desktop_sync = match prepare_ab_environment(state, run_id, "normal").await {
        Ok(value) => value,
        Err(message) => return err(StatusCode::CONFLICT, message).into_response(),
    };

    ab_log("INFO", run_id, "normal", "launch_requested", Some("pipeline=legacy-restart"));
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

'''
    text = text[:normal_start] + normal + text[normal_end:]

    text = replace_once(
        text,
        '''    if !report.launch_ready {
        return err(
            StatusCode::CONFLICT,
            "No Micro B 当前不满足 launch-ready 条件；请先完全退出 Codex 并重新兼容性检查。",
        )
        .into_response();
    }
''',
        '''    // Compatibility is checked before touching the runtime, but running Codex is allowed:
    // the shared legacy restart primitive will close/reap it safely before No Micro launches.
    if !report.compatible {
        return err(
            StatusCode::CONFLICT,
            report
                .warnings
                .first()
                .cloned()
                .unwrap_or_else(|| "No Micro B 当前未通过兼容性检查".to_owned()),
        )
        .into_response();
    }
''',
        "B compatibility gate",
    )

    old_b = '''    ab_log("INFO", &run_id, "no-micro", "launch_requested", None);
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
'''
    new_b = '''    ab_log(
        "INFO",
        &run_id,
        "no-micro",
        "launch_requested",
        Some("pipeline=legacy-restart-shared final_launcher=no-micro"),
    );
    match process::launch_codex_app_restart_with(std::env::consts::OS, |extra_args| {
        no_micro::launch_with_args(extra_args)
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
                "no-micro",
                "injection_success",
                Some(&format!("pid={pid} pipeline=legacy-restart-shared")),
            );
            if let Some(obj) = result.as_object_mut() {
                obj.insert("abRunId".to_owned(), Value::String(run_id.clone()));
                obj.insert("mode".to_owned(), Value::String("no-micro".to_owned()));
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
                "no-micro",
                "launch_failed",
                Some(&format!("pipeline=legacy-restart-shared error={message}")),
            );
            err(StatusCode::CONFLICT, message).into_response()
        }
    }
'''
    text = replace_once(text, old_b, new_b, "B shared restart launch")
    return text


def main() -> None:
    files = {
        PROCESS: (patch_process, PROCESS_MARKER),
        NO_MICRO_SERVICE: (patch_no_micro_service, SERVICE_MARKER),
        DESKTOP_HANDLER: (patch_desktop_handler, DESKTOP_MARKER),
        NO_MICRO_HANDLER: (patch_no_micro_handler, HANDLER_MARKER),
    }

    current = {path: path.read_text(encoding="utf-8") for path in files}
    markers = [marker in current[path] for path, (_, marker) in files.items()]
    if any(markers) and not all(markers):
        raise SystemExit("r23 restart overlay: partial generated state detected; refusing to guess")
    if all(markers):
        print("r23 shared restart pipeline already applied")
        return

    for path, (patcher, marker) in files.items():
        updated = patcher(current[path])
        if marker not in updated:
            raise SystemExit(f"r23 restart overlay: marker missing after patch: {marker}")
        path.write_text(updated, encoding="utf-8")
        print(f"patched {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
