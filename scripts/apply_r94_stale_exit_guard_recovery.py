from __future__ import annotations

# CAS-R94-STALE-EXIT-GUARD-RECOVERY
#
# User-explicit "Try repair" support for one proven Windows failure mode:
# a dead Transfer binder PID still owns the TCP row because its directly spawned
# No-Lagging r32 mcp-exit-guard PowerShell inherited the listener handle.
#
# Safety contract:
# - fixed configured port is preserved (no port hopping)
# - Codex Desktop must be not running
# - Windows must report a listener whose original owner PID is dead
# - the same dead owner PID must be observed twice
# - exactly one *direct child* must still exist
# - child must be pwsh.exe/powershell.exe and its command line must contain the
#   exact Transfer-owned mcp-exit-guard-r32.ps1 path fragment
# - identity is re-checked immediately before Stop-Process
# - no name-wide kill, no taskkill /T, no SO_REUSEADDR, no Docker/account/session mutation
# - wait for the original fixed port to become genuinely free before starting Transfer

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R94-STALE-EXIT-GUARD-RECOVERY"

text = CHAIN.read_text(encoding="utf-8")
if MARKER in text:
    print("R94 STALE EXIT GUARD RECOVERY PASS (already applied)")
    raise SystemExit(0)

required = (
    "CAS-R38-RECOVERY-PORT-CLASSIFICATION",
    "transfer_port_stale_owner",
    "CAS-R46-GENERIC-REPAIR-SAME-FAULT-GUARD",
)
for token in required:
    if token not in text:
        raise SystemExit(f"r94 stale exit guard recovery prerequisite missing: {token}")

match_old = '''        "transfer_port_stale_owner" => {
            actions.push(RecoveryAction::skipped(
                "preserve_stale_listener_evidence",
                "Windows 仍报告 owner PID 已死亡的监听端点；已保留现场，不重复 bind、不自动重启 Windows，详情中可查看 owner PID",
            ));
        }
'''
match_new = '''        "transfer_port_stale_owner" => {
            // CAS-R94-STALE-EXIT-GUARD-RECOVERY
            actions.extend(recover_stale_exit_guard_listener_r94(&state, &before).await);
        }
'''
if text.count(match_old) != 1:
    raise SystemExit(
        f"r94 stale exit guard recovery: stale match anchor count={text.count(match_old)}, expected 1"
    )
text = text.replace(match_old, match_new, 1)

recommend_old = '''        "transfer_port_stale_owner" => out.push(
            "Windows 报告死 PID 仍持有监听端点：保留现场并查看 listener owner 证据；恢复器不会连续重复 bind。".into(),
        ),
'''
recommend_new = '''        "transfer_port_stale_owner" => out.push(
            "Windows 报告死 PID 仍持有监听端点：可使用“尝试修复”。恢复器只会在 Codex 已退出、连续确认同一 dead binder、且唯一直接子进程精确匹配 Transfer 的 mcp-exit-guard-r32.ps1 时停止该 PID；随后等待同一个固定端口释放并重新启动 Transfer。".into(),
        ),
'''
if text.count(recommend_old) != 1:
    raise SystemExit(
        f"r94 stale exit guard recovery: recommendation anchor count={text.count(recommend_old)}, expected 1"
    )
text = text.replace(recommend_old, recommend_new, 1)

helper_anchor = '''async fn recover_transfer(
    state: &AdminState,
    snapshot: &ChainHealthSnapshot,
    force_refresh: bool,
) -> RecoveryAction {
'''
if helper_anchor not in text:
    raise SystemExit("r94 stale exit guard recovery: recover_transfer anchor missing")

helper = r'''#[cfg(target_os = "windows")]
async fn r94_find_stale_exit_guard_child(dead_binder_pid: u32) -> Result<Vec<u32>, String> {
    // Keep command-line inspection inside PowerShell and return PID(s) only.
    // This avoids ingesting unrelated process command lines into Transfer logs/state.
    let script = format!(
        concat!(
            "$ErrorActionPreference='Stop';",
            "$parent={dead_binder_pid};",
            "$marker='\\.codex-app-transfer\\codex-no-micro\\mcp-exit-guard-r32.ps1';",
            "$rows=@(Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $parent) | ",
            "Where-Object {{ ",
            "($_.Name -ieq 'pwsh.exe' -or $_.Name -ieq 'powershell.exe') -and ",
            "$_.CommandLine -and $_.CommandLine.IndexOf($marker,[StringComparison]::OrdinalIgnoreCase) -ge 0 ",
            "}});",
            "$rows | ForEach-Object {{ [string]$_.ProcessId }}"
        )
    );
    let result = run_command(
        "powershell.exe",
        &[
            "-NoLogo".into(),
            "-NoProfile".into(),
            "-NonInteractive".into(),
            "-ExecutionPolicy".into(),
            "Bypass".into(),
            "-Command".into(),
            script,
        ],
        Duration::from_secs(4),
    )
    .await;
    if !matches!(result.kind, CommandKind::Ok) {
        return Err(format!(
            "Exit Guard identity inventory failed: exit={:?} error={}",
            result.exit_code,
            result.stderr
        ));
    }
    let mut pids = Vec::new();
    for line in result.stdout.lines().map(str::trim).filter(|v| !v.is_empty()) {
        let pid = line
            .parse::<u32>()
            .map_err(|_| "Exit Guard identity inventory returned a non-PID value".to_owned())?;
        if !pids.contains(&pid) {
            pids.push(pid);
        }
    }
    Ok(pids)
}

#[cfg(target_os = "windows")]
async fn r94_stop_exact_stale_exit_guard(dead_binder_pid: u32, guard_pid: u32) -> Result<(), String> {
    // Re-check all identity fields in the same PowerShell invocation that performs
    // Stop-Process. PID reuse or parent/command drift therefore fails closed.
    let script = format!(
        concat!(
            "$ErrorActionPreference='Stop';",
            "$parent={dead_binder_pid};$pid={guard_pid};",
            "$marker='\\.codex-app-transfer\\codex-no-micro\\mcp-exit-guard-r32.ps1';",
            "$p=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $pid);",
            "if(-not $p){{exit 41}};",
            "if([uint32]$p.ParentProcessId -ne [uint32]$parent){{exit 42}};",
            "if(-not ($p.Name -ieq 'pwsh.exe' -or $p.Name -ieq 'powershell.exe')){{exit 43}};",
            "if(-not $p.CommandLine -or $p.CommandLine.IndexOf($marker,[StringComparison]::OrdinalIgnoreCase) -lt 0){{exit 44}};",
            "Stop-Process -Id $pid -Force -ErrorAction Stop;",
            "Write-Output ('stopped=' + $pid)"
        )
    );
    let result = run_command(
        "powershell.exe",
        &[
            "-NoLogo".into(),
            "-NoProfile".into(),
            "-NonInteractive".into(),
            "-ExecutionPolicy".into(),
            "Bypass".into(),
            "-Command".into(),
            script,
        ],
        Duration::from_secs(5),
    )
    .await;
    if matches!(result.kind, CommandKind::Ok)
        && result.stdout.trim() == format!("stopped={guard_pid}")
    {
        Ok(())
    } else {
        Err(format!(
            "Exit Guard identity re-check/stop failed: exit={:?} error={}",
            result.exit_code,
            result.stderr
        ))
    }
}

#[cfg(target_os = "windows")]
async fn r94_wait_fixed_port_free(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match crate::windows_tcp_owner::listener_owner(port) {
            Ok(None) => return true,
            Ok(Some(_)) | Err(_) if Instant::now() < deadline => {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Ok(Some(_)) | Err(_) => return false,
        }
    }
}

#[cfg(target_os = "windows")]
async fn recover_stale_exit_guard_listener_r94(
    state: &AdminState,
    snapshot: &ChainHealthSnapshot,
) -> Vec<RecoveryAction> {
    let mut actions = Vec::new();

    // The r32 Exit Guard is intentionally useful while Codex is alive. Never
    // terminate it from generic recovery until Desktop/app-server is confirmed gone.
    if snapshot.codex.code != "codex_not_running" {
        actions.push(RecoveryAction::skipped(
            "preserve_running_codex_exit_guard",
            "检测到 Codex 仍在运行；不会停止 MCP Exit Guard。请先正常退出 Codex，再重新“立即检查”。",
        ));
        return actions;
    }

    let cfg = load_registry().unwrap_or_else(|_| json!({}));
    let port = super::proxy::read_proxy_port(&cfg);

    let first = match crate::windows_tcp_owner::listener_owner(port) {
        Ok(Some(owner)) if !owner.process_alive => owner,
        Ok(Some(owner)) => {
            actions.push(RecoveryAction::skipped(
                "preserve_live_port_owner",
                format!(
                    "端口 {port} 当前 owner PID {} 仍存活；不会自动杀进程、换端口或抢占监听。",
                    owner.pid
                ),
            ));
            return actions;
        }
        Ok(None) => {
            actions.push(RecoveryAction::performed(
                "stale_listener_already_released",
                format!("端口 {port} 已释放，无需清理旧 Exit Guard"),
            ));
            actions.push(recover_transfer(state, snapshot, false).await);
            return actions;
        }
        Err(error) => {
            actions.push(RecoveryAction::failed(
                "verify_stale_listener",
                format!("无法读取端口 {port} owner 证据: {}", compact_error(&error)),
            ));
            return actions;
        }
    };

    tokio::time::sleep(Duration::from_millis(180)).await;
    let second = match crate::windows_tcp_owner::listener_owner(port) {
        Ok(Some(owner)) => owner,
        Ok(None) => {
            actions.push(RecoveryAction::performed(
                "stale_listener_released_during_verification",
                format!("端口 {port} 在二次确认期间自行释放"),
            ));
            actions.push(recover_transfer(state, snapshot, false).await);
            return actions;
        }
        Err(error) => {
            actions.push(RecoveryAction::failed(
                "verify_stale_listener",
                format!("二次 owner 证据读取失败: {}", compact_error(&error)),
            ));
            return actions;
        }
    };

    if second.process_alive || second.pid != first.pid {
        actions.push(RecoveryAction::skipped(
            "stale_listener_identity_changed",
            format!(
                "端口 {port} owner 在二次确认期间发生变化（{} -> {}，alive={}）；为避免误杀已中止自动清理。",
                first.pid, second.pid, second.process_alive
            ),
        ));
        return actions;
    }

    let dead_binder_pid = first.pid;
    actions.push(RecoveryAction::performed(
        "verify_stale_listener",
        format!(
            "已连续确认端口 {port} 的原 binder PID {dead_binder_pid} 不存在；开始查找其唯一、精确匹配的 Transfer r32 Exit Guard 直接子进程"
        ),
    ));

    let candidates = match r94_find_stale_exit_guard_child(dead_binder_pid).await {
        Ok(pids) => pids,
        Err(error) => {
            actions.push(RecoveryAction::failed(
                "find_stale_exit_guard",
                compact_error(&error),
            ));
            return actions;
        }
    };

    if candidates.is_empty() {
        actions.push(RecoveryAction::skipped(
            "no_exact_stale_exit_guard",
            format!(
                "未找到 parent PID={dead_binder_pid} 且命令行精确匹配 Transfer mcp-exit-guard-r32.ps1 的 pwsh/powershell；保留现场，不进行模糊进程清理"
            ),
        ));
        return actions;
    }
    if candidates.len() != 1 {
        actions.push(RecoveryAction::skipped(
            "ambiguous_stale_exit_guard",
            format!(
                "找到 {} 个精确 Exit Guard 候选，身份不唯一；已中止自动清理，不会批量杀进程",
                candidates.len()
            ),
        ));
        return actions;
    }

    let guard_pid = candidates[0];
    if let Err(error) = r94_stop_exact_stale_exit_guard(dead_binder_pid, guard_pid).await {
        actions.push(RecoveryAction::failed(
            "stop_stale_exit_guard",
            compact_error(&error),
        ));
        return actions;
    }
    actions.push(RecoveryAction::performed(
        "stop_stale_exit_guard",
        format!(
            "已停止旧 Transfer binder PID {dead_binder_pid} 的唯一直接子进程 Exit Guard PID {guard_pid}；未触碰其他 PowerShell/MCP/helper"
        ),
    ));

    if !r94_wait_fixed_port_free(port, Duration::from_secs(3)).await {
        let evidence = crate::windows_tcp_owner::listener_owner_evidence(port);
        actions.push(RecoveryAction::failed(
            "wait_fixed_port_release",
            format!(
                "Exit Guard 已停止，但固定端口 {port} 在 3 秒内仍未释放；保留现场，不换端口、不继续 bind。{evidence}"
            ),
        ));
        return actions;
    }

    actions.push(RecoveryAction::performed(
        "fixed_port_released",
        format!("固定端口 {port} 已确认释放；保持原端口不变"),
    ));
    actions.push(recover_transfer(state, snapshot, false).await);
    actions
}

#[cfg(not(target_os = "windows"))]
async fn recover_stale_exit_guard_listener_r94(
    _state: &AdminState,
    _snapshot: &ChainHealthSnapshot,
) -> Vec<RecoveryAction> {
    vec![RecoveryAction::skipped(
        "windows_stale_listener_recovery_unavailable",
        "该定向修复仅适用于 Windows dead-binder + r32 Exit Guard 证据链",
    )]
}

'''
text = text.replace(helper_anchor, helper + helper_anchor, 1)

for invariant in (
    MARKER,
    "recover_stale_exit_guard_listener_r94",
    "preserve_running_codex_exit_guard",
    "r94_find_stale_exit_guard_child",
    "r94_stop_exact_stale_exit_guard",
    "ParentProcessId = ",
    "mcp-exit-guard-r32.ps1",
    "stale_listener_identity_changed",
    "no_exact_stale_exit_guard",
    "ambiguous_stale_exit_guard",
    "fixed_port_released",
    "保持原端口不变",
):
    if invariant not in text:
        raise SystemExit(f"r94 stale exit guard recovery invariant missing: {invariant}")

# Explicit negative guards: this leaf must not introduce broad/destructive cleanup.
for forbidden in (
    "taskkill /T",
    "taskkill /IM",
    "SO_REUSEADDR",
    "Stop-Process -Name",
    "Get-Process | Stop-Process",
):
    if forbidden in text:
        raise SystemExit(f"r94 stale exit guard recovery forbidden broad action: {forbidden}")

CHAIN.write_text(text, encoding="utf-8")
print("R94_STALE_EXIT_GUARD_RECOVERY_PASS")
print("- Try repair now supports the proven dead-binder -> exact r32 Exit Guard leak")
print("- requires Codex stopped + stable dead owner PID + exactly one direct exact-script child")
print("- re-checks identity immediately before stopping that one PID")
print("- waits for the same configured port to become free, then starts Transfer on that same port")
print("- no port hopping, no process-name-wide kill, no Docker/account/session mutation")
