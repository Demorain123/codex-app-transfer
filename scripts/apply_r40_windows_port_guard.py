from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "src-tauri/src/windows_tcp_owner.rs"
PROXY = ROOT / "src-tauri/src/proxy_runner.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R40-WINDOWS-PORT-GUARD"


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r40 port guard: {label} anchor count={count}, expected 1")
    return body.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Windows native helpers: classify the listener binder and verify/harden the
# actual socket HANDLE against accidental child-process inheritance.
# ---------------------------------------------------------------------------
body = OWNER.read_text(encoding="utf-8")
if MARKER not in body:
    body = replace_once(
        body,
        "//! CAS-R38-WINDOWS-TCP-OWNER\n",
        "//! CAS-R38-WINDOWS-TCP-OWNER\n//! CAS-R40-WINDOWS-PORT-GUARD\n",
        "owner module marker",
    )
    body = replace_once(
        body,
        "use windows::Win32::Foundation::CloseHandle;\n",
        "use windows::Win32::Foundation::{\n"
        "    CloseHandle, GetHandleInformation, SetHandleInformation, HANDLE, HANDLE_FLAGS,\n"
        "    HANDLE_FLAG_INHERIT,\n"
        "};\n",
        "Foundation imports",
    )

    struct_anchor = '''pub struct TcpListenerOwner {
    pub local_addr: String,
    pub local_port: u16,
    pub pid: u32,
    pub process_alive: bool,
    pub executable: Option<String>,
}
'''
    struct_replacement = struct_anchor + r'''

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SocketInheritanceGuard {
    pub inheritable_before: bool,
    pub inheritable_after: bool,
    pub corrected: bool,
}

fn owner_class(owner: &TcpListenerOwner, expected_pid: u32) -> &'static str {
    if owner.process_alive && owner.pid == expected_pid {
        "self_live"
    } else if owner.process_alive {
        "foreign_live"
    } else {
        // GetExtendedTcpTable reports the context-bind PID. If that process has
        // disappeared while LISTEN still exists, do not claim the dead PID is
        // necessarily the final kernel handle owner.
        "stale_binder"
    }
}

/// Verify that a listening socket cannot leak into a child process. Modern Tokio/
/// socket2 already creates Windows sockets non-inheritable; this is a runtime
/// assertion and repair barrier in case that invariant changes or another creation
/// path reaches this code in the future.
pub fn harden_socket_inheritance(raw_socket: usize) -> Result<SocketInheritanceGuard, String> {
    unsafe {
        let handle = HANDLE(raw_socket as *mut c_void);
        let mut flags = 0u32;
        GetHandleInformation(handle, &mut flags)
            .map_err(|e| format!("GetHandleInformation(socket) failed: {e}"))?;
        let inheritable_before = flags & HANDLE_FLAG_INHERIT.0 != 0;
        let mut corrected = false;

        if inheritable_before {
            SetHandleInformation(handle, HANDLE_FLAG_INHERIT.0, HANDLE_FLAGS(0))
                .map_err(|e| format!("SetHandleInformation(clear inherit) failed: {e}"))?;
            corrected = true;
        }

        let mut after_flags = 0u32;
        GetHandleInformation(handle, &mut after_flags)
            .map_err(|e| format!("GetHandleInformation(socket verify) failed: {e}"))?;
        let inheritable_after = after_flags & HANDLE_FLAG_INHERIT.0 != 0;
        if inheritable_after {
            return Err("listener socket remained inheritable after hardening".to_owned());
        }

        Ok(SocketInheritanceGuard {
            inheritable_before,
            inheritable_after,
            corrected,
        })
    }
}
'''
    body = replace_once(body, struct_anchor, struct_replacement, "owner structs")

    evidence_old = r'''pub fn listener_owner_evidence(port: u16) -> String {
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
'''
    evidence_new = r'''pub fn listener_owner_evidence_for(port: u16, expected_pid: u32) -> String {
    match listener_owner(port) {
        Ok(Some(owner)) => format!(
            "owner_class={} owner_pid={} owner_alive={} owner_exe={} owner_addr={}:{} recommended_action={}",
            owner_class(&owner, expected_pid),
            owner.pid,
            owner.process_alive,
            owner.executable.as_deref().unwrap_or("<unresolved>"),
            owner.local_addr,
            owner.local_port,
            match owner_class(&owner, expected_pid) {
                "self_live" => "inspect_internal_lifecycle",
                "foreign_live" => "stop_foreign_owner_safely",
                "stale_binder" => "preserve_evidence_no_pid_kill",
                _ => "inspect",
            },
        ),
        Ok(None) => "owner_class=no_listener owner_pid=<none> owner_alive=false owner_exe=<none> recommended_action=retry_once_after_reprobe".to_owned(),
        Err(error) => format!("owner_class=probe_error owner_probe_error={error} recommended_action=preserve_evidence"),
    }
}

pub fn listener_owner_evidence(port: u16) -> String {
    listener_owner_evidence_for(port, std::process::id())
}
'''
    body = replace_once(body, evidence_old, evidence_new, "classified owner evidence")

    test_insert = r'''

    #[cfg(target_os = "windows")]
    #[test]
    fn windows_port_guard_r40_clears_inherit_bit() {
        use std::os::windows::io::AsRawSocket;

        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind guard fixture");
        let raw = listener.as_raw_socket() as usize;
        unsafe {
            SetHandleInformation(
                HANDLE(raw as *mut c_void),
                HANDLE_FLAG_INHERIT.0,
                HANDLE_FLAG_INHERIT,
            )
            .expect("force fixture socket inheritable");
        }
        let guard = harden_socket_inheritance(raw).expect("harden listener inheritance");
        assert!(guard.inheritable_before);
        assert!(guard.corrected);
        assert!(!guard.inheritable_after);
    }

    #[test]
    fn windows_port_guard_r40_classifies_foreign_and_stale_binders() {
        let live = TcpListenerOwner {
            local_addr: "127.0.0.1".to_owned(),
            local_port: 18089,
            pid: 4242,
            process_alive: true,
            executable: Some("pwsh.exe".to_owned()),
        };
        assert_eq!(owner_class(&live, 1111), "foreign_live");
        assert_eq!(owner_class(&live, 4242), "self_live");

        let stale = TcpListenerOwner { process_alive: false, ..live };
        assert_eq!(owner_class(&stale, 1111), "stale_binder");
    }
'''
    test_anchor = '''        assert!(owner.process_alive);
        drop(listener);
    }
}
'''
    test_replacement = '''        assert!(owner.process_alive);
        drop(listener);
    }
''' + test_insert + '''}
'''
    body = replace_once(body, test_anchor, test_replacement, "r40 native tests")
    OWNER.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Owner thread: audit the real Tokio listener HANDLE before publishing it.
# ---------------------------------------------------------------------------
body = PROXY.read_text(encoding="utf-8")
if MARKER not in body:
    body = replace_once(
        body,
        "//! CAS-R39-PROXY-OWNER-THREAD\n",
        "//! CAS-R39-PROXY-OWNER-THREAD\n//! CAS-R40-WINDOWS-PORT-GUARD\n",
        "proxy marker",
    )
    body = replace_once(
        body,
        "use std::time::{Duration, Instant};\n",
        "use std::time::{Duration, Instant};\n"
        "#[cfg(target_os = \"windows\")]\n"
        "use std::os::windows::io::AsRawSocket;\n",
        "AsRawSocket import",
    )
    body = replace_once(
        body,
        "        return crate::windows_tcp_owner::listener_owner_evidence(port);\n",
        "        return crate::windows_tcp_owner::listener_owner_evidence_for(port, std::process::id());\n",
        "classified owner evidence call",
    )

    addr_anchor = '''                let addr = match listener.local_addr() {
'''
    guard_block = r'''                #[cfg(target_os = "windows")]
                {
                    let raw_socket = listener.as_raw_socket() as usize;
                    match crate::windows_tcp_owner::harden_socket_inheritance(raw_socket) {
                        Ok(guard) => lifecycle_log(
                            if guard.corrected { "WARN" } else { "INFO" },
                            format!(
                                "listener_handle_guard listener_id={listener_id} app_pid={} raw_socket={} inherit_before={} inherit_after={} corrected={}",
                                std::process::id(),
                                raw_socket,
                                guard.inheritable_before,
                                guard.inheritable_after,
                                guard.corrected,
                            ),
                        ),
                        Err(error) => {
                            lifecycle_log(
                                "ERROR",
                                format!(
                                    "listener_handle_guard_failed listener_id={listener_id} app_pid={} error={error}",
                                    std::process::id()
                                ),
                            );
                            let _ = ready_tx.send(Err(format!(
                                "Windows listener handle inheritance audit failed: {error}"
                            )));
                            drop(listener);
                            rt.shutdown_timeout(RUNTIME_FORCE_WAIT);
                            lifecycle_log(
                                "INFO",
                                format!(
                                    "owner_thread_exit listener_id={listener_id} app_pid={} reason=handle_guard_failed",
                                    std::process::id()
                                ),
                            );
                            return;
                        }
                    }
                }

'''
    body = replace_once(body, addr_anchor, guard_block + addr_anchor, "listener handle guard")
    PROXY.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Chain health: surface the classification in a form users can act on without
# dangerous automatic process killing or port switching.
# ---------------------------------------------------------------------------
body = CHAIN.read_text(encoding="utf-8")
if "CAS-R40-PORT-OWNER-CLASSIFICATION" not in body:
    live_old = '''                .fact(format!("owner_pid={} owner_alive=true", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<unresolved>")
                )),
'''
    live_new = '''                // CAS-R40-PORT-OWNER-CLASSIFICATION
                .fact("owner_class=foreign_live")
                .fact(format!("owner_pid={} owner_alive=true", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<unresolved>")
                ))
                .fact("recommended_action=stop_foreign_owner_safely"),
'''
    body = replace_once(body, live_old, live_new, "live owner health classification")
    body = body.replace(
        '.fact("classification=unresolved_listener_residue"),',
        '.fact("classification=unresolved_listener_residue")\n                .fact("owner_class=stale_binder")\n                .fact("recommended_action=preserve_evidence_no_pid_kill"),',
        1,
    )
    CHAIN.write_text(body, encoding="utf-8")


checks = {
    OWNER: [
        MARKER,
        "GetHandleInformation",
        "SetHandleInformation",
        "HANDLE_FLAG_INHERIT",
        "harden_socket_inheritance",
        "owner_class=",
        "foreign_live",
        "stale_binder",
        "windows_port_guard_r40_clears_inherit_bit",
    ],
    PROXY: [
        MARKER,
        "AsRawSocket",
        "listener_handle_guard",
        "listener_handle_guard_failed",
        "listener_owner_evidence_for",
    ],
    CHAIN: [
        "CAS-R40-PORT-OWNER-CLASSIFICATION",
        "owner_class=foreign_live",
        "owner_class=stale_binder",
        "recommended_action=stop_foreign_owner_safely",
        "recommended_action=preserve_evidence_no_pid_kill",
    ],
}
for path, tokens in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"r40 port guard missing {token} in {path.relative_to(ROOT)}")

print("r40 Windows port guard: socket inheritance hardening + classified owner evidence applied")
