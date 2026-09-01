from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"
MARKER = "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION"

source = TARGET.read_text(encoding="utf-8")
if MARKER in source:
    print("r57 external MCP source migration already applied")
    raise SystemExit(0)

if "CAS-R55-DETACHED-MCP-HELPER" not in source:
    raise SystemExit("r57 requires r55 detached MCP helper baseline")

cargo = CARGO.read_text(encoding="utf-8")
if 'rusqlite = { version = "0.31", features = ["bundled"] }' not in cargo:
    win_anchor = '''[target.'cfg(target_os = "windows")'.dependencies]\nwindows = { version = "0.62", features = [\n'''
    if win_anchor not in cargo:
        raise SystemExit("r57: Windows dependency anchor missing")
    cargo = cargo.replace(
        win_anchor,
        '''[target.'cfg(target_os = "windows")'.dependencies]\n# r57: migrate the single CC Switch cat-webfetch row away from the install-directory EXE.\n# bundled keeps this independent of any system sqlite DLL/CLI.\nrusqlite = { version = "0.31", features = ["bundled"] }\nwindows = { version = "0.62", features = [\n''',
        1,
    )
    CARGO.write_text(cargo, encoding="utf-8")

helper_anchor = '''#[cfg(not(target_os = "windows"))]\nfn detached_web_fetch_exe_r55() -> Result<PathBuf, String> {\n    // The install-lock failure is Windows-specific. Keep the existing command path on\n    // other platforms until there is a demonstrated need to change their lifecycle.\n    std::env::current_exe().map_err(|e| format!("拿不到自身可执行路径: {e}"))\n}\n\n'''
if helper_anchor not in source:
    raise SystemExit("r57: r55 detached helper tail anchor missing")

helpers = r'''// CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION
//
// r55 fixed the live Codex registration, but two external sources can write the old
// install-directory command back later:
//   1. CC Switch persists MCP definitions in ~/.cc-switch/cc-switch.db and immediately
//      syncs enabled Codex entries back to ~/.codex/config.toml.
//   2. OMP can own its own mcp.json and prefer that native definition over imported
//      external-tool config.
//
// Only migrate a server when BOTH conditions hold:
//   - args select Transfer's webfetch MCP entrypoint; and
//   - command is the old main `codex-app-transfer.exe`, not an r55 detached helper.
// Everything else (other MCP servers, providers, app flags, env, secrets, timeouts) is
// preserved byte/field-wise. External-source migration is best-effort and must never
// prevent Transfer from starting.

#[cfg(target_os = "windows")]
fn webfetch_args_match_r57(value: &serde_json::Value) -> bool {
    value
        .get("args")
        .and_then(serde_json::Value::as_array)
        .map(|args| {
            args.iter().any(|arg| {
                matches!(
                    arg.as_str(),
                    Some("--mcp-serve-webfetch") | Some("--mcp-serve=webfetch")
                )
            })
        })
        .unwrap_or(false)
}

#[cfg(target_os = "windows")]
fn old_install_webfetch_command_r57(command: &str) -> bool {
    let trimmed = command.trim().trim_matches('"');
    let normalized = trimmed.replace('/', "\\").to_ascii_lowercase();
    if normalized.contains("\\.codex-app-transfer\\mcp-bin\\") {
        return false;
    }
    Path::new(trimmed)
        .file_name()
        .and_then(|name| name.to_str())
        .map(|name| name.eq_ignore_ascii_case("codex-app-transfer.exe"))
        .unwrap_or(false)
}

#[cfg(target_os = "windows")]
fn migrate_webfetch_server_value_r57(
    value: &mut serde_json::Value,
    detached_exe: &Path,
) -> Option<(String, Option<String>)> {
    if !webfetch_args_match_r57(value) {
        return None;
    }
    let old_command = value.get("command")?.as_str()?.to_owned();
    if !old_install_webfetch_command_r57(&old_command) {
        return None;
    }

    let old_cwd = value
        .get("cwd")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned);
    let detached = detached_exe.to_string_lossy().to_string();
    value["command"] = serde_json::Value::String(detached.clone());

    // cwd does not lock the executable, but an old install-directory cwd can disappear
    // after uninstall. Only rewrite it when it exactly equals the old command's parent;
    // otherwise preserve the user's explicit cwd.
    if let (Some(cwd), Some(old_parent), Some(new_parent)) = (
        old_cwd.as_deref(),
        Path::new(old_command.trim().trim_matches('"')).parent(),
        detached_exe.parent(),
    ) {
        let norm = |s: &str| s.replace('/', "\\").trim_end_matches('\\').to_ascii_lowercase();
        if norm(cwd) == norm(&old_parent.to_string_lossy()) {
            value["cwd"] = serde_json::Value::String(new_parent.to_string_lossy().to_string());
        }
    }

    Some((old_command, old_cwd))
}

#[cfg(target_os = "windows")]
fn external_migration_audit_path_r57() -> Result<PathBuf, String> {
    let home = resolve_home().ok_or_else(|| "HOME / USERPROFILE not set".to_owned())?;
    Ok(home
        .join(".codex-app-transfer")
        .join("managed-history")
        .join("external-mcp-r57.jsonl"))
}

#[cfg(target_os = "windows")]
fn append_external_migration_audit_r57(entry: &serde_json::Value) -> Result<(), String> {
    use std::io::Write;
    let path = external_migration_audit_path_r57()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("创建 r57 migration audit 目录失败: {e}"))?;
    }
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| format!("打开 r57 migration audit 失败: {e}"))?;
    let line = serde_json::to_string(entry)
        .map_err(|e| format!("序列化 r57 migration audit 失败: {e}"))?;
    writeln!(file, "{line}").map_err(|e| format!("写 r57 migration audit 失败: {e}"))
}

#[cfg(target_os = "windows")]
fn migrate_cc_switch_webfetch_r57(detached_exe: &Path) -> Result<usize, String> {
    use rusqlite::{params, Connection, OpenFlags, TransactionBehavior};

    let home = resolve_home().ok_or_else(|| "HOME / USERPROFILE not set".to_owned())?;
    let db_path = home.join(".cc-switch").join("cc-switch.db");
    if !db_path.is_file() {
        return Ok(0);
    }

    let mut conn = Connection::open_with_flags(
        &db_path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("打开 CC Switch DB 失败: {e}"))?;
    conn.busy_timeout(std::time::Duration::from_millis(1500))
        .map_err(|e| format!("设置 CC Switch DB busy timeout 失败: {e}"))?;

    let table_exists: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='mcp_servers'",
            [],
            |row| row.get(0),
        )
        .map_err(|e| format!("检查 CC Switch mcp_servers 表失败: {e}"))?;
    if table_exists == 0 {
        return Ok(0);
    }

    let mut pending: Vec<(String, String, String, String)> = Vec::new();
    {
        let mut stmt = conn
            .prepare(
                "SELECT id, name, server_config FROM mcp_servers WHERE enabled_codex != 0",
            )
            .map_err(|e| format!("读取 CC Switch MCP rows 失败: {e}"))?;
        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(|e| format!("查询 CC Switch MCP rows 失败: {e}"))?;
        for row in rows {
            let (id, name, raw) = row.map_err(|e| format!("读取 CC Switch MCP row 失败: {e}"))?;
            let mut value: serde_json::Value = match serde_json::from_str(&raw) {
                Ok(value) => value,
                Err(_) => continue,
            };
            let Some((old_command, _old_cwd)) =
                migrate_webfetch_server_value_r57(&mut value, detached_exe)
            else {
                continue;
            };
            // Name is an extra guard when present, but old/imported entries sometimes
            // carry a generated id while the display name remains cat-webfetch. The
            // command+entrypoint match above is the hard semantic guard.
            let updated = serde_json::to_string(&value)
                .map_err(|e| format!("序列化 CC Switch MCP row 失败: {e}"))?;
            pending.push((id, name, raw, updated));
            tracing::info!(
                "[mcp-r57] source=cc-switch action=match name={} old_command_basename={} target=detached",
                pending.last().map(|x| x.1.as_str()).unwrap_or("?"),
                Path::new(&old_command)
                    .file_name()
                    .and_then(|x| x.to_str())
                    .unwrap_or("?"),
            );
        }
    }

    if pending.is_empty() {
        return Ok(0);
    }

    // Write a narrowly scoped audit BEFORE DB mutation. It records only id/name and
    // old/new command paths; no env/header/provider secrets are copied out of CC Switch.
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    for (id, name, old_raw, new_raw) in &pending {
        let old_value: serde_json::Value = serde_json::from_str(old_raw).unwrap_or_default();
        let new_value: serde_json::Value = serde_json::from_str(new_raw).unwrap_or_default();
        append_external_migration_audit_r57(&serde_json::json!({
            "ts": timestamp,
            "source": "cc-switch",
            "id": id,
            "name": name,
            "old_command": old_value.get("command").and_then(|v| v.as_str()),
            "new_command": new_value.get("command").and_then(|v| v.as_str()),
        }))?;
    }

    let tx = conn
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|e| format!("开始 CC Switch MCP migration transaction 失败: {e}"))?;
    let mut changed = 0usize;
    for (id, _name, old_raw, new_raw) in &pending {
        let affected = tx
            .execute(
                "UPDATE mcp_servers SET server_config=?1 WHERE id=?2 AND server_config=?3",
                params![new_raw, id, old_raw],
            )
            .map_err(|e| format!("更新 CC Switch MCP row 失败: {e}"))?;
        if affected == 1 {
            changed += 1;
        } else {
            return Err(format!(
                "CC Switch MCP row 在迁移期间发生并发变化,拒绝覆盖: id={id}"
            ));
        }
    }
    tx.commit()
        .map_err(|e| format!("提交 CC Switch MCP migration 失败: {e}"))?;
    Ok(changed)
}

#[cfg(target_os = "windows")]
fn omp_native_mcp_paths_r57() -> Vec<PathBuf> {
    let Some(home) = resolve_home() else {
        return Vec::new();
    };
    let root = home.join(".omp");
    let mut paths = vec![
        root.join("agent").join("mcp.json"),
        root.join("agent").join(".mcp.json"),
        root.join("mcp.json"),
        root.join(".mcp.json"),
    ];
    let profiles = root.join("profiles");
    if let Ok(entries) = fs::read_dir(profiles) {
        for entry in entries.flatten() {
            let agent = entry.path().join("agent");
            paths.push(agent.join("mcp.json"));
            paths.push(agent.join(".mcp.json"));
        }
    }
    paths
}

#[cfg(target_os = "windows")]
fn migrate_omp_native_webfetch_r57(detached_exe: &Path) -> Result<usize, String> {
    let mut changed_files = 0usize;
    for path in omp_native_mcp_paths_r57() {
        if !path.is_file() {
            continue;
        }
        let raw = fs::read_to_string(&path)
            .map_err(|e| format!("读取 OMP MCP 配置失败 {}: {e}", path.display()))?;
        let mut root: serde_json::Value = match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(_) => continue,
        };
        let Some(servers) = root.get_mut("mcpServers").and_then(|v| v.as_object_mut()) else {
            continue;
        };
        let mut changed_entries = Vec::new();
        for (name, server) in servers.iter_mut() {
            if let Some((old_command, _old_cwd)) =
                migrate_webfetch_server_value_r57(server, detached_exe)
            {
                changed_entries.push((name.clone(), old_command));
            }
        }
        if changed_entries.is_empty() {
            continue;
        }

        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        for (name, old_command) in &changed_entries {
            append_external_migration_audit_r57(&serde_json::json!({
                "ts": timestamp,
                "source": "omp-native",
                "path": path.to_string_lossy(),
                "name": name,
                "old_command": old_command,
                "new_command": detached_exe.to_string_lossy(),
            }))?;
        }

        let pretty = serde_json::to_string_pretty(&root)
            .map_err(|e| format!("序列化 OMP MCP 配置失败 {}: {e}", path.display()))?;
        let tmp = path.with_extension("json.r57.tmp");
        fs::write(&tmp, pretty)
            .map_err(|e| format!("写 OMP MCP 临时配置失败 {}: {e}", tmp.display()))?;
        fs::rename(&tmp, &path)
            .map_err(|e| format!("提交 OMP MCP 配置失败 {}: {e}", path.display()))?;
        changed_files += 1;
    }
    Ok(changed_files)
}

#[cfg(target_os = "windows")]
fn migrate_external_webfetch_sources_r57(detached_exe: &Path) {
    match migrate_cc_switch_webfetch_r57(detached_exe) {
        Ok(changed) if changed > 0 => tracing::warn!(
            "[mcp-r57] source=cc-switch action=migrated rows={} restart_external_hosts_once=true",
            changed
        ),
        Ok(_) => {}
        Err(error) => tracing::warn!(
            "[mcp-r57] source=cc-switch action=skip error={} live_codex_registration_still_updates=true",
            error
        ),
    }
    match migrate_omp_native_webfetch_r57(detached_exe) {
        Ok(changed) if changed > 0 => tracing::warn!(
            "[mcp-r57] source=omp-native action=migrated files={} restart_external_hosts_once=true",
            changed
        ),
        Ok(_) => {}
        Err(error) => tracing::warn!(
            "[mcp-r57] source=omp-native action=skip error={} live_codex_registration_still_updates=true",
            error
        ),
    }
}

'''
source = source.replace(helper_anchor, helper_anchor + helpers, 1)

sync_anchor = '''    let exe = detached_web_fetch_exe_r55()?\n        .to_string_lossy()\n        .to_string();\n    let want_args = vec!["--mcp-serve-webfetch".to_string()];\n'''
sync_replacement = '''    let detached_exe_r57 = detached_web_fetch_exe_r55()?;\n    #[cfg(target_os = "windows")]\n    migrate_external_webfetch_sources_r57(&detached_exe_r57);\n    let exe = detached_exe_r57.to_string_lossy().to_string();\n    let want_args = vec!["--mcp-serve-webfetch".to_string()];\n'''
if sync_anchor not in source:
    raise SystemExit("r57: r55 sync detached-exe anchor missing")
source = source.replace(sync_anchor, sync_replacement, 1)

test_anchor = '''    #[test]\n    fn r55_detached_helper_name_is_content_addressed() {\n'''
tests = r'''    #[cfg(target_os = "windows")]
    #[test]
    fn r57_migrates_only_old_main_webfetch_command() {
        let detached = Path::new(r"C:\Users\u\.codex-app-transfer\mcp-bin\codex-app-transfer-mcp-abc.exe");
        let mut old = serde_json::json!({
            "type": "stdio",
            "command": r"V:\Codex App Transfer\codex-app-transfer.exe",
            "args": ["--mcp-serve-webfetch"],
            "startup_timeout_sec": 15,
            "tool_timeout_sec": 120
        });
        assert!(migrate_webfetch_server_value_r57(&mut old, detached).is_some());
        assert_eq!(old["command"], detached.to_string_lossy().as_ref());
        assert_eq!(old["startup_timeout_sec"], 15);
        assert_eq!(old["tool_timeout_sec"], 120);

        let mut unrelated = serde_json::json!({
            "command": r"V:\Other\server.exe",
            "args": ["--mcp-serve-webfetch"]
        });
        assert!(migrate_webfetch_server_value_r57(&mut unrelated, detached).is_none());

        let mut already = serde_json::json!({
            "command": detached.to_string_lossy(),
            "args": ["--mcp-serve-webfetch"]
        });
        assert!(migrate_webfetch_server_value_r57(&mut already, detached).is_none());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn r57_migrates_matching_cwd_but_preserves_custom_cwd() {
        let detached = Path::new(r"C:\Users\u\.codex-app-transfer\mcp-bin\helper.exe");
        let mut matching = serde_json::json!({
            "command": r"V:\Codex App Transfer\codex-app-transfer.exe",
            "args": ["--mcp-serve=webfetch"],
            "cwd": r"V:\Codex App Transfer"
        });
        migrate_webfetch_server_value_r57(&mut matching, detached).unwrap();
        assert_eq!(
            matching["cwd"],
            detached.parent().unwrap().to_string_lossy().as_ref()
        );

        let mut custom = serde_json::json!({
            "command": r"V:\Codex App Transfer\codex-app-transfer.exe",
            "args": ["--mcp-serve-webfetch"],
            "cwd": r"V:\Some Project"
        });
        migrate_webfetch_server_value_r57(&mut custom, detached).unwrap();
        assert_eq!(custom["cwd"], r"V:\Some Project");
    }

'''
if test_anchor not in source:
    raise SystemExit("r57: r55 test anchor missing")
source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    MARKER,
    "migrate_cc_switch_webfetch_r57",
    "migrate_omp_native_webfetch_r57",
    "external-mcp-r57.jsonl",
    "[mcp-r57] source=cc-switch action=migrated",
    "[mcp-r57] source=omp-native action=migrated",
    "r57_migrates_only_old_main_webfetch_command",
):
    if invariant not in source:
        raise SystemExit(f"r57 external MCP source invariant missing: {invariant}")

TARGET.write_text(source, encoding="utf-8")
print("R57 EXTERNAL MCP SOURCE MIGRATION PASS")
print("- CC Switch enabled-Codex cat-webfetch rows pointing at the installed main EXE migrate to r55 detached helper")
print("- OMP native user/profile mcp.json entries with the same old command migrate too")
print("- other MCP servers, app flags, provider data, env and timeout fields are preserved")
print("- migration uses optimistic SQLite update + atomic JSON replacement and is best-effort")
print("- audit records contain command paths only, never env/header/provider secret payloads")
