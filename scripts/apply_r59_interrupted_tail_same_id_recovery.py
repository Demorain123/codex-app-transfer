from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/threadRecovery.ts"
FRONTEND_INDEX = ROOT / "frontend/dist/index.html"

MARKER = "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r59 interrupted-tail recovery: anchor missing: {label}")
    return text.replace(old, new, 1)


# Backend: this overlay is intentionally applied AFTER the full r58 materializer.
text = BACKEND.read_text(encoding="utf-8")
if MARKER not in text:
    old_validate = '''    if !matches!(body.action.as_str(), "rewindOne" | "forkPrevious") {
        return err(StatusCode::BAD_REQUEST, "action 必须为 rewindOne 或 forkPrevious")
            .into_response();
    }
'''
    new_validate = '''    if !matches!(
        body.action.as_str(),
        "rewindOne" | "forkPrevious" | "rewindInterruptedTail"
    ) {
        return err(
            StatusCode::BAD_REQUEST,
            "action 必须为 rewindOne、forkPrevious 或 rewindInterruptedTail",
        )
        .into_response();
    }
'''
    text = replace_once(text, old_validate, new_validate, "backend action allowlist")

    helper_anchor = "fn latest_turn_window(rpc: &mut AppServerRpc, thread_id: &str) -> Result<TurnWindow, String> {\n"
    helper = r'''// CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY
// Upstream Windows Codex Desktop can leave the newest persisted turn(s) in
// interrupted/failed after its embedded app-server exits with 0xC000013A.
// This helper reads only structural turn ids/statuses. It never reads message
// bodies or sends model inference requests.
fn latest_turn_states(
    rpc: &mut AppServerRpc,
    thread_id: &str,
) -> Result<Vec<(String, String)>, String> {
    match rpc.call(
        "thread/turns/list",
        json!({
            "threadId": thread_id,
            "limit": 100,
            "sortDirection": "desc",
            "itemsView": "summary"
        }),
    ) {
        Ok(result) => {
            let states = result
                .get("data")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| {
                            let id = item.get("id").and_then(Value::as_str)?;
                            let status = item.get("status").and_then(Value::as_str)?;
                            Some((id.to_owned(), status.to_owned()))
                        })
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            if states.is_empty() {
                return Err(
                    "thread/turns/list 未返回带 status 的 persisted turns；为避免误回退，r59 拒绝猜测"
                        .into(),
                );
            }
            return Ok(states);
        }
        Err(error) if error.method_not_found() => {}
        Err(error) => return Err(format!("thread/turns/list(status) 失败: {error}")),
    }

    // Older app-server fallback. thread/read returns turns oldest -> newest, so
    // reverse to keep the same newest-first contract as thread/turns/list.
    let result = rpc
        .call(
            "thread/read",
            json!({ "threadId": thread_id, "includeTurns": true }),
        )
        .map_err(|e| format!("thread/read(status) fallback 失败: {e}"))?;
    let mut states = result
        .get("thread")
        .and_then(|v| v.get("turns"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    let id = item.get("id").and_then(Value::as_str)?;
                    let status = item.get("status").and_then(Value::as_str)?;
                    Some((id.to_owned(), status.to_owned()))
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    states.reverse();
    if states.is_empty() {
        return Err(
            "thread/read fallback 未返回带 status 的 persisted turns；为避免误回退，r59 拒绝猜测"
                .into(),
        );
    }
    Ok(states)
}

fn r59_bad_tail_status(status: &str) -> bool {
    matches!(status, "interrupted" | "failed")
}

'''
    text = replace_once(text, helper_anchor, helper + helper_anchor, "backend structural status helper")

    rewind_anchor = '''        "rewindOne" => {
'''
    rewind_arm = r'''        "rewindInterruptedTail" => {
            const MAX_BAD_TAIL: usize = 8;
            let states = latest_turn_states(&mut rpc, thread_id)?;
            let newest_status = states
                .first()
                .map(|(_, status)| status.as_str())
                .ok_or("thread 没有 persisted turn status")?;

            if newest_status == "inProgress" {
                return Err(
                    "最新 turn 仍为 inProgress；r59 不会在活跃 turn 上执行历史回退。请等待其结束或先正常停止当前 turn"
                        .into(),
                );
            }
            if !r59_bad_tail_status(newest_status) {
                return Err(format!(
                    "最新 turn 状态为 {newest_status}，不是 interrupted/failed；没有需要 r59 清理的坏尾巴"
                ));
            }

            let bad_count = states
                .iter()
                .take_while(|(_, status)| r59_bad_tail_status(status))
                .count();
            if bad_count == 0 {
                return Err("未检测到 interrupted/failed 尾巴".into());
            }
            if bad_count > MAX_BAD_TAIL {
                return Err(format!(
                    "连续 interrupted/failed 尾巴有 {bad_count} 个，超过 r59 安全上限 {MAX_BAD_TAIL}；为避免大范围删除，拒绝自动处理"
                ));
            }
            if bad_count >= states.len() {
                return Err(
                    "最近 100 个可见 turns 全部属于 interrupted/failed，找不到更早安全边界；未执行回退"
                        .into(),
                );
            }

            let safe_boundary = states
                .get(bad_count)
                .cloned()
                .ok_or("找不到 interrupted/failed 尾巴之前的安全边界")?;
            if safe_boundary.1 != "completed" {
                return Err(format!(
                    "坏尾巴之前的第一个 persisted turn 状态为 {} 而不是 completed；为避免误删，未自动处理",
                    safe_boundary.1
                ));
            }
            let oldest_bad_turn = states
                .get(bad_count - 1)
                .map(|(id, _)| id.clone())
                .ok_or("找不到最早的坏尾巴 turn")?;
            let removed_ids = states
                .iter()
                .take(bad_count)
                .map(|(id, _)| id.clone())
                .collect::<Vec<_>>();

            proxy_telemetry().logs.add(
                "WARN",
                format!(
                    "[thread-recovery-r59] stage=bad_tail_detected thread={} bad_count={} newest_status={} oldest_bad={} safe_boundary={} safe_status=completed model_request=false",
                    fingerprint8(thread_id),
                    bad_count,
                    newest_status,
                    fingerprint8(&oldest_bad_turn),
                    fingerprint8(&safe_boundary.0),
                ),
            );

            let method = match rpc.call(
                "thread/revert",
                json!({
                    "threadId": thread_id,
                    "beforeTurnId": oldest_bad_turn
                }),
            ) {
                Ok(_) => "thread/revert(interrupted-tail)".to_owned(),
                Err(error) if error.method_not_found() => {
                    rpc.call(
                        "thread/rollback",
                        json!({
                            "threadId": thread_id,
                            "numTurns": bad_count
                        }),
                    )
                    .map_err(|e| {
                        format!(
                            "thread/revert 不受支持，thread/rollback({bad_count}) 也失败: {e}"
                        )
                    })?;
                    format!("thread/rollback({bad_count})")
                }
                Err(error) => {
                    return Err(format!(
                        "thread/revert 返回非 method-not-found 错误，为避免误删未自动 fallback: {error}"
                    ))
                }
            };

            let after_states = latest_turn_states(&mut rpc, thread_id)?;
            if removed_ids
                .iter()
                .any(|removed| after_states.iter().any(|(id, _)| id == removed))
            {
                return Err(
                    "app-server 接受了回退请求，但至少一个 interrupted/failed 尾巴 turn 仍可见；停止并保留备份供人工恢复"
                        .into(),
                );
            }
            let after_newest = after_states
                .first()
                .ok_or("回退后 thread 没有可见 persisted turn")?;
            if after_newest.0 != safe_boundary.0 || after_newest.1 != "completed" {
                return Err(format!(
                    "回退后边界验证失败：期望安全 completed turn={}，实际 newest={} status={}；未继续执行其它动作",
                    fingerprint8(&safe_boundary.0),
                    fingerprint8(&after_newest.0),
                    after_newest.1
                ));
            }

            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[thread-recovery-r59] stage=bad_tail_removed thread={} bad_count={} safe_boundary={} same_thread=true verified=true model_request=false",
                    fingerprint8(thread_id),
                    bad_count,
                    fingerprint8(&safe_boundary.0),
                ),
            );

            Ok(RecoveryActionResult {
                action: action.into(),
                source_thread_id: thread_id.into(),
                resulting_thread_id: thread_id.into(),
                method,
                boundary_turn_id: Some(oldest_bad_turn),
                visible_turns_before: before.visible_count,
                visible_turns_after: Some(after_states.len()),
                backup,
                codex_relaunched: false,
                workspace_files_changed: false,
                note: format!(
                    "已保持完全相同的 thread/session id，只移除最新连续 {bad_count} 个 interrupted/failed persisted turn，并验证最新边界恢复为 completed。该动作是对 Windows app-server 0xC000013A 后坏尾巴的恢复兜底，不代表修复 OpenAI 上游二进制本身。请回到原会话先发送一条很短的普通消息验证。"
                ),
            })
        }
'''
    text = replace_once(text, rewind_anchor, rewind_arm + rewind_anchor, "backend r59 recovery arm")

    for marker in (
        MARKER,
        '"rewindInterruptedTail"',
        "latest_turn_states",
        "r59_bad_tail_status",
        "MAX_BAD_TAIL",
        "thread/revert(interrupted-tail)",
        "stage=bad_tail_removed",
        "same_thread=true",
        "model_request=false",
    ):
        if marker not in text:
            raise SystemExit(f"r59 backend invariant missing: {marker}")
    BACKEND.write_text(text, encoding="utf-8")
    print("R59 INTERRUPTED-TAIL BACKEND PASS")
else:
    print("r59 interrupted-tail backend already applied")

# API type union.
api = API.read_text(encoding="utf-8")
if "'rewindInterruptedTail'" not in api:
    api = api.replace(
        "action: 'rewindOne' | 'forkPrevious'",
        "action: 'rewindOne' | 'forkPrevious' | 'rewindInterruptedTail'",
    )
    api = api.replace(
        "action: 'rewindOne' | 'forkPrevious',",
        "action: 'rewindOne' | 'forkPrevious' | 'rewindInterruptedTail',",
    )
    if api.count("'rewindInterruptedTail'") < 2:
        raise SystemExit("r59 API action union update incomplete")
    API.write_text(api, encoding="utf-8")
    print("R59 INTERRUPTED-TAIL API PASS")
else:
    print("r59 interrupted-tail API already applied")

# UI: patch the fully generated r46+r58 recovery panel.
page = PAGE.read_text(encoding="utf-8")
if MARKER not in page:
    old_sig = "async function runRecoveryAction(action: 'rewindOne' | 'forkPrevious') {"
    new_sig = "async function runRecoveryAction(action: 'rewindOne' | 'forkPrevious' | 'rewindInterruptedTail') {"
    page = replace_once(page, old_sig, new_sig, "frontend recovery action union")

    old_logic = r'''  const isRewind = action === 'rewindOne'
  const warning = isRewind
    ? `将先完整备份，然后让原会话 ${preview.threadFingerprint} 只回退最新 1 个 persisted turn。\n\n工作区文件不会回滚。每次点击最多只退 1 轮。是否继续？`
    : `将先完整备份，然后创建一个截止到前一 turn 边界的恢复副本。\n\n原会话不会被修改。是否继续？`
'''
    new_logic = r'''  // CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY
  const isRewind = action === 'rewindOne'
  const isInterruptedTail = action === 'rewindInterruptedTail'
  const warning = isInterruptedTail
    ? `将先完整备份，然后只读取 persisted turn 的 id/status，自动移除原会话 ${preview.threadFingerprint} 最新连续的 interrupted/failed 尾巴。\n\n必须找到更早的 completed 安全边界；最多 8 个；thread/session id 保持完全不变；工作区文件不会修改；不会发送模型请求。\n\n这是 0xC000013A 后的恢复兜底，不会修改 OpenAI Codex 二进制。是否继续？`
    : isRewind
      ? `将先完整备份，然后让原会话 ${preview.threadFingerprint} 只回退最新 1 个 persisted turn。\n\n工作区文件不会回滚。每次点击最多只退 1 轮。是否继续？`
      : `将先完整备份，然后创建一个截止到前一 turn 边界的恢复副本。\n\n原会话不会被修改。是否继续？`
'''
    page = replace_once(page, old_logic, new_logic, "frontend warning logic")

    old_toast = r'''    toast(
      isRewind
        ? '同 ID 单步恢复已执行，请先测试原会话的一条短消息'
        : `恢复副本已创建：${result.resultingThreadId}`,
      'info',
    )
'''
    new_toast = r'''    toast(
      isInterruptedTail
        ? '同 ID 中断尾巴已清理并验证，请回到完全相同的原会话先发送一条短消息'
        : isRewind
          ? '同 ID 单步恢复已执行，请先测试原会话的一条短消息'
          : `恢复副本已创建：${result.resultingThreadId}`,
      'info',
    )
'''
    page = replace_once(page, old_toast, new_toast, "frontend result toast")

    button_anchor = r'''            <button
              class="chain-health__button chain-health__button--repair"
              :disabled="threadRecoveryRunning || !threadRecoveryPreview.codexCliFound"
              @click="runRecoveryAction('rewindOne')"
            >
'''
    new_button = r'''            <button
              class="chain-health__button chain-health__button--repair"
              :disabled="threadRecoveryRunning || !threadRecoveryPreview.codexCliFound"
              @click="runRecoveryAction('rewindInterruptedTail')"
              title="只清理最新连续 interrupted/failed persisted turns；同一 session id；先备份；不发送模型请求"
            >
              <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
              同 ID 清理中断尾巴（0xC000013A）
            </button>
''' + button_anchor
    page = replace_once(page, button_anchor, new_button, "frontend r59 action button")

    old_intro = "先只读诊断；执行前自动备份。不会修改 workspace 文件，也不会自动连续回退多轮。"
    new_intro = "先只读诊断；执行前自动备份。r59 可在完全相同的 session id 上清理 Windows app-server 0xC000013A 后留下的连续 interrupted/failed 尾巴；不会修改 workspace 文件，也不会发送模型请求。"
    page = replace_once(page, old_intro, new_intro, "frontend recovery description")

    if MARKER not in page:
        raise SystemExit("r59 frontend marker missing after patch")
    PAGE.write_text(page, encoding="utf-8")
    if FRONTEND_INDEX.is_file():
        FRONTEND_INDEX.unlink()
        print("r59 interrupted-tail: invalidated stale frontend dist once")
    print("R59 INTERRUPTED-TAIL UI PASS")
else:
    print("r59 interrupted-tail UI already applied")

print("R59 INTERRUPTED-TAIL SAME-ID RECOVERY PASS")
