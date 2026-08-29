from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-CODEX-CLI-SHADOW-COPY"

if MARKER in text:
    print("r46 Codex CLI shadow-copy hotfix already applied")
    raise SystemExit(0)

anchor = '''fn find_launchable_codex_cli() -> Result<PathBuf, String> {
'''
helper = r'''// CAS-R46-CODEX-CLI-SHADOW-COPY
#[cfg(target_os = "windows")]
fn running_codex_executable_path() -> Option<PathBuf> {
    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            "$p=Get-CimInstance Win32_Process -Filter \"Name='codex.exe'\" | Select-Object -First 1 -ExpandProperty ExecutablePath; if($p){[Console]::Out.Write($p)}",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let raw = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if raw.is_empty() {
        return None;
    }
    let path = PathBuf::from(raw);
    path.is_file().then_some(path)
}

#[cfg(target_os = "windows")]
fn shadow_copy_running_codex_cli() -> Result<PathBuf, String> {
    let source = running_codex_executable_path().ok_or(
        "Codex Desktop 正在运行，但未能读取其 native codex.exe 路径",
    )?;
    let root = recovery_backup_root()?
        .join("_runtime-tools")
        .join("codex-cli-shadow");
    fs::create_dir_all(&root)
        .map_err(|e| format!("创建 Codex CLI shadow 目录失败: {e}"))?;
    let destination = root.join("codex.exe");

    // Copying the packaged native runtime outside WindowsApps avoids ERROR_ACCESS_DENIED
    // from CreateProcess while keeping the exact Desktop-bundled native version.
    fs::copy(&source, &destination).map_err(|e| {
        format!(
            "复制 Codex Desktop 内置 codex.exe 到 V: shadow 目录失败: {e}"
        )
    })?;
    codex_cli_launch_preflight(&destination).map_err(|e| {
        let _ = fs::remove_file(&destination);
        format!("Codex CLI shadow 副本启动预检失败，未关闭 Codex、未执行恢复。{e}")
    })?;
    Ok(destination)
}

'''
if anchor not in text:
    raise SystemExit("r46 CLI shadow hotfix: launchable CLI anchor missing")
text = text.replace(anchor, helper + anchor, 1)

old = '''    let fallback = find_codex_cli()?;
    codex_cli_launch_preflight(&fallback).map_err(|e| {
        format!(
            "检测到 Codex CLI 路径但无法直接启动；未关闭 Codex、未执行恢复。{e}"
        )
    })?;
    Ok(fallback)
'''
new = '''    #[cfg(target_os = "windows")]
    {
        if let Ok(path) = shadow_copy_running_codex_cli() {
            return Ok(path);
        }
    }

    let fallback = find_codex_cli()?;
    codex_cli_launch_preflight(&fallback).map_err(|e| {
        format!(
            "检测到 Codex CLI 路径但无法直接启动；也未能准备 Desktop native shadow 副本；未关闭 Codex、未执行恢复。{e}"
        )
    })?;
    Ok(fallback)
'''
if old not in text:
    raise SystemExit("r46 CLI shadow hotfix: fallback anchor missing")
text = text.replace(old, new, 1)

# Make the preview wording match the new semantics: Desktop being detected is not enough;
# what matters is a launchable app-server runtime, including the V:-local shadow copy.
for marker in (
    MARKER,
    "fn running_codex_executable_path",
    "fn shadow_copy_running_codex_cli",
    "codex-cli-shadow",
    "shadow_copy_running_codex_cli()",
):
    if marker not in text:
        raise SystemExit(f"r46 CLI shadow hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 CODEX CLI SHADOW-COPY HOTFIX PASS")
