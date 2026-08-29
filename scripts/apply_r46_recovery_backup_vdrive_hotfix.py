from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-RECOVERY-BACKUP-VDRIVE"

if MARKER in text:
    print("r46 recovery backup V-drive hotfix already applied")
    raise SystemExit(0)

old = '''fn backup_recovery_state(
    codex_home: &Path,
    source: &Path,
    thread_id: &str,
) -> Result<BackupInfo, String> {
    let root = codex_app_transfer_registry::config_dir()
        .ok_or("无法解析 codex-app-transfer config dir")?
        .join("thread-recovery");
'''
new = '''// CAS-R46-RECOVERY-BACKUP-VDRIVE
fn recovery_backup_root() -> Result<PathBuf, String> {
    // Explicit override wins. Otherwise prefer V: because recovery rollouts can be
    // hundreds of MB and the Windows system drive may be intentionally small.
    if let Ok(value) = std::env::var("CODEX_APP_TRANSFER_RECOVERY_BACKUP_DIR") {
        let value = value.trim();
        if !value.is_empty() {
            return Ok(PathBuf::from(value));
        }
    }
    #[cfg(target_os = "windows")]
    {
        let v = PathBuf::from(r"V:\\Codex-App-Transfer-Recovery-Backups");
        if Path::new(r"V:\\").is_dir() {
            return Ok(v);
        }
    }
    Ok(codex_app_transfer_registry::config_dir()
        .ok_or("无法解析 codex-app-transfer config dir")?
        .join("thread-recovery"))
}

fn recovery_backup_required_bytes(codex_home: &Path, source: &Path) -> u64 {
    let mut total = fs::metadata(source).map(|m| m.len()).unwrap_or(0);
    if let Some(state_db) = newest_state_db(codex_home) {
        for path in [
            state_db.clone(),
            PathBuf::from(format!("{}-wal", state_db.display())),
            PathBuf::from(format!("{}-shm", state_db.display())),
        ] {
            total = total.saturating_add(fs::metadata(path).map(|m| m.len()).unwrap_or(0));
        }
    }
    // Keep a small safety margin for the manifest and filesystem allocation slack.
    total.saturating_add(64 * 1024 * 1024)
}

#[cfg(target_os = "windows")]
fn windows_drive_free_bytes(root: &Path) -> Result<u64, String> {
    let raw = root.display().to_string();
    let bytes = raw.as_bytes();
    if bytes.len() < 2 || bytes[1] != b':' || !bytes[0].is_ascii_alphabetic() {
        return Err(format!("恢复备份目录不是可检测剩余空间的盘符路径: {raw}"));
    }
    let drive = (bytes[0] as char).to_ascii_uppercase();
    let script = format!("$d=Get-PSDrive -Name '{drive}' -ErrorAction Stop; [Console]::Out.Write($d.Free)");
    let output = Command::new("powershell")
        .args(["-NoProfile", "-Command", &script])
        .output()
        .map_err(|e| format!("检测 {drive}: 剩余空间失败: {e}"))?;
    if !output.status.success() {
        return Err(format!("检测 {drive}: 剩余空间失败"));
    }
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse::<u64>()
        .map_err(|e| format!("解析 {drive}: 剩余空间失败: {e}"))
}

fn preflight_recovery_backup_space(codex_home: &Path, source: &Path) -> Result<(), String> {
    let root = recovery_backup_root()?;
    let required = recovery_backup_required_bytes(codex_home, source);
    #[cfg(target_os = "windows")]
    {
        let free = windows_drive_free_bytes(&root)?;
        if free < required {
            return Err(format!(
                "恢复备份空间不足，未关闭 Codex、未修改会话：需要至少 {:.2} MB，可用 {:.2} MB，备份目录 {}",
                required as f64 / 1024.0 / 1024.0,
                free as f64 / 1024.0 / 1024.0,
                root.display(),
            ));
        }
    }
    Ok(())
}

fn backup_recovery_state(
    codex_home: &Path,
    source: &Path,
    thread_id: &str,
) -> Result<BackupInfo, String> {
    let root = recovery_backup_root()?;
'''
if old not in text:
    raise SystemExit("r46 V-drive backup hotfix: backup root anchor missing")
text = text.replace(old, new, 1)

old_action = '''    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[thread-recovery-r46] action={} stage=begin thread={} workspace_mutation=false",
            action_name,
            fingerprint8(&thread_id),
        ),
    );

    let outcome = tokio::task::spawn_blocking(move || {
'''
new_action = '''    if let Err(e) = preflight_recovery_backup_space(&paths.codex_home, &rollout) {
        return err(StatusCode::INSUFFICIENT_STORAGE, e).into_response();
    }

    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[thread-recovery-r46] action={} stage=begin thread={} workspace_mutation=false backup_root={}",
            action_name,
            fingerprint8(&thread_id),
            recovery_backup_root().map(|p| p.display().to_string()).unwrap_or_else(|_| "<unavailable>".into()),
        ),
    );

    let outcome = tokio::task::spawn_blocking(move || {
'''
if old_action not in text:
    raise SystemExit("r46 V-drive backup hotfix: recovery action preflight anchor missing")
text = text.replace(old_action, new_action, 1)

# Surface the actual backup root in the preview safeguards so users know large
# history copies are not silently targeting the system drive.
old_safe = '            "执行修改前自动完整备份 rollout + 当前 Codex state DB，并记录 rollout SHA256".into(),\n'
new_safe = '            format!("执行修改前自动完整备份 rollout + 当前 Codex state DB，并记录 rollout SHA256；备份根目录：{}", recovery_backup_root().map(|p| p.display().to_string()).unwrap_or_else(|_| "<unavailable>".into())),\n'
if old_safe not in text:
    raise SystemExit("r46 V-drive backup hotfix: safeguard anchor missing")
text = text.replace(old_safe, new_safe, 1)

for marker in (
    MARKER,
    "CODEX_APP_TRANSFER_RECOVERY_BACKUP_DIR",
    "Codex-App-Transfer-Recovery-Backups",
    "preflight_recovery_backup_space(&paths.codex_home, &rollout)",
    "StatusCode::INSUFFICIENT_STORAGE",
    "let root = recovery_backup_root()?;",
):
    if marker not in text:
        raise SystemExit(f"r46 V-drive backup hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 RECOVERY BACKUP V-DRIVE HOTFIX PASS")
