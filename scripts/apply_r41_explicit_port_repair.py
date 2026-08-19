from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "src-tauri/src/windows_tcp_owner.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-R41-EXPLICIT-PORT-REPAIR"


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r41 explicit repair: {label} anchor count={count}, expected 1")
    return body.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Windows owner helper: an explicit user-triggered repair may terminate ONLY a
# currently revalidated, live, foreign process that still owns the configured
# listener. It never terminates self/System/protected core processes and never
# acts on a stale/dead binder PID.
# ---------------------------------------------------------------------------
body = OWNER.read_text(encoding="utf-8")
if MARKER not in body:
    body = replace_once(
        body,
        "//! CAS-R40-WINDOWS-PORT-GUARD\n",
        "//! CAS-R40-WINDOWS-PORT-GUARD\n//! CAS-R41-EXPLICIT-PORT-REPAIR\n",
        "owner marker",
    )
    body = replace_once(
        body,
        "use std::path::Path;\n",
        "use std::path::Path;\nuse std::time::Duration;\n",
        "Duration import",
    )
    body = replace_once(
        body,
        "use windows::Win32::System::Threading::{\n    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,\n};\n",
        "use windows::Win32::System::Threading::{\n"
        "    OpenProcess, QueryFullProcessImageNameW, TerminateProcess, PROCESS_NAME_WIN32,\n"
        "    PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE,\n"
        "};\n",
        "Threading imports",
    )

    anchor = '''pub fn listener_owner_evidence_for(port: u16, expected_pid: u32) -> String {\n'''
    helper = r'''const R41_REPAIR_EXIT_CODE: u32 = 0xC041;

fn protected_repair_owner_name(name: &str) -> bool {
    matches!(
        name.to_ascii_lowercase().as_str(),
        "system"
            | "registry"
            | "smss.exe"
            | "csrss.exe"
            | "wininit.exe"
            | "services.exe"
            | "lsass.exe"
            | "svchost.exe"
    )
}

/// CAS-R41-EXPLICIT-PORT-REPAIR
///
/// Release a configured loopback listener by terminating its currently-live
/// foreign process owner. This function is deliberately suitable only for the
/// explicit UI recovery path: callers must pass the PID that was shown to the
/// user/health snapshot, and the function re-reads the TCP owner immediately
/// before termination to defend against a changed owner. Stale/dead PIDs are
/// evidence only and are never used as kill targets.
pub fn terminate_live_foreign_listener_owner(
    port: u16,
    expected_pid: u32,
) -> Result<String, String> {
    if expected_pid == 0 || expected_pid <= 4 {
        return Err(format!("refusing protected/system PID {expected_pid}"));
    }
    if expected_pid == std::process::id() {
        return Err(format!(
            "refusing to terminate current app PID {expected_pid}; inspect internal lifecycle instead"
        ));
    }

    let before = listener_owner(port)?
        .ok_or_else(|| format!("port {port} is already free"))?;
    if before.pid != expected_pid {
        return Err(format!(
            "listener owner changed before repair: expected PID {expected_pid}, now PID {}",
            before.pid
        ));
    }
    if !before.process_alive {
        return Err(format!(
            "listener binder PID {expected_pid} is no longer alive; preserve stale-binder evidence"
        ));
    }
    let executable = before
        .executable
        .clone()
        .ok_or_else(|| format!("refusing to terminate unresolved PID {expected_pid}"))?;
    if protected_repair_owner_name(&executable) {
        return Err(format!(
            "refusing to terminate protected process {executable} (PID {expected_pid})"
        ));
    }

    unsafe {
        let handle = OpenProcess(PROCESS_TERMINATE, false, expected_pid)
            .map_err(|e| format!("OpenProcess(PROCESS_TERMINATE, pid={expected_pid}) failed: {e}"))?;

        // Revalidate after obtaining the process handle. If the configured port
        // was released/rebound in the meantime, do not terminate anything.
        let recheck = listener_owner(port);
        let target_still_matches = match recheck {
            Ok(Some(owner)) => {
                owner.pid == expected_pid
                    && owner.process_alive
                    && owner
                        .executable
                        .as_deref()
                        .map(|name| name.eq_ignore_ascii_case(&executable))
                        .unwrap_or(false)
            }
            _ => false,
        };
        if !target_still_matches {
            let _ = CloseHandle(handle);
            return Err(format!(
                "listener owner changed during repair; PID {expected_pid} was not terminated"
            ));
        }

        let terminated = TerminateProcess(handle, R41_REPAIR_EXIT_CODE);
        let _ = CloseHandle(handle);
        terminated.map_err(|e| {
            format!("TerminateProcess({executable}, pid={expected_pid}) failed: {e}")
        })?;
    }

    // TerminateProcess is asynchronous for another process. Do not report repair
    // success until the configured listener has actually disappeared.
    for _ in 0..80 {
        match listener_owner(port)? {
            None => {
                return Ok(format!(
                    "released port {port} by terminating {executable} (PID {expected_pid})"
                ));
            }
            Some(owner) if owner.pid != expected_pid => {
                return Err(format!(
                    "port {port} was rebound by PID {} before repair verification completed",
                    owner.pid
                ));
            }
            Some(_) => std::thread::sleep(Duration::from_millis(50)),
        }
    }

    Err(format!(
        "process {executable} (PID {expected_pid}) was terminated but port {port} is still listening"
    ))
}

'''
    body = replace_once(body, anchor, helper + anchor, "explicit repair helper")

    # Add real Windows tests. One verifies the self-protection rule; the other
    # launches a dedicated Windows PowerShell child that owns an ephemeral port,
    # then exercises the same explicit repair primitive used by the UI.
    test_anchor = '''    #[test]\n    fn windows_port_guard_r40_classifies_foreign_and_stale_binders() {\n'''
    test_insert = r'''    #[test]
    fn windows_port_repair_r41_rejects_self_owner() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind self repair fixture");
        let port = listener.local_addr().expect("fixture addr").port();
        let error = terminate_live_foreign_listener_owner(port, std::process::id())
            .expect_err("explicit repair must never terminate this process");
        assert!(error.contains("current app PID"));
        drop(listener);
    }

    #[test]
    fn windows_port_repair_r41_terminates_explicit_foreign_owner() {
        use std::process::Command;

        // Reserve a currently-free port, release it, then immediately hand it to
        // a dedicated PowerShell child. The child is created solely by this test.
        let reservation = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("reserve test port");
        let port = reservation.local_addr().expect("reservation addr").port();
        drop(reservation);

        let script = format!(
            "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,{port}); try {{$l.Start(); Start-Sleep -Seconds 30}} finally {{$l.Stop()}}"
        );
        let mut child = Command::new("powershell.exe")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .spawn()
            .expect("spawn dedicated foreign listener fixture");
        let child_pid = child.id();

        let mut visible = false;
        for _ in 0..80 {
            if let Some(owner) = listener_owner(port).expect("query fixture owner") {
                if owner.pid == child_pid && owner.process_alive {
                    visible = true;
                    break;
                }
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        if !visible {
            let _ = child.kill();
            let _ = child.wait();
            panic!("dedicated PowerShell listener never became visible in TCP owner table");
        }

        let outcome = terminate_live_foreign_listener_owner(port, child_pid)
            .expect("explicit repair must terminate the dedicated foreign owner");
        assert!(outcome.contains("released port"));

        for _ in 0..40 {
            if listener_owner(port).expect("verify released listener").is_none() {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(listener_owner(port).expect("final owner query").is_none());
        let _ = child.wait();
    }

'''
    body = replace_once(body, test_anchor, test_insert + test_anchor, "r41 repair tests")
    OWNER.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Recovery endpoint: clicking the user-visible repair button is explicit consent
# to release a live foreign owner of the configured Transfer port. The recovery
# does NOT silently restart Transfer; after the port is verified free the user
# can press Start forwarding again, matching the requested interaction model.
# ---------------------------------------------------------------------------
body = CHAIN.read_text(encoding="utf-8")
if MARKER not in body:
    old = '''        "transfer_port_occupied_live" => {\n            actions.push(RecoveryAction::skipped(\n                "preserve_live_port_owner",\n                "配置端口由仍存活的其他进程占用；恢复器不会自动杀进程、改端口或用 SO_REUSEADDR 绕过所有权冲突",\n            ));\n        }\n'''
    new = '''        "transfer_port_occupied_live" => {\n            // CAS-R41-EXPLICIT-PORT-REPAIR: this branch runs only after the user\n            // explicitly clicks the recovery button. Re-resolve and revalidate the\n            // configured listener owner immediately before any termination.\n            #[cfg(target_os = "windows")]\n            {\n                let cfg = load_registry().unwrap_or_else(|_| json!({}));\n                let port = super::proxy::read_proxy_port(&cfg);\n                match crate::windows_tcp_owner::listener_owner(port) {\n                    Ok(Some(owner)) if owner.process_alive && owner.pid != std::process::id() => {\n                        let pid = owner.pid;\n                        let executable = owner\n                            .executable\n                            .clone()\n                            .unwrap_or_else(|| "<unresolved>".to_owned());\n                        match crate::windows_tcp_owner::terminate_live_foreign_listener_owner(port, pid) {\n                            Ok(detail) => actions.push(RecoveryAction::performed(\n                                "release_foreign_port_owner",\n                                format!(\n                                    "已释放 Transfer 端口 {port}：{executable} (PID {pid}) 已按用户显式修复请求结束。现在可重新点击‘启动转发’。{detail}"\n                                ),\n                            )),\n                            Err(error) => actions.push(RecoveryAction::failed(\n                                "release_foreign_port_owner",\n                                format!(\n                                    "未能安全释放 Transfer 端口 {port}；未改端口、未继续重试 bind：{}",\n                                    compact_error(&error)\n                                ),\n                            )),\n                        }\n                    }\n                    Ok(Some(owner)) if owner.process_alive => actions.push(RecoveryAction::failed(\n                        "refuse_self_port_owner_termination",\n                        format!(\n                            "端口 {port} 当前由本应用 PID {} 持有；为避免自杀式修复，未结束当前进程，请检查内部生命周期日志",\n                            owner.pid\n                        ),\n                    )),\n                    Ok(Some(owner)) => actions.push(RecoveryAction::skipped(\n                        "preserve_stale_listener_evidence",\n                        format!(\n                            "端口 {port} 的 binder PID {} 已不存在；不会拿死 PID 去结束可能已复用的新进程，已保留 stale-binder 证据",\n                            owner.pid\n                        ),\n                    )),\n                    Ok(None) => actions.push(RecoveryAction::performed(\n                        "port_already_free",\n                        format!("Transfer 端口 {port} 已经释放，现在可重新点击‘启动转发’"),\n                    )),\n                    Err(error) => actions.push(RecoveryAction::failed(\n                        "inspect_port_owner",\n                        format!("无法重新确认端口 {port} 的 owner：{}", compact_error(&error)),\n                    )),\n                }\n            }\n            #[cfg(not(target_os = "windows"))]\n            actions.push(RecoveryAction::skipped(\n                "explicit_port_repair_windows_only",\n                "显式端口 owner 修复目前仅在 Windows 上启用",\n            ));\n        }\n'''
    body = replace_once(body, old, new, "live-owner recovery branch")
    CHAIN.write_text(body, encoding="utf-8")


# Make the button wording match its actual behavior: this is now an explicit repair,
# not merely a passive diagnostic/recovery attempt.
for path, old_text, new_text in [
    (ZH, "'chainHealth.recover': '尝试恢复'", "'chainHealth.recover': '尝试修复'"),
    (EN, "'chainHealth.recover': 'Try recovery'", "'chainHealth.recover': 'Try repair'"),
]:
    text = path.read_text(encoding="utf-8")
    if new_text not in text:
        if old_text not in text:
            raise SystemExit(f"r41 explicit repair: i18n anchor missing in {path.name}")
        path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")


checks = {
    OWNER: [
        MARKER,
        "terminate_live_foreign_listener_owner",
        "PROCESS_TERMINATE",
        "TerminateProcess",
        "refusing to terminate current app PID",
        "listener owner changed during repair",
        "windows_port_repair_r41_rejects_self_owner",
        "windows_port_repair_r41_terminates_explicit_foreign_owner",
    ],
    CHAIN: [
        MARKER,
        "release_foreign_port_owner",
        "terminate_live_foreign_listener_owner",
        "现在可重新点击‘启动转发’",
        "preserve_stale_listener_evidence",
    ],
    ZH: ["'chainHealth.recover': '尝试修复'"],
    EN: ["'chainHealth.recover': 'Try repair'"],
}
for path, tokens in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"r41 explicit repair missing {token} in {path.relative_to(ROOT)}")

print("r41 explicit user-triggered live foreign port repair: applied")
