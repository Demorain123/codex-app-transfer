from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-R38-RECOVERY-PORT-CLASSIFICATION"

body = CHAIN.read_text(encoding="utf-8")
if MARKER not in body:
    # Transfer health: distinguish truly stopped from live foreign owner and dead/stale owner.
    old = '''    let transfer = if proxy_status.running {
        let port = proxy_status
            .addr
            .as_deref()
            .and_then(|value| value.rsplit(':').next())
            .unwrap_or("unknown");
        HealthLayer::new("ok", "transfer_listening", "Transfer 本地转发器正在监听")
            .fact(format!("listener={port}"))
            .fact(format!(
                "requests={} success={} failed={}",
                stats.total, stats.success, stats.failed
            ))
            .fact(format!(
                "active_provider={}",
                proxy_status.active_provider.as_deref().unwrap_or("none")
            ))
    } else {
        HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
            .fact(format!("requests={} failed={}", stats.total, stats.failed))
    };
'''
    new = '''    // CAS-R38-RECOVERY-PORT-CLASSIFICATION
    let configured_transfer_port = super::proxy::read_proxy_port(&cfg);
    let transfer = if proxy_status.running {
        let port = proxy_status
            .addr
            .as_deref()
            .and_then(|value| value.rsplit(':').next())
            .unwrap_or("unknown");
        HealthLayer::new("ok", "transfer_listening", "Transfer 本地转发器正在监听")
            .fact(format!("listener={port}"))
            .fact(format!(
                "requests={} success={} failed={}",
                stats.total, stats.success, stats.failed
            ))
            .fact(format!(
                "active_provider={}",
                proxy_status.active_provider.as_deref().unwrap_or("none")
            ))
    } else {
        #[cfg(target_os = "windows")]
        {
            match crate::windows_tcp_owner::listener_owner(configured_transfer_port) {
                Ok(Some(owner)) if owner.process_alive => HealthLayer::new(
                    "error",
                    "transfer_port_occupied_live",
                    "Transfer 未运行，但配置端口正被一个仍存活的进程监听",
                )
                .fact(format!("listener_port={configured_transfer_port}"))
                .fact(format!("owner_pid={} owner_alive=true", owner.pid))
                .fact(format!(
                    "owner_exe={}",
                    owner.executable.as_deref().unwrap_or("<unresolved>")
                )),
                Ok(Some(owner)) => HealthLayer::new(
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
                Ok(None) => HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
                    .fact(format!("listener_port={configured_transfer_port}"))
                    .fact(format!("requests={} failed={}", stats.total, stats.failed)),
                Err(error) => HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
                    .fact(format!("listener_port={configured_transfer_port}"))
                    .fact(format!("owner_probe_error={}", compact_error(&error)))
                    .fact(format!("requests={} failed={}", stats.total, stats.failed)),
            }
        }
        #[cfg(not(target_os = "windows"))]
        {
            HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
                .fact(format!("listener_port={configured_transfer_port}"))
                .fact(format!("requests={} failed={}", stats.total, stats.failed))
        }
    };
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: transfer layer anchor missing")
    body = body.replace(old, new, 1)

    old = '''fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
    if snapshot.transfer.code == "transfer_stopped" {
        return "transfer_stopped";
    }
'''
    new = '''fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
    if snapshot.transfer.code == "transfer_port_occupied_live" {
        return "transfer_port_occupied_live";
    }
    if snapshot.transfer.code == "transfer_port_stale_owner" {
        return "transfer_port_stale_owner";
    }
    if snapshot.transfer.code == "transfer_stopped" {
        return "transfer_stopped";
    }
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: recovery_classification anchor missing")
    body = body.replace(old, new, 1)

    old = '''    match classification.as_str() {
        "transfer_stopped" => {
            actions.push(recover_transfer(&state, &before, false).await);
        }
'''
    new = '''    match classification.as_str() {
        "transfer_port_occupied_live" => {
            actions.push(RecoveryAction::skipped(
                "preserve_live_port_owner",
                "18089/配置端口由仍存活的其他进程占用；恢复器不会自动杀进程、改端口或用 SO_REUSEADDR 绕过所有权冲突",
            ));
        }
        "transfer_port_stale_owner" => {
            actions.push(RecoveryAction::skipped(
                "preserve_stale_listener_evidence",
                "Windows 仍报告 owner PID 已死亡的监听端点；已保留现场，不重复 bind、不自动重启 Windows，详情中可查看 owner PID",
            ));
        }
        "transfer_stopped" => {
            actions.push(recover_transfer(&state, &before, false).await);
        }
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: match anchor missing")
    body = body.replace(old, new, 1)

    # r38 stop() is release-verified; use it rather than blind stop_silent + 150ms sleep.
    old = '''    if force_refresh && state.proxy_manager.status().running {
        state.proxy_manager.stop_silent();
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
'''
    new = '''    if force_refresh && state.proxy_manager.status().running {
        if let Err(error) = state.proxy_manager.stop() {
            return RecoveryAction::failed(
                "stop_transfer_verified",
                format!("Transfer stop 未通过端口释放验证，已中止后续 rebind: {}", compact_error(&error)),
            );
        }
    }
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: blind recovery stop anchor missing")
    body = body.replace(old, new, 1)

    # Recommendations make owner classification visible without forcing user into logs.
    old = '''    match transfer.code.as_str() {
        "transfer_stopped" => out.push("先启动 Transfer 转发器，再测试 Codex 新会话。".into()),
        _ => {}
    }
'''
    new = '''    match transfer.code.as_str() {
        "transfer_port_occupied_live" => out.push(
            "配置端口由仍存活进程占用：展开 Transfer 明细查看 owner PID/进程；不要自动杀进程或换端口掩盖根因。".into(),
        ),
        "transfer_port_stale_owner" => out.push(
            "Windows 报告死 PID 仍持有监听端点：保留现场并查看 listener owner 证据；恢复器不会连续重复 bind。".into(),
        ),
        "transfer_stopped" => out.push("先启动 Transfer 转发器，再测试 Codex 新会话。".into()),
        _ => {}
    }
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: recommendation anchor missing")
    body = body.replace(old, new, 1)
    CHAIN.write_text(body, encoding="utf-8")

# Frontend: local in-flight guard already exists; make progress explicit instead of leaving the label unchanged.
body = PAGE.read_text(encoding="utf-8")
if "chainHealth.recovering" not in body:
    old = '''            {{ t('chainHealth.recover') }}
'''
    new = '''            {{ chainRecovering ? t('chainHealth.recovering') : t('chainHealth.recover') }}
'''
    if old not in body:
        raise SystemExit("r38 recovery classification: recovery label anchor missing")
    body = body.replace(old, new, 1)
    PAGE.write_text(body, encoding="utf-8")

for path, key, value in (
    (ZH, '"chainHealth.recover": \'尝试恢复\',\n', '"chainHealth.recovering": \'恢复处理中…\',\n'),
    (EN, '"chainHealth.recover": \'Try recovery\',\n', '"chainHealth.recovering": \'Recovery in progress…\',\n'),
):
    text = path.read_text(encoding="utf-8")
    if "chainHealth.recovering" not in text:
        if key not in text:
            raise SystemExit(f"r38 recovery classification: i18n anchor missing in {path.name}")
        text = text.replace(key, key + "  " + value, 1)
        path.write_text(text, encoding="utf-8")

checks = {
    CHAIN: [
        MARKER,
        "transfer_port_occupied_live",
        "transfer_port_stale_owner",
        "preserve_stale_listener_evidence",
        "stop_transfer_verified",
    ],
    PAGE: ["chainHealth.recovering"],
    ZH: ["chainHealth.recovering"],
    EN: ["chainHealth.recovering"],
}
for path, tokens in checks.items():
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise SystemExit(f"r38 recovery classification missing {token} in {path.relative_to(ROOT)}")

print("r38 recovery port classification: applied")
