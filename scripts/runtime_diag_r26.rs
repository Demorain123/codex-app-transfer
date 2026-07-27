//! CAS-RUNTIME-DIAG-R26
//!
//! Diagnostic-only watcher for long-lived Codex Desktop sessions on Windows.
//! It never restarts, kills, resumes, clears, or rewrites a Codex thread. It only
//! emits privacy-filtered lifecycle markers into the existing tracing -> proxy log bridge.

#![cfg(target_os = "windows")]

use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, SystemTime};

use windows::Win32::Foundation::CloseHandle;
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
    TH32CS_SNAPPROCESS,
};

const POLL: Duration = Duration::from_secs(2);
const MAX_READ: u64 = 1024 * 1024;
static STARTED: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug, PartialEq, Eq)]
struct ProcRow {
    pid: u32,
    ppid: u32,
    name: String,
}

#[derive(Default)]
struct TailState {
    offset: u64,
    carry: String,
}

pub fn start_runtime_diag_daemon() {
    if STARTED.swap(true, Ordering::SeqCst) {
        return;
    }
    match std::thread::Builder::new()
        .name("codex-runtime-diag-r26".into())
        .spawn(run_loop)
    {
        Ok(_) => tracing::info!(
            target: "codex_runtime_diag",
            event = "watcher_started",
            revision = 26_u64,
            poll_seconds = POLL.as_secs(),
            "r26 diagnostic-only runtime watcher started"
        ),
        Err(error) => tracing::error!(
            target: "codex_runtime_diag",
            event = "watcher_spawn_failed",
            error = %error,
            "failed to spawn r26 runtime watcher"
        ),
    }
}

fn run_loop() {
    let mut previous = HashMap::new();
    let mut tails = HashMap::new();
    loop {
        observe_processes(&mut previous);
        observe_native_logs(&mut tails);
        std::thread::sleep(POLL);
    }
}

fn snapshot_codex_processes() -> Option<Vec<ProcRow>> {
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        let mut rows = Vec::new();
        if Process32FirstW(snapshot, &mut entry).is_ok() {
            loop {
                let len = entry
                    .szExeFile
                    .iter()
                    .position(|&c| c == 0)
                    .unwrap_or(entry.szExeFile.len());
                let name = String::from_utf16_lossy(&entry.szExeFile[..len]);
                if name.eq_ignore_ascii_case("codex.exe") {
                    rows.push(ProcRow {
                        pid: entry.th32ProcessID,
                        ppid: entry.th32ParentProcessID,
                        name,
                    });
                }
                if Process32NextW(snapshot, &mut entry).is_err() {
                    break;
                }
            }
        }
        let _ = CloseHandle(snapshot);
        Some(rows)
    }
}

fn observe_processes(previous: &mut HashMap<u32, ProcRow>) {
    let Some(rows) = snapshot_codex_processes() else {
        tracing::warn!(target: "codex_runtime_diag", event = "process_snapshot_failed", "Toolhelp32 snapshot failed");
        return;
    };
    let current: HashMap<u32, ProcRow> = rows.into_iter().map(|row| (row.pid, row)).collect();
    for (pid, row) in &current {
        if !previous.contains_key(pid) {
            tracing::info!(
                target: "codex_runtime_diag",
                event = "process_started",
                pid = *pid as u64,
                ppid = row.ppid as u64,
                codex_process_count = current.len() as u64,
                "Codex runtime process started"
            );
        }
    }
    for (pid, row) in previous.iter() {
        if !current.contains_key(pid) {
            tracing::warn!(
                target: "codex_runtime_diag",
                event = "process_exited",
                pid = *pid as u64,
                ppid = row.ppid as u64,
                remaining_codex_processes = current.len() as u64,
                "Codex runtime process exited"
            );
        }
    }
    if current.len() > 1 && previous.len() <= 1 {
        tracing::warn!(
            target: "codex_runtime_diag",
            event = "multiple_codex_processes",
            codex_process_count = current.len() as u64,
            "multiple codex.exe runtime candidates detected; diagnostic only"
        );
    }
    *previous = current;
}

fn native_log_roots() -> Vec<PathBuf> {
    let Some(local) = std::env::var_os("LOCALAPPDATA") else {
        return Vec::new();
    };
    let local = PathBuf::from(local);
    let mut roots = Vec::new();
    if let Ok(entries) = fs::read_dir(local.join("Packages")) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_ascii_lowercase();
            if name.starts_with("openai.codex_") {
                let candidate = entry
                    .path()
                    .join("LocalCache")
                    .join("Local")
                    .join("Codex")
                    .join("Logs");
                if candidate.is_dir() {
                    roots.push(candidate);
                }
            }
        }
    }
    for candidate in [
        local.join("OpenAI").join("Codex").join("Logs"),
        local.join("Codex").join("Logs"),
    ] {
        if candidate.is_dir() {
            roots.push(candidate);
        }
    }
    roots
}

fn walk_logs(root: &Path, depth: usize, out: &mut Vec<PathBuf>) {
    if depth > 6 {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk_logs(&path, depth + 1, out);
        } else {
            let name = entry.file_name().to_string_lossy().to_ascii_lowercase();
            if name.starts_with("codex-desktop-") && name.ends_with(".log") {
                out.push(path);
            }
        }
    }
}

fn newest_logs() -> Vec<PathBuf> {
    let mut files = Vec::new();
    for root in native_log_roots() {
        walk_logs(&root, 0, &mut files);
    }
    files.sort_by_key(|path| {
        fs::metadata(path)
            .and_then(|m| m.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH)
    });
    files.reverse();
    files.truncate(8);
    files
}

fn observe_native_logs(tails: &mut HashMap<PathBuf, TailState>) {
    for path in newest_logs() {
        let Ok(meta) = fs::metadata(&path) else {
            continue;
        };
        let len = meta.len();
        if !tails.contains_key(&path) {
            tails.insert(
                path.clone(),
                TailState {
                    // Never replay historical log contents when r26 attaches.
                    offset: len,
                    carry: String::new(),
                },
            );
            tracing::info!(
                target: "codex_runtime_diag",
                event = "native_log_attached",
                file = %path.file_name().and_then(|s| s.to_str()).unwrap_or("<unknown>"),
                existing_bytes = len,
                "attached to Codex native log tail at EOF"
            );
            continue;
        }
        let Some(state) = tails.get_mut(&path) else {
            continue;
        };
        if len < state.offset {
            state.offset = 0;
            state.carry.clear();
            tracing::info!(target: "codex_runtime_diag", event = "native_log_rotated", "Codex native log rotated/truncated");
        }
        if len <= state.offset {
            continue;
        }
        let end = len;
        let start = end.saturating_sub(MAX_READ).max(state.offset);
        let Ok(mut file) = File::open(&path) else {
            continue;
        };
        if file.seek(SeekFrom::Start(start)).is_err() {
            continue;
        }
        let mut bytes = Vec::with_capacity((end - start) as usize);
        if file.take(MAX_READ).read_to_end(&mut bytes).is_err() {
            continue;
        }
        state.offset = start + bytes.len() as u64;
        let mut text = std::mem::take(&mut state.carry);
        text.push_str(&String::from_utf8_lossy(&bytes));
        let complete = text.ends_with('\n');
        let mut lines: Vec<&str> = text.split('\n').collect();
        if !complete {
            if let Some(last) = lines.pop() {
                state.carry = last.to_string();
            }
        }
        let file_name = path.file_name().and_then(|s| s.to_str()).unwrap_or("<unknown>");
        for line in lines {
            if !line.is_empty() {
                emit_native_event(line, file_name);
            }
        }
    }
}

fn fnv64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

fn uuid_at(bytes: &[u8]) -> bool {
    if bytes.len() != 36 {
        return false;
    }
    bytes.iter().enumerate().all(|(index, byte)| match index {
        8 | 13 | 18 | 23 => *byte == b'-',
        _ => byte.is_ascii_hexdigit(),
    })
}

fn uuid_fingerprints(line: &str) -> String {
    let bytes = line.as_bytes();
    let mut out = Vec::new();
    if bytes.len() >= 36 {
        for index in 0..=bytes.len() - 36 {
            let candidate = &bytes[index..index + 36];
            if uuid_at(candidate) {
                let fp = format!("{:08x}", (fnv64(candidate) ^ (fnv64(candidate) >> 32)) as u32);
                if !out.contains(&fp) {
                    out.push(fp);
                    if out.len() == 4 {
                        break;
                    }
                }
            }
        }
    }
    if out.is_empty() { "-".into() } else { out.join(",") }
}

fn status_from_line(lower: &str) -> u16 {
    for code in [400_u16, 401, 408, 409, 429, 500, 502, 503, 504] {
        if lower.contains(&format!(" {code} "))
            || lower.contains(&format!("status={code}"))
            || lower.contains(&format!("\"status\":{code}"))
        {
            return code;
        }
    }
    0
}

fn classify(lower: &str) -> Option<(&'static str, &'static str)> {
    for (needle, event, level) in [
        ("agent loop died unexpectedly", "agent_loop_died", "ERROR"),
        ("error submitting message", "error_submitting_message", "ERROR"),
        ("error creating task", "error_creating_task", "ERROR"),
        ("failed to start turn", "failed_to_start_turn", "ERROR"),
        ("app-server connection closed", "app_server_connection_closed", "WARN"),
        ("codex cli process exited", "cli_process_exited", "WARN"),
        ("classifiedasexpected=false", "cli_process_unexpected_exit", "WARN"),
        ("stdio_transport_spawned", "stdio_transport_spawned", "INFO"),
        ("context automatically compacted", "context_auto_compacted", "INFO"),
        ("remote_compaction_v2", "remote_compaction_v2", "WARN"),
        ("response.failed", "response_failed", "WARN"),
        ("reconnecting", "reconnecting", "WARN"),
        ("upstream request failed", "upstream_request_failed", "WARN"),
    ] {
        if lower.contains(needle) {
            return Some((event, level));
        }
    }
    if lower.contains("collabtoolcall") {
        for (needle, event) in [
            ("spawn_agent", "collab_spawn_agent"),
            ("send_input", "collab_send_input"),
            ("resume_agent", "collab_resume_agent"),
            ("close_agent", "collab_close_agent"),
            ("wait", "collab_wait"),
        ] {
            if lower.contains(needle) {
                return Some((event, "INFO"));
            }
        }
    }
    None
}

fn emit_native_event(line: &str, file_name: &str) {
    let lower = line.to_ascii_lowercase();
    let Some((event, level)) = classify(&lower) else {
        return;
    };
    let ids = uuid_fingerprints(line);
    let status = status_from_line(&lower) as u64;
    let line_fp = format!("{:016x}", fnv64(line.as_bytes()));
    match level {
        "ERROR" => tracing::error!(
            target: "codex_runtime_diag", event = %event, ids = %ids, status, line_fp = %line_fp,
            file = %file_name, "sanitized Codex native runtime event"
        ),
        "WARN" => tracing::warn!(
            target: "codex_runtime_diag", event = %event, ids = %ids, status, line_fp = %line_fp,
            file = %file_name, "sanitized Codex native runtime event"
        ),
        _ => tracing::info!(
            target: "codex_runtime_diag", event = %event, ids = %ids, status, line_fp = %line_fp,
            file = %file_name, "sanitized Codex native runtime event"
        ),
    }
}
