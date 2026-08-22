from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R43-REWRITE-HEALTH-MCP"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r43 rewrite {label}: expected one exact r42 anchor, found {count}")
    return text.replace(old, new, 1)


text = CHAIN.read_text(encoding="utf-8")
if MARKER in text:
    print("r43 rewrite health/MCP overlay: already applied")
    raise SystemExit(0)

text = replace_once(
    text,
    "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n//!",
    "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n//! CAS-R43-REWRITE-HEALTH-MCP\n//!",
    "file marker",
)

text = replace_once(
    text,
    "const R37_EVIDENCE_WINDOW_SECS: u64 = 15 * 60;\nconst R37_LARGE_CONTEXT_BYTES: u64 = 8 * 1024 * 1024;",
    "const R37_EVIDENCE_WINDOW_SECS: u64 = 15 * 60;\n"
    "const R37_LARGE_CONTEXT_BYTES: u64 = 8 * 1024 * 1024;\n"
    "const R43_SHARED_FAILURE_WINDOW_SECS: u64 = 2 * 60;\n"
    "const R43_COMPACTION_TRANSITION_WINDOW_SECS: u64 = 3 * 60;",
    "windows",
)

text = replace_once(
    text,
    "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\nfn recent_log_age_r37",
    "// CAS-R43-REWRITE-LIFECYCLE-PREDICATES\n"
    "fn lifecycle_failed_r43(raw_status: Option<u16>, terminal: Option<&str>) -> bool {\n"
    "    raw_status.is_some_and(|status| status >= 400)\n"
    "        || terminal.is_some_and(|value| value == \"upstream_error\" || value.starts_with(\"failed:\"))\n"
    "}\n\n"
    "fn compaction_transition_failed_r43(\n"
    "    raw_status: Option<u16>,\n"
    "    failure_age_s: u64,\n"
    "    compact_signal_age_s: Option<u64>,\n"
    ") -> bool {\n"
    "    failure_age_s <= R43_COMPACTION_TRANSITION_WINDOW_SECS\n"
    "        && compact_signal_age_s.is_some_and(|age| age <= R43_COMPACTION_TRANSITION_WINDOW_SECS)\n"
    "        && raw_status.is_some_and(|status| matches!(status, 500 | 502 | 503 | 504))\n"
    "}\n\n"
    "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\nfn recent_log_age_r37",
    "lifecycle predicates",
)

old_failed = '''    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let cutoff = now_ms.saturating_sub(30 * 60 * 1000);
    let failed = records.iter().rev().find(|record| {
        record.accepted_at_ms >= cutoff
            && (record
                .raw_upstream_status
                .is_some_and(|status| status >= 400)
                || record
                    .terminal
                    .as_deref()
                    .is_some_and(|value| value == "upstream_error" || value.starts_with("failed:")))
    });
'''
new_failed = '''    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let cutoff = now_ms.saturating_sub(30 * 60 * 1000);

    // CAS-R43-REWRITE-LATEST-LINEAGE-WINS: once the same provider/model/thread
    // lineage completes successfully, its older failure no longer votes red.
    let mut latest_by_lineage = HashMap::new();
    for candidate in records.iter().rev() {
        if candidate.accepted_at_ms < cutoff {
            continue;
        }
        latest_by_lineage
            .entry((
                candidate.provider.as_str(),
                candidate.model.as_str(),
                candidate.correlation.as_str(),
            ))
            .or_insert(candidate);
    }
    let failed = latest_by_lineage
        .values()
        .copied()
        .filter(|record| {
            lifecycle_failed_r43(record.raw_upstream_status, record.terminal.as_deref())
        })
        .max_by_key(|record| record.accepted_at_ms);
'''
text = replace_once(text, old_failed, new_failed, "latest-lineage attribution")

text = replace_once(
    text,
    "    if let Some(record) = failed {\n        let compact_signal =",
    "    if let Some(record) = failed {\n"
    "        let failure_age_s = now_ms.saturating_sub(record.accepted_at_ms).max(0) as u64 / 1000;\n"
    "        let transition_signal = recent_log_age_r37(\n"
    "            \"compact v2 upstream\",\n"
    "            R43_COMPACTION_TRANSITION_WINDOW_SECS,\n"
    "        )\n"
    "        .or_else(|| recent_log_age_r37(\"compact_v2_upstream_failed\", R43_COMPACTION_TRANSITION_WINDOW_SECS))\n"
    "        .or_else(|| recent_log_age_r37(\"remote_compaction_v2\", R43_COMPACTION_TRANSITION_WINDOW_SECS))\n"
    "        .or_else(|| recent_log_age_r37(\"context_auto_compacting\", R43_COMPACTION_TRANSITION_WINDOW_SECS));\n"
    "        if compaction_transition_failed_r43(\n"
    "            record.raw_upstream_status,\n"
    "            failure_age_s,\n"
    "            transition_signal,\n"
    "        ) {\n"
    "            return HealthLayer::new(\n"
    "                \"degraded\",\n"
    "                \"fault_compaction_transition\",\n"
    "                \"模型切换/旧会话 compact 阶段暂时不可用；尚未证明新模型请求已经发出\",\n"
    "            )\n"
    "            .fact(format!(\"model={} provider={}\", record.model, record.provider))\n"
    "            .fact(format!(\"request_bytes={}\", record.request_bytes))\n"
    "            .fact(format!(\"failure_age_s={failure_age_s}\"))\n"
    "            .fact(format!(\"compact_signal_age_s={}\", transition_signal.map(|v| v.to_string()).unwrap_or_else(|| \"-\".into())))\n"
    "            .fact(\"phase=pre_switch_compaction\")\n"
    "            .fact(\"new_model_request_seen=unproven\");\n"
    "        }\n\n"
    "        let compact_signal =",
    "model-switch compaction attribution",
)

old_peer = '''        let other_success = records.iter().rev().any(|candidate| {
            candidate.accepted_at_ms >= cutoff
                && candidate.provider == record.provider
                && candidate.model == record.model
                && candidate.correlation != record.correlation
                && candidate
                    .raw_upstream_status
                    .is_some_and(|status| status < 400)
                && candidate.terminal.as_deref() == Some("completed")
        });
        let start_failed = recent_log_age_r37("failed_to_start_turn", 5 * 60).is_some()
            || recent_log_age_r37("agent loop died unexpectedly", 5 * 60).is_some();
        if other_success {
            return HealthLayer::new(
                "error",
                "fault_session_scoped",
                "同模型、同 provider 的其他会话近期成功，故障更像当前 thread/session 局部状态",
            )
            .fact(format!(
                "model={} provider={}",
                record.model, record.provider
            ))
            .fact(format!("failed_correlation={}", record.correlation))
            .fact(format!("local_start_error={start_failed}"));
        }
        if start_failed {
            return HealthLayer::new(
                "error",
                "fault_session_state",
                "Codex 本地 Turn/agent loop 状态异常是当前最强证据",
            )
            .fact(format!("session_code={}", session.code));
        }

        let failed_correlations: HashSet<&str> = records
            .iter()
            .filter(|candidate| {
                candidate.accepted_at_ms >= cutoff
                    && candidate.provider == record.provider
                    && candidate.model == record.model
                    && candidate
                        .raw_upstream_status
                        .is_some_and(|status| status >= 400)
            })
            .map(|candidate| candidate.correlation.as_str())
            .collect();
        if failed_correlations.len() >= 2 {
            return HealthLayer::new(
                "error",
                "fault_shared_upstream",
                "同模型 / provider 的多个独立会话均失败，更像账号调度或共享上游故障",
            )
            .fact(format!("failed_threads={}", failed_correlations.len()))
            .fact(format!("upstream_code={}", upstream.code));
        }
'''
new_peer = '''        // CAS-R43-REWRITE-SHARED-FAILURE-QUORUM: only latest states in a
        // short provider/model window vote for a shared-upstream fault.
        let shared_cutoff = now_ms.saturating_sub(R43_SHARED_FAILURE_WINDOW_SECS as i64 * 1000);
        let mut latest_peer_by_correlation = HashMap::new();
        for candidate in records.iter().rev() {
            if candidate.accepted_at_ms < shared_cutoff
                || candidate.provider != record.provider
                || candidate.model != record.model
            {
                continue;
            }
            latest_peer_by_correlation
                .entry(candidate.correlation.as_str())
                .or_insert(candidate);
        }
        let active_failed = latest_peer_by_correlation
            .values()
            .filter(|candidate| {
                lifecycle_failed_r43(candidate.raw_upstream_status, candidate.terminal.as_deref())
            })
            .count();
        if active_failed >= 2 {
            return HealthLayer::new(
                "error",
                "fault_shared_upstream",
                "同模型/provider 的多个独立会话在同一短窗口内仍处于失败态，更像账号调度或共享上游故障",
            )
            .fact(format!("failed_threads={active_failed}"))
            .fact(format!("window_s={R43_SHARED_FAILURE_WINDOW_SECS}"))
            .fact(format!("upstream_code={}", upstream.code));
        }

        let other_success = latest_peer_by_correlation.values().any(|candidate| {
            candidate.correlation != record.correlation
                && candidate.raw_upstream_status.is_some_and(|status| status < 400)
                && candidate.terminal.as_deref() == Some("completed")
        });
        let start_failed = recent_log_age_r37("failed_to_start_turn", 5 * 60).is_some()
            || recent_log_age_r37("agent loop died unexpectedly", 5 * 60).is_some();
        if other_success {
            return HealthLayer::new(
                "error",
                "fault_session_scoped",
                "同模型、同 provider 的其他会话当前成功，故障更像当前 thread/session 局部状态",
            )
            .fact(format!(
                "model={} provider={}",
                record.model, record.provider
            ))
            .fact(format!("failed_correlation={}", record.correlation))
            .fact(format!("window_s={R43_SHARED_FAILURE_WINDOW_SECS}"))
            .fact(format!("local_start_error={start_failed}"));
        }
        if start_failed {
            return HealthLayer::new(
                "error",
                "fault_session_state",
                "Codex 本地 Turn/agent loop 状态异常是当前最强证据",
            )
            .fact(format!("session_code={}", session.code));
        }
'''
text = replace_once(text, old_peer, new_peer, "shared-upstream quorum")

text = replace_once(
    text,
    "        let mut names: HashMap<String, usize> = HashMap::new();\n        let mut helpers = 0usize;",
    "        let mut names: HashMap<String, usize> = HashMap::new();\n"
    "        let mut helpers = 0usize;\n"
    "        let mut orphan_candidates = 0usize;\n"
    "        let mut external_candidates = 0usize;",
    "MCP evidence counters",
)
text = replace_once(
    text,
    "            let mut owned = false;\n            let mut visited = HashSet::new();",
    "            let mut owned = false;\n"
    "            let mut ancestry_missing = false;\n"
    "            let mut visited = HashSet::new();",
    "MCP ancestry state",
)
text = replace_once(
    text,
    "                let Some(next) = by_id.get(&parent) else {\n                    break;\n                };",
    "                let Some(next) = by_id.get(&parent) else {\n"
    "                    ancestry_missing = true;\n"
    "                    break;\n"
    "                };",
    "MCP missing ancestry",
)
text = replace_once(
    text,
    "            if owned {\n                helpers += 1;\n                *names.entry(row.name.to_ascii_lowercase()).or_default() += 1;\n            }",
    "            if owned {\n"
    "                helpers += 1;\n"
    "                *names.entry(row.name.to_ascii_lowercase()).or_default() += 1;\n"
    "            } else if ancestry_missing {\n"
    "                orphan_candidates += 1;\n"
    "            } else {\n"
    "                external_candidates += 1;\n"
    "            }",
    "MCP ancestry classification",
)
text = replace_once(
    text,
    "            .fact(format!(\"owned_helpers={helpers}\"))\n            .fact(format!(\"max_duplicate={max_duplicate}\"))",
    "            .fact(format!(\"owned_helpers={helpers}\"))\n"
    "            .fact(format!(\"verified_generation_helpers={helpers}\"))\n"
    "            .fact(format!(\"orphan_candidates={orphan_candidates}\"))\n"
    "            .fact(format!(\"external_candidates={external_candidates}\"))\n"
    "            .fact(format!(\"max_duplicate={max_duplicate}\"))",
    "MCP facts",
)

text = replace_once(
    text,
    '        "fault_compaction_context" => out.push(\n            "大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。".into(),\n        ),',
    '        "fault_compaction_context" => out.push(\n'
    '            "大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。".into(),\n'
    '        ),\n'
    '        "fault_compaction_transition" => out.push(\n'
    '            "当前证据停在旧模型 compact/模型切换前阶段：先等待或切回旧模型恢复；不要把该 5xx 直接归因给尚未真正发出请求的新模型。".into(),\n'
    '        ),',
    "compaction recommendation",
)

text = replace_once(
    text,
    '        "fault_session_scoped" | "fault_session_state" | "fault_compaction_context"',
    '        "fault_session_scoped"\n            | "fault_session_state"\n            | "fault_compaction_context"\n            | "fault_compaction_transition"',
    "recovery classification",
)

text = replace_once(
    text,
    '    #[test]\n    fn severity_prefers_explicit_error() {\n        let ok = HealthLayer::new("ok", "ok", "ok");',
    '    #[test]\n'
    '    fn r43_rewrite_lifecycle_failure_predicate_clears_on_success() {\n'
    '        assert!(lifecycle_failed_r43(Some(503), Some("upstream_error")));\n'
    '        assert!(lifecycle_failed_r43(None, Some("failed:transport")));\n'
    '        assert!(!lifecycle_failed_r43(Some(200), Some("completed")));\n'
    '    }\n\n'
    '    #[test]\n'
    '    fn r43_rewrite_compaction_transition_requires_fresh_5xx_and_signal() {\n'
    '        assert!(compaction_transition_failed_r43(Some(503), 10, Some(5)));\n'
    '        assert!(!compaction_transition_failed_r43(Some(400), 10, Some(5)));\n'
    '        assert!(!compaction_transition_failed_r43(Some(503), R43_COMPACTION_TRANSITION_WINDOW_SECS + 1, Some(5)));\n'
    '        assert!(!compaction_transition_failed_r43(Some(503), 10, None));\n'
    '    }\n\n'
    '    #[test]\n'
    '    fn severity_prefers_explicit_error() {\n'
    '        let ok = HealthLayer::new("ok", "ok", "ok");',
    "unit tests",
)

CHAIN.write_text(text, encoding="utf-8")

final = CHAIN.read_text(encoding="utf-8")
for marker in (
    MARKER,
    "CAS-R43-REWRITE-LATEST-LINEAGE-WINS",
    "CAS-R43-REWRITE-SHARED-FAILURE-QUORUM",
    "fault_compaction_transition",
    "verified_generation_helpers",
    "orphan_candidates",
    "external_candidates",
    "r43_rewrite_lifecycle_failure_predicate_clears_on_success",
):
    if marker not in final:
        raise SystemExit(f"r43 rewrite postcondition missing: {marker}")

print("r43 rewrite health/MCP overlay: PASS")
