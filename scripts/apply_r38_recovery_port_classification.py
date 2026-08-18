from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-R38-RECOVERY-PORT-CLASSIFICATION"


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r38 recovery classification: {label} anchor count={count}, expected 1")
    return body.replace(old, new, 1)


body = CHAIN.read_text(encoding="utf-8")
if MARKER not in body:
    # The r37 chain-health composer may normalize whitespace around this section, so replace
    # the full transfer layer by semantic boundaries instead of a huge whitespace-sensitive literal.
    start_token = "    let proxy_status = state.proxy_manager.status();\n"
    end_token = "\n    let gateway = match provider.as_ref() {\n"
    start = body.find(start_token)
    if start < 0:
        raise SystemExit("r38 recovery classification: proxy_status boundary missing")
    end = body.find(end_token, start)
    if end < 0:
        raise SystemExit("r38 recovery classification: gateway boundary missing")
    old_segment = body[start:end]
    if "let transfer = if proxy_status.running" not in old_segment:
        raise SystemExit("r38 recovery classification: transfer layer semantic anchor missing")
    new_segment = '''    let proxy_status = state.proxy_manager.status();
    let stats = proxy_telemetry().stats.snapshot();
    // CAS-R38-RECOVERY-PORT-CLASSIFICATION
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
    body = body[:start] + new_segment + body[end:]

    body = replace_once(
        body,
        '''fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
    if snapshot.transfer.code == "transfer_stopped" {
        return "transfer_stopped";
    }
''',
        '''fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
    if snapshot.transfer.code == "transfer_port_occupied_live" {
        return "transfer_port_occupied_live";
    }
    if snapshot.transfer.code == "transfer_port_stale_owner" {
        return "transfer_port_stale_owner";
    }
    if snapshot.transfer.code == "transfer_stopped" {
        return "transfer_stopped";
    }
''',
        "recovery_classification",
    )

    body = replace_once(
        body,
        '''    match classification.as_str() {
        "transfer_stopped" => {
            actions.push(recover_transfer(&state, &before, false).await);
        }
''',
        '''    match classification.as_str() {
        "transfer_port_occupied_live" => {
            actions.push(RecoveryAction::skipped(
                "preserve_live_port_owner",
                "配置端口由仍存活的其他进程占用；恢复器不会自动杀进程、改端口或用 SO_REUSEADDR 绕过所有权冲突",
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
''',
        "recovery match",
    )

    body = replace_once(
        body,
        '''    if force_refresh && state.proxy_manager.status().running {
        state.proxy_manager.stop_silent();
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
''',
        '''    if force_refresh && state.proxy_manager.status().running {
        if let Err(error) = state.proxy_manager.stop() {
            return RecoveryAction::failed(
                "stop_transfer_verified",
                format!("Transfer stop 未通过端口释放验证，已中止后续 rebind: {}", compact_error(&error)),
            );
        }
    }
''',
        "verified recovery stop",
    )

    body = replace_once(
        body,
        '''    match transfer.code.as_str() {
        "transfer_stopped" => out.push("先启动 Transfer 转发器，再测试 Codex 新会话。".into()),
        _ => {}
    }
''',
        '''    match transfer.code.as_str() {
        "transfer_port_occupied_live" => out.push(
            "配置端口由仍存活进程占用：展开 Transfer 明细查看 owner PID/进程；不要自动杀进程或换端口掩盖根因。".into(),
        ),
        "transfer_port_stale_owner" => out.push(
            "Windows 报告死 PID 仍持有监听端点：保留现场并查看 listener owner 证据；恢复器不会连续重复 bind。".into(),
        ),
        "transfer_stopped" => out.push("先启动 Transfer 转发器，再测试 Codex 新会话。".into()),
        _ => {}
    }
''',
        "transfer recommendations",
    )
    CHAIN.write_text(body, encoding="utf-8")

# Frontend: the existing boolean is already a duplicate-click lock; make the stage visible.
body = PAGE.read_text(encoding="utf-8")
if "chainHealth.recovering" not in body:
    body = replace_once(
        body,
        "            {{ t('chainHealth.recover') }}\n",
        "            {{ chainRecovering ? t('chainHealth.recovering') : t('chainHealth.recover') }}\n",
        "recovery button label",
    )
    PAGE.write_text(body, encoding="utf-8")

for path, english in ((ZH, False), (EN, True)):
    text = path.read_text(encoding="utf-8")
    if "chainHealth.recovering" in text:
        continue
    old = '  "chainHealth.recover": \'Try recovery\',\n' if english else '  "chainHealth.recover": \'尝试恢复\',\n'
    new = old + (
        '  "chainHealth.recovering": \'Recovery in progress…\',\n'
        if english
        else '  "chainHealth.recovering": \'恢复处理中…\',\n'
    )
    if old not in text:
        raise SystemExit(f"r38 recovery classification: i18n anchor missing in {path.name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

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
