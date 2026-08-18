from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROXY_HANDLER = ROOT / "src-tauri/src/admin/handlers/proxy.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R39-BIND-BUSY-NONRETRYABLE"

body = PROXY_HANDLER.read_text(encoding="utf-8")
if MARKER not in body:
    old_stop = '''        manager.stop_silent();
    }

    const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];
    for attempt in 0..=RETRY_MS.len() {
        match manager.start(port).await {
            Ok(_) => return Ok(true),
            Err(message) if proxy_bind_address_in_use(&message) && attempt < RETRY_MS.len() => {
                let delay = RETRY_MS[attempt];
                proxy_telemetry().logs.add(
                    "WARN",
                    format!(
                        "[proxy-lifecycle-r28] bind busy requested_port={port} retry={} delay_ms={delay}",
                        attempt + 1
                    ),
                );
                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
            }
            Err(message) => {
                return Err(if proxy_bind_address_in_use(&message) {
                    format!(
                        "{message}; r28 已避免同端口自重启并按 provider 刷新 resolver，若端口 {port} 仍失败说明此刻确有 listener/Windows socket 占用"
                    )
                } else {
                    message
                });
            }
        }
    }
    unreachable!("bounded proxy start retry loop always returns")
'''
    new_stop = '''        // CAS-R39-BIND-BUSY-NONRETRYABLE
        // Provider refresh is a verified lifecycle transition now. A failed stop must
        // abort before any same-port rebind; do not silently continue after teardown.
        manager.stop().map_err(|error| {
            format!(
                "proxy provider refresh stopped before rebind because teardown verification failed: {error}"
            )
        })?;
    }

    // Address-in-use is ownership evidence, not a transient retry signal. Repeating
    // bind five times only floods the UI and can hide a lifecycle defect. r39 performs
    // exactly one bind attempt. Recovery/health owns the explanation; it never kills
    // an owner, changes ports, or enables SO_REUSEADDR automatically.
    match manager.start(port).await {
        Ok(_) => Ok(true),
        Err(message) if proxy_bind_address_in_use(&message) => {
            proxy_telemetry().logs.add(
                "ERROR",
                format!(
                    "[proxy-lifecycle-r39] bind_busy_nonretryable requested_port={port} message={message}"
                ),
            );
            Err(format!(
                "{message}; r39 将地址占用视为不可盲重试故障：不会自动换端口、不会杀进程、不会用 SO_REUSEADDR；请查看全链路健康中的 binder/listener 证据"
            ))
        }
        Err(message) => Err(message),
    }
'''
    if old_stop not in body:
        raise SystemExit("r39 bind policy: r28 retry block anchor missing")
    body = body.replace(old_stop, new_stop, 1)
    PROXY_HANDLER.write_text(body, encoding="utf-8")

# Correct r38 health wording: IP Helper's PID is binder/context attribution, not proof
# that a dead process is still the sole live handle owner.
body = CHAIN.read_text(encoding="utf-8")
if "CAS-R39-BINDER-TERMINOLOGY" not in body:
    body = body.replace(
        '''                Ok(Some(owner)) => HealthLayer::new(
                    "error",
                    "transfer_port_stale_owner",
                    "Transfer 未运行，但 Windows 仍报告一个 owner PID 已死亡的监听端点",
                )
                .fact(format!("listener_port={configured_transfer_port}"))
                .fact(format!("owner_pid={} owner_alive=false", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<dead-or-unresolved>")
                )),
''',
        '''                // CAS-R39-BINDER-TERMINOLOGY: GetExtendedTcpTable identifies the
                // context-bind PID. If that PID is gone while the listener remains, call it
                // unresolved listener residue rather than claiming the dead PID still owns
                // the only socket handle.
                Ok(Some(owner)) => HealthLayer::new(
                    "error",
                    "transfer_port_stale_owner",
                    "Transfer 未运行；Windows 仍报告监听端点，但最初 binder PID 已不存在",
                )
                .fact(format!("listener_port={configured_transfer_port}"))
                .fact(format!("binder_pid={} binder_alive=false", owner.pid))
                .fact(format!(
                    "binder_exe={}",
                    owner.executable.as_deref().unwrap_or("<dead-or-unresolved>")
                ))
                .fact("classification=unresolved_listener_residue"),
''',
        1,
    )
    body = body.replace(
        "Windows 仍报告 owner PID 已死亡的监听端点；已保留现场，不重复 bind、不自动重启 Windows，详情中可查看 owner PID",
        "Windows 仍报告监听端点，但最初 binder PID 已不存在；已保留现场，不重复 bind、不自动重启 Windows，详情中可查看 binder 证据",
    )
    body = body.replace(
        "Windows 报告死 PID 仍持有监听端点：保留现场并查看 listener owner 证据；恢复器不会连续重复 bind。",
        "Windows 报告监听端点仍在，而最初 binder PID 已不存在：保留现场并查看 binder/listener 证据；恢复器不会连续重复 bind。",
    )
    CHAIN.write_text(body, encoding="utf-8")

checks = {
    PROXY_HANDLER: [
        MARKER,
        "bind_busy_nonretryable",
        "manager.stop().map_err",
        "exactly one bind attempt",
    ],
    CHAIN: [
        "CAS-R39-BINDER-TERMINOLOGY",
        "binder_pid=",
        "classification=unresolved_listener_residue",
    ],
}
for path, tokens in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"r39 bind policy missing {token} in {path.relative_to(ROOT)}")

handler = PROXY_HANDLER.read_text(encoding="utf-8")
if '[proxy-lifecycle-r28] bind busy requested_port=' in handler:
    raise SystemExit("r39 bind policy: r28 blind bind retry survived")
if "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];" in handler:
    raise SystemExit("r39 bind policy: address-in-use retry schedule survived")

print("r39 bind-busy policy: non-retryable + binder terminology applied")
