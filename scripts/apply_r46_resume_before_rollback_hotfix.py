from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-RESUME-BEFORE-ROLLBACK-HOTFIX"

if MARKER in text:
    print("r46 resume-before-rollback hotfix already applied")
    raise SystemExit(0)

# A 500MB+ historical rollout can take longer than the original maintenance-RPC
# budget to hydrate into a fresh shadow app-server. Keep this bounded, but large enough
# for the one explicit recovery action. Be tolerant if another hotfix already changed it.
text, timeout_replacements = re.subn(
    r"const RPC_TIMEOUT: Duration = Duration::from_secs\(\d+\);",
    "const RPC_TIMEOUT: Duration = Duration::from_secs(30);",
    text,
    count=1,
)
if timeout_replacements != 1 and "Duration::from_secs(30)" not in text:
    raise SystemExit("r46 resume-before-rollback hotfix: RPC_TIMEOUT anchor missing")

# Insert immediately before the first turn-window read. Earlier r46 backup/shadow/logging
# hotfixes are allowed to reshape everything before this semantic point, so do not depend
# on a large exact run_recovery_action block.
anchor_re = re.compile(
    r"(?m)^(?P<indent>[ \t]*)let before = latest_turn_window\(&mut rpc, thread_id\)\?;[ \t]*$"
)
match = anchor_re.search(text)
if not match:
    raise SystemExit("r46 resume-before-rollback hotfix: semantic latest_turn_window anchor missing")
indent = match.group("indent")
resume_block = f'''{indent}// CAS-R46-RESUME-BEFORE-ROLLBACK-HOTFIX
{indent}// `thread/turns/list` can read persisted history directly from the thread store,
{indent}// while mutation methods such as the legacy `thread/rollback` operate on a thread
{indent}// loaded into this app-server process' ThreadManager. A fresh shadow app-server has
{indent}// no historical threads loaded yet, so hydrate the exact persisted thread first.
{indent}let resume_result = match rpc.call(
{indent}    "thread/resume",
{indent}    json!({{ "threadId": thread_id }}),
{indent}) {{
{indent}    Ok(value) => value,
{indent}    Err(error) => {{
{indent}        return Err(format!(
{indent}            "目标历史 thread 可从持久化存储读取，但无法加载进恢复 app-server；未执行回退: {{error}}"
{indent}        ));
{indent}    }}
{indent}}};
{indent}let resumed_id = resume_result
{indent}    .get("thread")
{indent}    .and_then(|value| value.get("id"))
{indent}    .and_then(Value::as_str)
{indent}    .ok_or("thread/resume 成功响应缺少 result.thread.id；未执行回退")?;
{indent}if resumed_id != thread_id {{
{indent}    return Err(format!(
{indent}        "thread/resume 返回了不同的 thread id；为避免修改错误会话已中止。requested={{}} resumed={{}}",
{indent}        fingerprint8(thread_id),
{indent}        fingerprint8(resumed_id),
{indent}    ));
{indent}}}
{indent}proxy_telemetry().logs.add(
{indent}    "INFO",
{indent}    format!(
{indent}        "[thread-recovery-r46] stage=thread_loaded method=thread/resume thread={{}} id_match=true",
{indent}        fingerprint8(thread_id),
{indent}    ),
{indent});

'''
text = text[: match.start()] + resume_block + text[match.start() :]

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
