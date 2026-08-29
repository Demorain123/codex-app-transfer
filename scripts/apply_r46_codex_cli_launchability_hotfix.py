from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-CODEX-CLI-LAUNCHABILITY-HOTFIX"

if MARKER in text:
    print("r46 Codex CLI launchability hotfix already applied")
    raise SystemExit(0)

anchor = "fn find_codex_cli() -> Result<PathBuf, String> {\n"
helper = r'''// CAS-R46-CODEX-CLI-LAUNCHABILITY-HOTFIX
fn codex_cli_launch_preflight(path: &Path) -> Result<(), String> {
    let status = Command::new(path)
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|e| format!("Codex CLI 启动预检失败 {}: {e}", path.display()))?;
    if !status.success() {
        return Err(format!(
            "Codex CLI 启动预检返回非零状态 {}: {}",
            path.display(),
            status
        ));
    }
    Ok(())
}

fn find_launchable_codex_cli() -> Result<PathBuf, String> {
    for key in ["CODEX_CLI_PATH", "CODEX_BIN"] {
        if let Ok(value) = std::env::var(key) {
            let path = PathBuf::from(value.trim());
            if path.is_file() && codex_cli_launch_preflight(&path).is_ok() {
                return Ok(path);
            }
        }
    }

    #[cfg(target_os = "windows")]
    {
        // Prefer the user-visible PATH/App Execution Alias. The ExecutablePath of an
        // already-running MSIX child may live under protected WindowsApps and can return
        // ERROR_ACCESS_DENIED when a normal desktop process tries to CreateProcess it.
        if let Ok(output) = Command::new("where.exe").arg("codex.exe").output() {
            if output.status.success() {
                for line in String::from_utf8_lossy(&output.stdout).lines() {
                    let path = PathBuf::from(line.trim());
                    if path.is_file() && codex_cli_launch_preflight(&path).is_ok() {
                        return Ok(path);
                    }
                }
            }
        }
    }

    let fallback = find_codex_cli()?;
    codex_cli_launch_preflight(&fallback).map_err(|e| {
        format!(
            "检测到 Codex CLI 路径但无法直接启动；未关闭 Codex、未执行恢复。{e}"
        )
    })?;
    Ok(fallback)
}

'''
if anchor not in text:
    raise SystemExit("r46 CLI launchability hotfix: find_codex_cli anchor missing")
text = text.replace(anchor, helper + anchor, 1)

if "let cli = find_codex_cli();" not in text:
    raise SystemExit("r46 CLI launchability hotfix: preview CLI anchor missing")
text = text.replace("let cli = find_codex_cli();", "let cli = find_launchable_codex_cli();", 1)

old_action = '''    let cli = match find_codex_cli() {
        Ok(path) => path,
        Err(e) => return err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    };
'''
new_action = '''    let cli = match find_launchable_codex_cli() {
        Ok(path) => path,
        Err(e) => return err(StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    };
'''
if old_action not in text:
    raise SystemExit("r46 CLI launchability hotfix: action CLI anchor missing")
text = text.replace(old_action, new_action, 1)

for marker in (
    MARKER,
    "fn codex_cli_launch_preflight",
    "fn find_launchable_codex_cli",
    "where.exe",
    "未关闭 Codex、未执行恢复",
):
    if marker not in text:
        raise SystemExit(f"r46 CLI launchability hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 CODEX CLI LAUNCHABILITY HOTFIX PASS")
