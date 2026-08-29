from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
FRONTEND_INDEX = ROOT / "frontend/dist/index.html"
MARKER = "CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX"

text = BACKEND.read_text(encoding="utf-8")

if MARKER not in text:
    old_window = '''struct TurnWindow {
    newest: Option<String>,
    previous: Option<String>,
    visible_count: usize,
}
'''
    new_window = '''struct TurnWindow {
    newest: Option<String>,
    previous: Option<String>,
    visible_count: usize,
    // CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX
    // Descending persisted turn ids from thread/turns/list. Keeping the bounded
    // window lets recovery target an exact failed compaction boundary instead of
    // guessing with a rollback count or blindly forking only one raw turn back.
    ids: Vec<String>,
}
'''
    if old_window not in text:
        raise SystemExit("r46 failure-boundary fork: TurnWindow anchor missing")
    text = text.replace(old_window, new_window, 1)

    # The app-server protocol caps thread/turns/list at 100. Use the full bounded
    # page so a handful of failed retries after the poisoned compaction do not hide
    # the exact failure boundary.
    turns_fn = text.find("fn latest_turn_window(")
    if turns_fn < 0:
        raise SystemExit("r46 failure-boundary fork: latest_turn_window missing")
    limit_pos = text.find('"limit": 64', turns_fn)
    if limit_pos < 0:
        raise SystemExit("r46 failure-boundary fork: turn list limit anchor missing")
    text = text[:limit_pos] + '"limit": 100' + text[limit_pos + len('"limit": 64'):]

    return_block = '''            return Ok(TurnWindow {
                newest: ids.first().cloned(),
                previous: ids.get(1).cloned(),
                visible_count: ids.len(),
            });
'''
    return_new = '''            return Ok(TurnWindow {
                newest: ids.first().cloned(),
                previous: ids.get(1).cloned(),
                visible_count: ids.len(),
                ids,
            });
'''
    if return_block not in text:
        raise SystemExit("r46 failure-boundary fork: v2 turn window return anchor missing")
    text = text.replace(return_block, return_new, 1)

    fallback_block = '''    Ok(TurnWindow {
        newest: ids.first().cloned(),
        previous: ids.get(1).cloned(),
        visible_count: ids.len(),
    })
'''
    fallback_new = '''    Ok(TurnWindow {
        newest: ids.first().cloned(),
        previous: ids.get(1).cloned(),
        visible_count: ids.len(),
        ids,
    })
'''
    if fallback_block not in text:
        raise SystemExit("r46 failure-boundary fork: legacy turn window return anchor missing")
    text = text.replace(fallback_block, fallback_new, 1)

    helper_anchor = "fn latest_turn_window(rpc: &mut AppServerRpc, thread_id: &str) -> Result<TurnWindow, String> {\n"
    if helper_anchor not in text:
        raise SystemExit("r46 failure-boundary fork: helper insertion anchor missing")
    helper = r'''// CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX
// Search only bounded/redacted proxy diagnostics and retain only structural metadata.
// This deliberately does not read or log request bodies, prompts, responses, tokens,
// credentials, tool arguments, or raw message content.
fn latest_failed_compaction_turn_id(thread_id: &str) -> Option<String> {
    const FAILURE_SCAN_BYTES: u64 = 64 * 1024 * 1024;
    let dir = proxy_log_dir()?;
    let mut files = fs::read_dir(dir)
        .ok()?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|v| v.to_str()) == Some("log"))
        .collect::<Vec<_>>();
    files.sort_by_key(|path| {
        fs::metadata(path)
            .and_then(|m| m.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH)
    });

    for path in files.into_iter().rev().take(4) {
        let Ok(tail) = read_tail(&path, FAILURE_SCAN_BYTES) else {
            continue;
        };
        let mut end = tail.len();
        for _ in 0..512 {
            let Some(pos) = tail[..end].rfind("upstream error diag ") else {
                break;
            };
            let after = &tail[pos..tail.len().min(pos + 48 * 1024)];
            let status = after
                .strip_prefix("upstream error diag ")
                .and_then(|rest| rest.split_whitespace().next())
                .and_then(|value| value.parse::<u16>().ok());
            let same_thread = extract_json_string(after, "thread_id")
                .as_deref()
                == Some(thread_id);
            let is_compaction = extract_json_string(after, "request_kind")
                .as_deref()
                == Some("compaction");
            if same_thread && is_compaction && status.is_some_and(|value| value >= 400) {
                if let Some(turn_id) = extract_json_string(after, "turn_id")
                    .filter(|value| safe_thread_id(value))
                {
                    return Some(turn_id);
                }
            }
            end = pos;
        }
    }
    None
}

'''
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    old_fork = '''        "forkPrevious" => {
            let boundary = before
                .previous
                .clone()
                .or_else(|| before.newest.clone())
                .ok_or("thread 没有可用于 fork 的 persisted turn")?;
'''
    new_fork = '''        "forkPrevious" => {
            // Do not guess with "previous" after the user has retried the broken
            // conversation multiple times. Locate the newest failed compaction for
            // this exact thread from structural diagnostics, then fork THROUGH the
            // immediately older persisted turn. This excludes the failed compaction
            // itself and every later failed retry while leaving the original untouched.
            let failure_turn = latest_failed_compaction_turn_id(thread_id).ok_or(
                "未在有界代理日志中找到该 thread 的失败 compaction turn；为避免截错会话，未创建恢复副本",
            )?;
            let failure_index = before
                .ids
                .iter()
                .position(|value| value == &failure_turn)
                .ok_or(
                    "已找到失败 compaction，但它不在最近 100 个 persisted turns 中；未自动猜测恢复边界",
                )?;
            let boundary = before
                .ids
                .get(failure_index + 1)
                .cloned()
                .ok_or("失败 compaction 已是最早可见 turn，没有更早安全边界可供 fork")?;
            proxy_telemetry().logs.add(
                "WARN",
                format!(
                    "[thread-recovery-r46] stage=fork_boundary thread={} failure_turn={} safe_last_turn={} exact_match=true original_untouched=true",
                    fingerprint8(thread_id),
                    fingerprint8(&failure_turn),
                    fingerprint8(&boundary),
                ),
            );
'''
    if old_fork not in text:
        raise SystemExit("r46 failure-boundary fork: forkPrevious anchor missing")
    text = text.replace(old_fork, new_fork, 1)

    old_note = 'note: "原 thread 未修改；已创建一个截止到前一安全边界的恢复副本。".into(),'
    new_note = 'note: "原 thread 未修改；已在最近一次失败 compaction 之前的精确 persisted-turn 边界创建恢复副本，并排除该失败 compaction 及其后的失败重试。请优先在新副本发送一条很短的普通消息验证。".into(),'
    if old_note not in text:
        raise SystemExit("r46 failure-boundary fork: fork result note anchor missing")
    text = text.replace(old_note, new_note, 1)

    old_rewind_note = 'note: "已保持同一个 thread id，仅回退最新 1 个 persisted turn；请先在原会话发送一条很短的普通消息验证，不要立刻再次切模型或 compact。".into(),'
    new_rewind_note = 'note: "同 ID 回退请求已被 app-server 接受，但旧版 thread/rollback 的计数语义不能证明失败 compaction 已被移除；如短消息仍发送巨型历史/继续 400，请改用‘故障前恢复副本’，不要连续盲点回退。".into(),'
    if old_rewind_note in text:
        text = text.replace(old_rewind_note, new_rewind_note, 1)

    for invariant in (
        MARKER,
        "latest_failed_compaction_turn_id",
        "stage=fork_boundary",
        "failure_turn=",
        "safe_last_turn=",
        '"limit": 100',
    ):
        if invariant not in text:
            raise SystemExit(f"r46 failure-boundary fork backend invariant missing: {invariant}")

    BACKEND.write_text(text, encoding="utf-8")
    print("R46 FAILURE-BOUNDARY FORK BACKEND PASS")
else:
    print("r46 failure-boundary fork backend already applied")

page = PAGE.read_text(encoding="utf-8")
old_label = "创建恢复副本（原会话不动）"
new_label = "创建故障前恢复副本（推荐）"
if old_label in page:
    page = page.replace(old_label, new_label, 1)
    PAGE.write_text(page, encoding="utf-8")
    # Invalidate only the generated frontend entry once. The FAST builder will rebuild
    # dist on this first UI change, then subsequent runs return to the warm SKIP path.
    if FRONTEND_INDEX.is_file():
        FRONTEND_INDEX.unlink()
        print("r46 failure-boundary fork: invalidated stale frontend dist once")
    print("R46 FAILURE-BOUNDARY FORK UI PASS")
elif new_label in page:
    print("r46 failure-boundary fork UI already applied")
else:
    raise SystemExit("r46 failure-boundary fork: recovery-copy UI label anchor missing")

print("R46 FAILURE-BOUNDARY FORK HOTFIX PASS")
