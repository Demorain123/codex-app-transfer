from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
MARKER = "CAS-R55-DETACHED-MCP-HELPER"

source = TARGET.read_text(encoding="utf-8")
if MARKER in source:
    print("r55 detached MCP helper already applied")
    raise SystemExit(0)

import_anchor = "use serde::{Deserialize, Serialize};\nuse toml_edit::{value, Array, DocumentMut, Item, Table};\n"
import_replacement = "use serde::{Deserialize, Serialize};\nuse sha2::{Digest, Sha256};\nuse toml_edit::{value, Array, DocumentMut, Item, Table};\n"
if import_anchor not in source:
    raise SystemExit("r55 detached MCP helper: import anchor missing")
source = source.replace(import_anchor, import_replacement, 1)

comment_anchor = "/// 注册 transfer 自己的 web_fetch MCP server(`command` = 本二进制绝对路径 + `--mcp-serve-webfetch`)。\n"
helper_code = r'''// CAS-R55-DETACHED-MCP-HELPER
//
// Windows does not allow an installer/updater to replace or remove an executable while
// another process is running that image.  `cat-webfetch` used to register the *main*
// installed codex-app-transfer.exe as its stdio MCP command, so long-lived hosts (for
// example OMP) could keep the installation executable mapped even after the GUI exited.
//
// Materialize a content-addressed byte-for-byte helper copy under the user's Transfer
// data directory and register that path instead.  The helper is the same binary and is
// still entered with `--mcp-serve-webfetch`, but it no longer lives in the installation
// directory.  Content-addressed names let an update create a new helper even while an
// older helper is still running/locked.  Stale helpers are removed best-effort once they
// are no longer locked.
const DETACHED_MCP_HELPER_PREFIX_R55: &str = "codex-app-transfer-mcp-";

fn detached_mcp_helper_name_r55(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let fingerprint = digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    if cfg!(target_os = "windows") {
        format!("{DETACHED_MCP_HELPER_PREFIX_R55}{fingerprint}.exe")
    } else {
        format!("{DETACHED_MCP_HELPER_PREFIX_R55}{fingerprint}")
    }
}

#[cfg(target_os = "windows")]
fn detached_web_fetch_exe_r55() -> Result<PathBuf, String> {
    let source_exe = std::env::current_exe()
        .map_err(|e| format!("拿不到自身可执行路径: {e}"))?;
    let source_bytes = fs::read(&source_exe)
        .map_err(|e| format!("读取 MCP helper 源二进制失败: {e}"))?;
    let source_digest = Sha256::digest(&source_bytes);

    let home = resolve_home().ok_or_else(|| "HOME / USERPROFILE not set".to_owned())?;
    let helper_dir = home.join(".codex-app-transfer").join("mcp-bin");
    fs::create_dir_all(&helper_dir)
        .map_err(|e| format!("创建 MCP helper 目录失败: {e}"))?;

    let helper_name = detached_mcp_helper_name_r55(&source_bytes);
    let helper_path = helper_dir.join(&helper_name);

    let helper_is_current = fs::read(&helper_path)
        .ok()
        .map(|bytes| Sha256::digest(&bytes)[..] == source_digest[..])
        .unwrap_or(false);

    if !helper_is_current {
        // A content-addressed path should normally be absent.  If a corrupt/incomplete
        // file exists, remove it if possible; a locked mismatch is surfaced rather than
        // silently registering unverified bytes.
        if helper_path.exists() {
            fs::remove_file(&helper_path)
                .map_err(|e| format!("替换损坏的 MCP helper 失败: {e}"))?;
        }
        let temp_path = helper_dir.join(format!(
            ".{helper_name}.{}.tmp",
            std::process::id()
        ));
        fs::write(&temp_path, &source_bytes)
            .map_err(|e| format!("写入 MCP helper 临时文件失败: {e}"))?;
        match fs::rename(&temp_path, &helper_path) {
            Ok(()) => {}
            Err(rename_error) if helper_path.exists() => {
                // Another GUI instance may have won the same content-addressed race.
                let _ = fs::remove_file(&temp_path);
                let winner = fs::read(&helper_path)
                    .map_err(|e| format!("读取并发生成的 MCP helper 失败: {e}"))?;
                if Sha256::digest(&winner)[..] != source_digest[..] {
                    return Err(format!(
                        "并发生成的 MCP helper 校验失败: {rename_error}"
                    ));
                }
            }
            Err(rename_error) => {
                let _ = fs::remove_file(&temp_path);
                return Err(format!("提交 MCP helper 失败: {rename_error}"));
            }
        }
    }

    // Best-effort GC.  A helper still serving an old host is expected to be locked on
    // Windows; leave it alone and retry on a later GUI startup.  This never blocks the
    // current registration or installation directory cleanup.
    if let Ok(entries) = fs::read_dir(&helper_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path == helper_path {
                continue;
            }
            let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
                continue;
            };
            if name.starts_with(DETACHED_MCP_HELPER_PREFIX_R55)
                && name.to_ascii_lowercase().ends_with(".exe")
            {
                let _ = fs::remove_file(path);
            }
        }
    }

    tracing::info!(
        "[mcp-r55] action=detached_helper_ready helper={} source_install_exe_detached=true",
        helper_name
    );
    Ok(helper_path)
}

#[cfg(not(target_os = "windows"))]
fn detached_web_fetch_exe_r55() -> Result<PathBuf, String> {
    // The install-lock failure is Windows-specific.  Keep the existing command path on
    // other platforms until there is a demonstrated need to change their lifecycle.
    std::env::current_exe().map_err(|e| format!("拿不到自身可执行路径: {e}"))
}

'''
if comment_anchor not in source:
    raise SystemExit("r55 detached MCP helper: registration comment anchor missing")
source = source.replace(
    comment_anchor,
    helper_code
    + "/// 注册 transfer 自己的 web_fetch MCP server。Windows r55 起 command 指向用户数据目录的\n"
      "/// content-addressed detached helper；其它平台仍用当前二进制。统一追加 `--mcp-serve-webfetch`。\n",
    1,
)

exe_anchor = '''    let exe = std::env::current_exe()
        .map_err(|e| format!("拿不到自身可执行路径: {e}"))?
        .to_string_lossy()
        .to_string();
'''
exe_replacement = '''    let exe = detached_web_fetch_exe_r55()?
        .to_string_lossy()
        .to_string();
'''
if exe_anchor not in source:
    raise SystemExit("r55 detached MCP helper: current_exe registration anchor missing")
source = source.replace(exe_anchor, exe_replacement, 1)

test_anchor = '''    #[test]
    fn validate_spec_rejects_shell_commands() {
'''
tests = r'''    #[test]
    fn r55_detached_helper_name_is_content_addressed() {
        let a1 = detached_mcp_helper_name_r55(b"binary-a");
        let a2 = detached_mcp_helper_name_r55(b"binary-a");
        let b = detached_mcp_helper_name_r55(b"binary-b");
        assert_eq!(a1, a2);
        assert_ne!(a1, b);
        assert!(a1.starts_with(DETACHED_MCP_HELPER_PREFIX_R55));
        if cfg!(target_os = "windows") {
            assert!(a1.ends_with(".exe"));
        }
    }

'''
if test_anchor not in source:
    raise SystemExit("r55 detached MCP helper: tests anchor missing")
source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    "CAS-R55-DETACHED-MCP-HELPER",
    "detached_web_fetch_exe_r55",
    "detached_mcp_helper_name_r55",
    ".codex-app-transfer\").join(\"mcp-bin",
    "[mcp-r55] action=detached_helper_ready",
    "r55_detached_helper_name_is_content_addressed",
):
    if invariant not in source:
        raise SystemExit(f"r55 detached MCP helper invariant missing: {invariant}")

TARGET.write_text(source, encoding="utf-8")
print("R55 DETACHED MCP HELPER PASS")
print("- Windows cat-webfetch command now points to a user-data content-addressed helper copy")
print("- OMP/Codex may keep the helper running without locking the installed main executable")
print("- updates create a new helper filename instead of overwriting a running old helper")
print("- stale unlocked helpers are garbage-collected best-effort")
print("- non-Windows MCP registration behavior remains unchanged")
