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
    "let root = recovery_backup_root()?;",
):
    if marker not in text:
        raise SystemExit(f"r46 V-drive backup hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 RECOVERY BACKUP V-DRIVE HOTFIX PASS")
