#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
HANDLER = ROOT / "src-tauri/src/admin/handlers/no_micro.rs"
BASE_MARKER = "CAS-NO-MICRO-R23-SHARED-RESTART-PIPELINE"
REVIEW_MARKER = "CAS-NO-MICRO-R23-LEGACY-RESTART-PRESERVED"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r23 restart review: anchor {label!r} count={count}, expected 1")
    return text.replace(old, new, 1)


def patch_process(text: str) -> str:
    if REVIEW_MARKER in text:
        return text
    if BASE_MARKER not in text:
        raise SystemExit("r23 restart review requires apply_no_micro_r23_restart_pipeline.py first")

    start = text.index(f"// {BASE_MARKER}")
    end = text.index("/// [CAT-255]", start)
    replacement = r'''fn open_codex_app(platform: &str) -> Result<(), String> {
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

// CAS-NO-MICRO-R23-SHARED-RESTART-PIPELINE
// CAS-NO-MICRO-R23-LEGACY-RESTART-PRESERVED
/// Prepare the launch-time state/arguments for an alternate final launcher such as No Micro.
/// This mirrors the state work performed by `open_codex_app` without changing that proven
/// legacy function itself. The normal Restart button therefore keeps byte-for-byte behavior.
pub fn prepare_codex_alternate_launch_args() -> Vec<String> {
    sync_codex_pet_state();
    sync_codex_reasoning_efforts_state();
    should_attach_debug_port()
}

/// Shared maintenance slot: exact legacy lock + quit + reap/grace sequence, with only the final
/// launcher supplied by the caller. The legacy Restart path calls `open_codex_app` unchanged;
/// No Micro uses the same closed/reaped slot and then launches through its inspector hook.
pub fn launch_codex_app_restart_with<T, F>(platform: &str, launcher: F) -> Result<T, String>
where
    F: FnOnce() -> Result<T, String>,
{
    let _guard = CODEX_MAINTENANCE_LOCK
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    let was_running = is_codex_app_running(platform);
    quit_codex_app_with_retries(platform)?;
    if was_running {
        std::thread::sleep(POST_QUIT_LAUNCHD_GRACE);
    }
    launcher()
}

pub fn launch_codex_app_restart(platform: &str) -> Result<(), String> {
    launch_codex_app_restart_with(platform, || open_codex_app(platform))
}

'''
    return text[:start] + replacement + text[end:]


def patch_handler(text: str) -> str:
    if "prepare_codex_alternate_launch_args" in text:
        return text
    old = '''    match process::launch_codex_app_restart_with(std::env::consts::OS, |extra_args| {
        no_micro::launch_with_args(extra_args)
    }) {
'''
    new = '''    match process::launch_codex_app_restart_with(std::env::consts::OS, || {
        let extra_args = process::prepare_codex_alternate_launch_args();
        no_micro::launch_with_args(&extra_args)
    }) {
'''
    return replace_once(text, old, new, "No Micro final launcher closure")


def main() -> None:
    process_text = PROCESS.read_text(encoding="utf-8")
    handler_text = HANDLER.read_text(encoding="utf-8")

    process_updated = patch_process(process_text)
    handler_updated = patch_handler(handler_text)

    if REVIEW_MARKER not in process_updated:
        raise SystemExit("r23 restart review marker missing after patch")
    if "prepare_codex_alternate_launch_args" not in handler_updated:
        raise SystemExit("r23 handler did not adopt alternate launch args")

    PROCESS.write_text(process_updated, encoding="utf-8")
    HANDLER.write_text(handler_updated, encoding="utf-8")
    print("applied r23 restart review: legacy Restart behavior preserved")


if __name__ == "__main__":
    main()
