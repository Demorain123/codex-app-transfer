from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-RECOVERY-STATE-DB-BACKUP"

if MARKER in text:
    print("r46 recovery state DB backup hardening already applied")
    raise SystemExit(0)

text = text.replace(
    "    time::{Duration, Instant, SystemTime},\n",
    "    time::{Duration, Instant, SystemTime, UNIX_EPOCH},\n",
    1,
)
text = text.replace("SystemTime::UNIX_EPOCH", "UNIX_EPOCH")

old_struct = '''struct BackupInfo {
    directory: String,
    rollout_copy: String,
    sha256: String,
    bytes: u64,
}
'''
new_struct = '''struct BackupInfo {
    directory: String,
    rollout_copy: String,
    sha256: String,
    bytes: u64,
    // CAS-R46-RECOVERY-STATE-DB-BACKUP
    // thread/revert/rollback is performed through Codex app-server and may update the
    // state_<N>.sqlite thread index in addition to the rollout. Keep a cold copy of the
    // current state DB (+ sidecars if present) so recovery itself is reversible.
    state_db_copies: Vec<String>,
}
'''
if old_struct not in text:
    raise SystemExit("r46 backup hardening: BackupInfo anchor missing")
text = text.replace(old_struct, new_struct, 1)

old_call = "    let backup = backup_rollout(rollout, thread_id)?;\n"
new_call = "    let backup = backup_recovery_state(codex_home, rollout, thread_id)?;\n"
if old_call not in text:
    raise SystemExit("r46 backup hardening: backup call anchor missing")
text = text.replace(old_call, new_call, 1)

old_fn = '''fn backup_rollout(source: &Path, thread_id: &str) -> Result<BackupInfo, String> {
    let root = codex_app_transfer_registry::config_dir()
        .ok_or("无法解析 codex-app-transfer config dir")?
        .join("thread-recovery");
    let stamp = Local::now().format("%Y%m%d-%H%M%S").to_string();
    let directory = root.join(format!("{stamp}-{}", fingerprint8(thread_id)));
    let backup_dir = directory.join("source-backup");
    fs::create_dir_all(&backup_dir).map_err(|e| format!("创建恢复备份目录失败: {e}"))?;
    let name = source
        .file_name()
        .ok_or("rollout 文件名不可用")?;
    let destination = backup_dir.join(name);
    fs::copy(source, &destination).map_err(|e| format!("备份 rollout 失败: {e}"))?;
    let bytes = fs::metadata(&destination).map_err(|e| e.to_string())?.len();
    let sha256 = sha256_file(&destination)?;
    let manifest = json!({
        "version": 1,
        "createdAt": Local::now().to_rfc3339(),
        "threadFingerprint": fingerprint8(thread_id),
        "sourcePath": source.display().to_string(),
        "backupPath": destination.display().to_string(),
        "bytes": bytes,
        "sha256": sha256,
        "workspaceFilesChanged": false,
        "note": "Conversation-history backup only; workspace files are intentionally untouched."
    });
    fs::write(
        directory.join("RECOVERY-BACKUP.json"),
        serde_json::to_vec_pretty(&manifest).map_err(|e| e.to_string())?,
    )
    .map_err(|e| format!("写恢复 manifest 失败: {e}"))?;
    Ok(BackupInfo {
        directory: directory.display().to_string(),
        rollout_copy: destination.display().to_string(),
        sha256,
        bytes,
    })
}
'''
new_fn = '''// CAS-R46-RECOVERY-STATE-DB-BACKUP
fn newest_state_db(codex_home: &Path) -> Option<PathBuf> {
    let mut best: Option<(u32, PathBuf)> = None;
    for entry in fs::read_dir(codex_home).ok()?.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let Some(version) = name
            .strip_prefix("state_")
            .and_then(|value| value.strip_suffix(".sqlite"))
            .and_then(|value| value.parse::<u32>().ok())
        else {
            continue;
        };
        if best.as_ref().is_none_or(|(current, _)| version > *current) {
            best = Some((version, entry.path()));
        }
    }
    best.map(|(_, path)| path)
}

fn backup_recovery_state(
    codex_home: &Path,
    source: &Path,
    thread_id: &str,
) -> Result<BackupInfo, String> {
    let root = codex_app_transfer_registry::config_dir()
        .ok_or("无法解析 codex-app-transfer config dir")?
        .join("thread-recovery");
    let stamp = Local::now().format("%Y%m%d-%H%M%S").to_string();
    let directory = root.join(format!("{stamp}-{}", fingerprint8(thread_id)));
    let backup_dir = directory.join("source-backup");
    let state_dir = directory.join("state-db-backup");
    fs::create_dir_all(&backup_dir).map_err(|e| format!("创建恢复备份目录失败: {e}"))?;
    fs::create_dir_all(&state_dir).map_err(|e| format!("创建 state DB 备份目录失败: {e}"))?;

    let name = source.file_name().ok_or("rollout 文件名不可用")?;
    let destination = backup_dir.join(name);
    fs::copy(source, &destination).map_err(|e| format!("备份 rollout 失败: {e}"))?;
    let bytes = fs::metadata(&destination).map_err(|e| e.to_string())?.len();
    let sha256 = sha256_file(&destination)?;

    let mut state_db_copies = Vec::new();
    if let Some(state_db) = newest_state_db(codex_home) {
        let state_name = state_db.file_name().ok_or("state DB 文件名不可用")?;
        for source_path in [
            state_db.clone(),
            PathBuf::from(format!("{}-wal", state_db.display())),
            PathBuf::from(format!("{}-shm", state_db.display())),
        ] {
            if !source_path.is_file() {
                continue;
            }
            let destination_name = if source_path == state_db {
                state_name.to_os_string()
            } else {
                source_path
                    .file_name()
                    .ok_or("state DB sidecar 文件名不可用")?
                    .to_os_string()
            };
            let target = state_dir.join(destination_name);
            fs::copy(&source_path, &target)
                .map_err(|e| format!("备份 {} 失败: {e}", source_path.display()))?;
            state_db_copies.push(target.display().to_string());
        }
    }

    let manifest = json!({
        "version": 2,
        "createdAt": Local::now().to_rfc3339(),
        "threadFingerprint": fingerprint8(thread_id),
        "sourcePath": source.display().to_string(),
        "backupPath": destination.display().to_string(),
        "bytes": bytes,
        "sha256": sha256,
        "stateDbCopies": state_db_copies,
        "workspaceFilesChanged": false,
        "note": "Conversation rollout + cold Codex state DB backup. Workspace files are intentionally untouched."
    });
    fs::write(
        directory.join("RECOVERY-BACKUP.json"),
        serde_json::to_vec_pretty(&manifest).map_err(|e| e.to_string())?,
    )
    .map_err(|e| format!("写恢复 manifest 失败: {e}"))?;

    Ok(BackupInfo {
        directory: directory.display().to_string(),
        rollout_copy: destination.display().to_string(),
        sha256,
        bytes,
        state_db_copies,
    })
}
'''
if old_fn not in text:
    raise SystemExit("r46 backup hardening: backup function anchor missing")
text = text.replace(old_fn, new_fn, 1)

text = text.replace(
    '"执行修改前自动完整备份 rollout 并记录 SHA256".into(),',
    '"执行修改前自动完整备份 rollout + 当前 Codex state DB，并记录 rollout SHA256".into(),',
    1,
)

for marker in (
    "CAS-R46-RECOVERY-STATE-DB-BACKUP",
    "backup_recovery_state(codex_home, rollout, thread_id)",
    "state-db-backup",
    "state_db_copies",
    "UNIX_EPOCH",
):
    if marker not in text:
        raise SystemExit(f"r46 backup hardening invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 THREAD RECOVERY STATE-DB BACKUP HARDENING PASS")
