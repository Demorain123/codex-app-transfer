from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "src-tauri/Cargo.toml"
MAIN = ROOT / "src-tauri/src/main.rs"
OWNER = ROOT / "src-tauri/src/windows_tcp_owner.rs"
PROXY = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R38-WINDOWS-TCP-OWNER"

# windows-rs features for IP Helper + process image resolution.
body = CARGO.read_text(encoding="utf-8")
if '"Win32_NetworkManagement_IpHelper"' not in body:
    anchor = '    "Win32_System_Diagnostics_ToolHelp",\n'
    if anchor not in body:
        raise SystemExit("r38 tcp owner: Cargo windows feature anchor missing")
    body = body.replace(
        anchor,
        anchor + '    # CAS-R38-WINDOWS-TCP-OWNER: native listener PID attribution\n    "Win32_NetworkManagement_IpHelper",\n    "Win32_System_Threading",\n',
        1,
    )
    CARGO.write_text(body, encoding="utf-8")

body = MAIN.read_text(encoding="utf-8")
if "mod windows_tcp_owner;" not in body:
    anchor = '#[cfg(target_os = "windows")]\nmod windows_msix;\n'
    if anchor not in body:
        raise SystemExit("r38 tcp owner: main module anchor missing")
    body = body.replace(
        anchor,
        '#[cfg(target_os = "windows")]\nmod windows_tcp_owner; // CAS-R38-WINDOWS-TCP-OWNER\n' + anchor,
        1,
    )
    MAIN.write_text(body, encoding="utf-8")

OWNER.write_text(r'''//! CAS-R38-WINDOWS-TCP-OWNER
//! Native, read-only attribution for an IPv4 TCP listening port.
//! Uses GetExtendedTcpTable(TCP_TABLE_OWNER_PID_LISTENER); never kills or mutates owners.

use std::ffi::c_void;
use std::net::Ipv4Addr;
use std::path::Path;

use serde::Serialize;
use windows::core::PWSTR;
use windows::Win32::Foundation::CloseHandle;
use windows::Win32::NetworkManagement::IpHelper::{
    GetExtendedTcpTable, MIB_TCPTABLE_OWNER_PID, TCP_TABLE_OWNER_PID_LISTENER,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};

const AF_INET_U32: u32 = 2;
const NO_ERROR: u32 = 0;
const ERROR_INSUFFICIENT_BUFFER_U32: u32 = 122;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TcpListenerOwner {
    pub local_addr: String,
    pub local_port: u16,
    pub pid: u32,
    pub process_alive: bool,
    pub executable: Option<String>,
}

fn process_basename_from_snapshot(pid: u32) -> Option<String> {
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        let mut found = None;
        if Process32FirstW(snapshot, &mut entry).is_ok() {
            loop {
                if entry.th32ProcessID == pid {
                    let len = entry
                        .szExeFile
                        .iter()
                        .position(|&c| c == 0)
                        .unwrap_or(entry.szExeFile.len());
                    found = Some(String::from_utf16_lossy(&entry.szExeFile[..len]));
                    break;
                }
                if Process32NextW(snapshot, &mut entry).is_err() {
                    break;
                }
            }
        }
        let _ = CloseHandle(snapshot);
        found
    }
}

fn process_image_basename(pid: u32) -> Option<String> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buf = vec![0u16; 32768];
        let mut size = buf.len() as u32;
        let result = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buf.as_mut_ptr()),
            &mut size,
        );
        let _ = CloseHandle(handle);
        if result.is_err() || size == 0 {
            return None;
        }
        let full = String::from_utf16_lossy(&buf[..size as usize]);
        Path::new(&full)
            .file_name()
            .and_then(|s| s.to_str())
            .map(str::to_owned)
    }
}

pub fn listener_owner(port: u16) -> Result<Option<TcpListenerOwner>, String> {
    unsafe {
        let mut bytes = 0u32;
        let first = GetExtendedTcpTable(
            None,
            &mut bytes,
            false,
            AF_INET_U32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if first != NO_ERROR && first != ERROR_INSUFFICIENT_BUFFER_U32 {
            return Err(format!("GetExtendedTcpTable(size) failed: {first}"));
        }
        if bytes == 0 {
            return Ok(None);
        }

        // u32 backing keeps the buffer at least 4-byte aligned for the MIB structures.
        let words = (bytes as usize).div_ceil(std::mem::size_of::<u32>());
        let mut storage = vec![0u32; words];
        let second = GetExtendedTcpTable(
            Some(storage.as_mut_ptr().cast::<c_void>()),
            &mut bytes,
            false,
            AF_INET_U32,
            TCP_TABLE_OWNER_PID_LISTENER,
            0,
        );
        if second != NO_ERROR {
            return Err(format!("GetExtendedTcpTable(data) failed: {second}"));
        }

        let table = &*(storage.as_ptr().cast::<MIB_TCPTABLE_OWNER_PID>());
        let rows = std::slice::from_raw_parts(table.table.as_ptr(), table.dwNumEntries as usize);
        for row in rows {
            let row_port = u16::from_be((row.dwLocalPort & 0xffff) as u16);
            if row_port != port {
                continue;
            }
            let ip = Ipv4Addr::from(u32::from_be(row.dwLocalAddr));
            // Transfer binds loopback. Also accept 0.0.0.0 because an external wildcard listener
            // blocks the same local port and is equally important attribution evidence.
            if ip != Ipv4Addr::LOCALHOST && ip != Ipv4Addr::UNSPECIFIED {
                continue;
            }
            let snapshot_name = process_basename_from_snapshot(row.dwOwningPid);
            let process_alive = snapshot_name.is_some();
            let executable = process_image_basename(row.dwOwningPid).or(snapshot_name);
            return Ok(Some(TcpListenerOwner {
                local_addr: ip.to_string(),
                local_port: row_port,
                pid: row.dwOwningPid,
                process_alive,
                executable,
            }));
        }
        Ok(None)
    }
}

pub fn listener_owner_evidence(port: u16) -> String {
    match listener_owner(port) {
        Ok(Some(owner)) => format!(
            "owner_pid={} owner_alive={} owner_exe={} owner_addr={}:{}",
            owner.pid,
            owner.process_alive,
            owner.executable.as_deref().unwrap_or("<unresolved>"),
            owner.local_addr,
            owner.local_port,
        ),
        Ok(None) => "owner_pid=<none> owner_alive=false owner_exe=<none>".to_owned(),
        Err(error) => format!("owner_probe_error={error}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn native_owner_table_finds_this_process_listener() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind fixture listener");
        let port = listener.local_addr().expect("fixture addr").port();
        let mut found = None;
        for _ in 0..20 {
            found = listener_owner(port).expect("owner table query");
            if found.is_some() { break; }
            thread::sleep(Duration::from_millis(25));
        }
        let owner = found.expect("listener must appear in owner PID table");
        assert_eq!(owner.pid, std::process::id());
        assert!(owner.process_alive);
        drop(listener);
    }
}
''', encoding="utf-8")

# Enrich bind failures and stale-release telemetry without changing recovery semantics.
body = PROXY.read_text(encoding="utf-8")
if MARKER not in body:
    anchor = '''fn lifecycle_log(level: &str, message: impl Into<String>) {
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, format!("[proxy-lifecycle-r38] {}", message.into()));
}
'''
    helper = '''fn lifecycle_log(level: &str, message: impl Into<String>) {
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, format!("[proxy-lifecycle-r38] {}", message.into()));
}

// CAS-R38-WINDOWS-TCP-OWNER
fn port_owner_evidence(port: u16) -> String {
    #[cfg(target_os = "windows")]
    {
        return crate::windows_tcp_owner::listener_owner_evidence(port);
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = port;
        "owner_probe=windows_only".to_owned()
    }
}
'''
    if anchor not in body:
        raise SystemExit("r38 tcp owner: lifecycle_log anchor missing")
    body = body.replace(anchor, helper, 1)

    old = '''                    let listener = tokio::net::TcpListener::bind(format!("127.0.0.1:{port}"))
                        .await
                        .map_err(|e| format!("bind 127.0.0.1:{port} failed: {e}"))?;
'''
    new = '''                    let listener = match tokio::net::TcpListener::bind(format!("127.0.0.1:{port}")).await {
                        Ok(listener) => listener,
                        Err(e) => {
                            let evidence = port_owner_evidence(port);
                            lifecycle_log(
                                "ERROR",
                                format!(
                                    "bind_failed app_pid={} requested_port={port} os_error={:?} {evidence}",
                                    std::process::id(),
                                    e.raw_os_error(),
                                ),
                            );
                            return Err(format!("bind 127.0.0.1:{port} failed: {e}; {evidence}"));
                        }
                    };
'''
    if old not in body:
        raise SystemExit("r38 tcp owner: bind error anchor missing")
    body = body.replace(old, new, 1)

    old = '''    let released = wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT);
    lifecycle_log(
        if released { "INFO" } else { "ERROR" },
        format!(
            "{} listener_id={} app_pid={} addr={} wait_ms={}",
            if released { "port_release_verified" } else { "stale_listener_detected" },
            h.listener_id,
            pid,
            h.addr,
            PORT_RELEASE_WAIT.as_millis()
        ),
    );
'''
    new = '''    let released = wait_until_port_bindable(h.addr, PORT_RELEASE_WAIT);
    let owner_evidence = if released {
        "owner_pid=<none>".to_owned()
    } else {
        port_owner_evidence(h.addr.port())
    };
    lifecycle_log(
        if released { "INFO" } else { "ERROR" },
        format!(
            "{} listener_id={} app_pid={} addr={} wait_ms={} {owner_evidence}",
            if released { "port_release_verified" } else { "stale_listener_detected" },
            h.listener_id,
            pid,
            h.addr,
            PORT_RELEASE_WAIT.as_millis()
        ),
    );
'''
    if old not in body:
        raise SystemExit("r38 tcp owner: release telemetry anchor missing")
    body = body.replace(old, new, 1)
    PROXY.write_text(body, encoding="utf-8")

checks = {
    CARGO: ["Win32_NetworkManagement_IpHelper", "Win32_System_Threading"],
    MAIN: ["mod windows_tcp_owner"],
    OWNER: [MARKER, "GetExtendedTcpTable", "TCP_TABLE_OWNER_PID_LISTENER", "native_owner_table_finds_this_process_listener"],
    PROXY: [MARKER, "owner_pid=", "bind_failed", "port_owner_evidence"],
}
for path, tokens in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"r38 tcp owner missing {token} in {path.relative_to(ROOT)}")

print("r38 Windows TCP owner attribution: applied")
