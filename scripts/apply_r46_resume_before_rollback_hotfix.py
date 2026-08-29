from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-RESUME-BEFORE-ROLLBACK-HOTFIX"

if MARKER in text:
    print("r46 resume-before-rollback hotfix already applied")
    raise SystemExit(0)

# A 500MB+ historical rollout can take longer than the original 12s maintenance-RPC
# budget to hydrate into a fresh shadow app-server. Keep this bounded, but large enough
# for the one explicit recovery action.
text = text.replace(
    "const RPC_TIMEOUT: Duration = Duration::from_secs(12);",
    "const RPC_TIMEOUT: Duration = Duration::from_secs(30);",
    1,
)

old = '''    let backup = backup_rollout(rollout, thread_id)?;
    let mut rpc = AppServerRpc::start(cli, codex_home)?;
    let before = latest_turn_window(&mut rpc, thread_id)?;
'''
new = '''    let backup = backup_rollout(rollout, thread_id)?;
    let mut rpc = AppServerRpc::start(cli, codex_home)?;

    // CAS-R46-RESUME-BEFORE-ROLLBACK-HOTFIX
    // `thread/turns/list` can read persisted history directly from the thread store,
    // while mutation methods such as the legacy `thread/rollback` operate on a thread
    // loaded into this app-server process' ThreadManager. A fresh shadow app-server has
    // no historical threads loaded yet, so hydrate the exact persisted thread first.
    let resume_result = match rpc.call(
        "thread/resume",
        json!({ "threadId": thread_id }),
    ) {
        Ok(value) => value,
        Err(error) => {
            return Err(format!(
                "目标历史 thread 可从持久化存储读取，但无法加载进恢复 app-server；未执行回退: {error}"
            ));
        }
    };
    let resumed_id = resume_result
        .get("thread")
        .and_then(|value| value.get("id"))
        .and_then(Value::as_str)
        .ok_or("thread/resume 成功响应缺少 result.thread.id；未执行回退")?;
    if resumed_id != thread_id {
        return Err(format!(
            "thread/resume 返回了不同的 thread id；为避免修改错误会话已中止。requested={} resumed={}",
            fingerprint8(thread_id),
            fingerprint8(resumed_id),
        ));
    }
    proxy_telemetry().logs.add(
        "INFO",
        format!(
            "[thread-recovery-r46] stage=thread_loaded method=thread/resume thread={} id_match=true",
            fingerprint8(thread_id),
        ),
    );

    let before = latest_turn_window(&mut rpc, thread_id)?;
'''
if old not in text:
    raise SystemExit("r46 resume-before-rollback hotfix: run_recovery_action anchor missing")
text = text.replace(old, new, 1)

for marker in (
    MARKER,
    '"thread/resume"',
    "stage=thread_loaded",
    "id_match=true",
    "Duration::from_secs(30)",
):
    if marker not in text:
        raise SystemExit(f"r46 resume-before-rollback hotfix invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R46 RESUME-BEFORE-ROLLBACK HOTFIX PASS")
