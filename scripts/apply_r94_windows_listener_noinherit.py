from __future__ import annotations

# R94 Windows fixed-port listener inheritance hardening.
#
# A dead binder PID + still-LISTENING endpoint can occur when a descendant
# process inherited the listening socket handle. Windows continues to attribute
# the TCP row to the process that issued the original context bind even after
# that process exits. The only durable fix is prevention: explicitly clear
# HANDLE_FLAG_INHERIT on the bound socket before any child/descendant launch can
# inherit it. Keep the configured fixed port; do not port-hop, kill unrelated
# processes, or use SO_REUSEADDR.

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-R94-WINDOWS-LISTENER-NOINHERIT"

body = TARGET.read_text(encoding="utf-8")
if MARKER in body:
    print("R94 WINDOWS LISTENER NO-INHERIT PASS (already applied)")
    raise SystemExit(0)

if "CAS-R39-PROXY-OWNER-THREAD" not in body:
    raise SystemExit("r94 listener no-inherit: r39 owner-thread must be materialized first")

import_anchor = """use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

"""
import_replacement = """use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use std::os::windows::io::AsRawSocket;
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::{
    GetHandleInformation, SetHandleInformation, HANDLE, HANDLE_FLAGS, HANDLE_FLAG_INHERIT,
};

"""
if import_anchor not in body:
    raise SystemExit("r94 listener no-inherit: import anchor missing")
body = body.replace(import_anchor, import_replacement, 1)

helper_anchor = """fn lifecycle_log(level: &str, message: impl Into<String>) {
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, format!("[proxy-lifecycle-r39] {}", message.into()));
}

"""
helper = """fn lifecycle_log(level: &str, message: impl Into<String>) {
    codex_app_transfer_proxy::proxy_telemetry()
        .logs
        .add(level, format!("[proxy-lifecycle-r39] {}", message.into()));
}

// CAS-R94-WINDOWS-LISTENER-NOINHERIT
//
// Rust normally creates non-inheritable sockets when possible, but this is an
// explicit Windows fixed-port safety barrier. A long-lived descendant must
// never keep the Transfer listener alive after the original binder exits.
#[cfg(target_os = "windows")]
fn harden_listener_handle_inheritance(listener: &tokio::net::TcpListener) -> Result<(), String> {
    let raw = listener.as_raw_socket();
    let handle = HANDLE(raw as usize as *mut core::ffi::c_void);

    unsafe {
        SetHandleInformation(handle, HANDLE_FLAG_INHERIT.0, HANDLE_FLAGS(0))
            .map_err(|error| format!("clear listener HANDLE_FLAG_INHERIT failed: {error}"))?;

        let mut flags = 0u32;
        GetHandleInformation(handle, &mut flags)
            .map_err(|error| format!("verify listener HANDLE_FLAG_INHERIT failed: {error}"))?;

        if flags & HANDLE_FLAG_INHERIT.0 != 0 {
            return Err(format!(
                "listener handle remained inheritable after SetHandleInformation: flags=0x{flags:08x}"
            ));
        }
    }

    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn harden_listener_handle_inheritance(_listener: &tokio::net::TcpListener) -> Result<(), String> {
    Ok(())
}

"""
if helper_anchor not in body:
    raise SystemExit("r94 listener no-inherit: lifecycle helper anchor missing")
body = body.replace(helper_anchor, helper, 1)

call_anchor = """                let addr = match listener.local_addr() {
"""
call_block = """                if let Err(error) = harden_listener_handle_inheritance(&listener) {
                    lifecycle_log(
                        "ERROR",
                        format!(
                            "listener_inherit_guard_failed listener_id={listener_id} app_pid={} requested_port={port} error={error}",
                            std::process::id()
                        ),
                    );
                    let _ = ready_tx.send(Err(format!(
                        "proxy listener inheritance hardening failed for 127.0.0.1:{port}: {error}"
                    )));
                    drop(listener);
                    rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                    lifecycle_log(
                        "INFO",
                        format!(
                            "owner_thread_exit listener_id={listener_id} app_pid={} reason=inherit_guard_failed",
                            std::process::id()
                        ),
                    );
                    return;
                }
                lifecycle_log(
                    "INFO",
                    format!(
                        "listener_inherit_guard_verified listener_id={listener_id} app_pid={} requested_port={port} inheritable=false",
                        std::process::id()
                    ),
                );

                let addr = match listener.local_addr() {
"""
if call_anchor not in body:
    raise SystemExit("r94 listener no-inherit: listener local_addr anchor missing")
body = body.replace(call_anchor, call_block, 1)

for invariant in (
    MARKER,
    "AsRawSocket",
    "SetHandleInformation",
    "GetHandleInformation",
    "HANDLE_FLAG_INHERIT",
    "harden_listener_handle_inheritance(&listener)",
    "listener_inherit_guard_verified",
    "listener_inherit_guard_failed",
    "inheritable=false",
):
    if invariant not in body:
        raise SystemExit(f"r94 listener no-inherit invariant missing: {invariant}")

TARGET.write_text(body, encoding="utf-8")
print("R94_WINDOWS_LISTENER_NOINHERIT_PASS")
print("- fixed Transfer port remains fixed; no automatic port hopping")
print("- Windows listener HANDLE_FLAG_INHERIT is explicitly cleared and read-back verified")
print("- startup fails closed if the listener cannot be proven non-inheritable")
print("- no process killing and no SO_REUSEADDR workaround")
