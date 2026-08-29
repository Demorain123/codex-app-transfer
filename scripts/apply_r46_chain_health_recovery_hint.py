from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
text = TARGET.read_text(encoding="utf-8")
MARKER = "CAS-R46-OLD-THREAD-RECOVERY-HINT"

if MARKER in text:
    print("r46 chain-health recovery hint already applied")
    raise SystemExit(0)

old = '''        "session_or_context_failure" => {
            actions.push(RecoveryAction::skipped(
                "no_infrastructure_restart",
                "同 provider 仍有成功会话或检测到大型上下文/compaction 证据；不重启健康网关，优先 fork/新建会话验证",
            ));
            actions.push(RecoveryAction::skipped(
                "preserve_thread_evidence",
                "保留旧会话现场，避免连续重试扩大上下文和上游消耗",
            ));
        }
'''
new = '''        "session_or_context_failure" => {
            // CAS-R46-OLD-THREAD-RECOVERY-HINT
            actions.push(RecoveryAction::skipped(
                "no_infrastructure_restart",
                "同 provider 仍有成功会话或检测到大型上下文/compaction 证据；不重启健康网关。请先打开“旧会话恢复”做只读预览",
            ));
            actions.push(RecoveryAction::skipped(
                "same_thread_recovery_available",
                "r46 可在自动备份 rollout + Codex state DB 后，同一个 thread id 每次只回退 1 个 persisted turn；若不希望改原会话，可创建恢复副本",
            ));
            actions.push(RecoveryAction::skipped(
                "preserve_thread_evidence",
                "不要在坏会话里反复发送或重复 compact；失败 compaction 可能继续保留同一巨型历史并重复触发上游 400",
            ));
        }
'''
if old not in text:
    raise SystemExit("r46 chain-health hint: session_or_context_failure anchor missing")
text = text.replace(old, new, 1)

old_rec = '"大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。"'
new_rec = '"大型旧会话的 context/compaction 路径异常：先用“旧会话恢复”只读预览；如需保留原 ID，一次只回退 1 轮并测试；不要连续发送或重复 compact。"'
if old_rec in text:
    text = text.replace(old_rec, new_rec, 1)

if MARKER not in text or "same_thread_recovery_available" not in text:
    raise SystemExit("r46 chain-health hint invariant missing")
TARGET.write_text(text, encoding="utf-8")
print("R46 CHAIN HEALTH RECOVERY HINT PASS")
