from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"
EXIT_GUARD = ROOT / "scripts/no_lagging_r32_mcp_exit_guard.ps1"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r43 {label}: expected exactly one anchor, found {count} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"r43 patched {label}: {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Health attribution: latest state per lineage, short shared-failure window,
# explicit model-switch/compact transition diagnosis, MCP evidence split.
# ---------------------------------------------------------------------------
replace_once(
    CHAIN,
    "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n//!",
    "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n//! CAS-R43-HEALTH-MCP-HARDENING\n//!",
    "chain-health marker",
)

replace_once(
    CHAIN,
    "const R37_EVIDENCE_WINDOW_SECS: u64 = 15 * 60;\nconst R37_LARGE_CONTEXT_BYTES: u64 = 8 * 1024 * 1024;",
    "const R37_EVIDENCE_WINDOW_SECS: u64 = 15 * 60;\nconst R37_LARGE_CONTEXT_BYTES: u64 = 8 * 1024 * 1024;\n"
    "const R43_SHARED_FAILURE_WINDOW_SECS: u64 = 2 * 60;\n"
    "const R43_COMPACTION_TRANSITION_WINDOW_SECS: u64 = 3 * 60;",
    "r43 windows",
)

# Pure predicates keep the lifecycle rules reviewable and unit-testable.
replace_once(
    CHAIN,
    "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\nfn recent_log_age_r37",
    "// CAS-R43-LIFECYCLE-PREDICATES\n"
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
    "r43 lifecycle predicates",
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

    // CAS-R43-LATEST-LINEAGE-WINS: historical failures must not keep the health card
    // red after the same provider/model/thread lineage has completed successfully.
    // Work newest-first and retain only the latest lifecycle record per lineage.
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
replace_once(CHAIN, old_failed, new_failed, "latest-lineage attribution")

replace_once(
    CHAIN,
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
    "compaction transition attribution",
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
new_peer = '''        // CAS-R43-SHARED-FAILURE-QUORUM: shared-upstream requires at least two
        // independent lineages whose *latest* state is still failed inside a short
        // window. A later 200 on a lineage immediately removes its stale failure vote.
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
replace_once(CHAIN, old_peer, new_peer, "shared-upstream quorum")

# MCP: keep the safety threshold based only on verified descendants of the active
# Codex root, but expose broken/external ancestry separately instead of conflating it.
replace_once(
    CHAIN,
    "        let mut names: HashMap<String, usize> = HashMap::new();\n        let mut helpers = 0usize;",
    "        let mut names: HashMap<String, usize> = HashMap::new();\n"
    "        let mut helpers = 0usize;\n"
    "        let mut orphan_candidates = 0usize;\n"
    "        let mut external_candidates = 0usize;",
    "mcp evidence counters",
)

replace_once(
    CHAIN,
    "            let mut owned = false;\n            let mut visited = HashSet::new();",
    "            let mut owned = false;\n"
    "            let mut ancestry_missing = false;\n"
    "            let mut visited = HashSet::new();",
    "mcp ancestry state",
)

replace_once(
    CHAIN,
    "                let Some(next) = by_id.get(&parent) else {\n                    break;\n                };",
    "                let Some(next) = by_id.get(&parent) else {\n"
    "                    ancestry_missing = true;\n"
    "                    break;\n"
    "                };",
    "mcp broken ancestry",
)

replace_once(
    CHAIN,
    "            if owned {\n                helpers += 1;\n                *names.entry(row.name.to_ascii_lowercase()).or_default() += 1;\n            }",
    "            if owned {\n"
    "                helpers += 1;\n"
    "                *names.entry(row.name.to_ascii_lowercase()).or_default() += 1;\n"
    "            } else if ancestry_missing {\n"
    "                orphan_candidates += 1;\n"
    "            } else {\n"
    "                external_candidates += 1;\n"
    "            }",
    "mcp ancestry classification",
)

replace_once(
    CHAIN,
    "            .fact(format!(\"owned_helpers={helpers}\"))\n            .fact(format!(\"max_duplicate={max_duplicate}\"))",
    "            .fact(format!(\"owned_helpers={helpers}\"))\n"
    "            .fact(format!(\"verified_generation_helpers={helpers}\"))\n"
    "            .fact(format!(\"orphan_candidates={orphan_candidates}\"))\n"
    "            .fact(format!(\"external_candidates={external_candidates}\"))\n"
    "            .fact(format!(\"max_duplicate={max_duplicate}\"))",
    "mcp evidence facts",
)

replace_once(
    CHAIN,
    "        \"fault_compaction_context\" => out.push(\n            \"大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。\".into(),\n        ),",
    "        \"fault_compaction_context\" => out.push(\n"
    "            \"大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。\".into(),\n"
    "        ),\n"
    "        \"fault_compaction_transition\" => out.push(\n"
    "            \"当前证据停在旧模型 compact/模型切换前阶段：先等待或切回旧模型恢复；不要把该 5xx 直接归因给尚未真正发出请求的新模型。\".into(),\n"
    "        ),",
    "compaction transition recommendation",
)

# Add deterministic regression tests to the existing test module.
replace_once(
    CHAIN,
    "    #[test]\n    fn severity_prefers_explicit_error() {\n        let ok = HealthLayer::new(\"ok\", \"ok\", \"ok\");",
    "    #[test]\n"
    "    fn r43_lifecycle_failure_predicate_clears_on_success() {\n"
    "        assert!(lifecycle_failed_r43(Some(503), Some(\"upstream_error\")));\n"
    "        assert!(lifecycle_failed_r43(None, Some(\"failed:transport\")));\n"
    "        assert!(!lifecycle_failed_r43(Some(200), Some(\"completed\")));\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn r43_compaction_transition_requires_fresh_5xx_and_signal() {\n"
    "        assert!(compaction_transition_failed_r43(Some(503), 10, Some(5)));\n"
    "        assert!(!compaction_transition_failed_r43(Some(400), 10, Some(5)));\n"
    "        assert!(!compaction_transition_failed_r43(Some(503), R43_COMPACTION_TRANSITION_WINDOW_SECS + 1, Some(5)));\n"
    "        assert!(!compaction_transition_failed_r43(Some(503), 10, None));\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn severity_prefers_explicit_error() {\n"
    "        let ok = HealthLayer::new(\"ok\", \"ok\", \"ok\");",
    "r43 unit tests",
)

# ---------------------------------------------------------------------------
# Runtime watcher: emit sanitized phase markers for model switch / compaction.
# ---------------------------------------------------------------------------
replace_once(
    RUNTIME,
    "//! CAS-RUNTIME-DIAG-R26\n//!",
    "//! CAS-RUNTIME-DIAG-R26\n//! CAS-R43-MODEL-SWITCH-COMPACTION-DIAG\n//!",
    "runtime marker",
)

replace_once(
    RUNTIME,
    "        (\"context automatically compacted\",\n            \"context_auto_compacted\",\n            \"INFO\",\n        ),",
    "        (\"context automatically compacting\", \"context_auto_compacting\", \"INFO\"),\n"
    "        (\"model changed from\", \"model_switch_selected\", \"INFO\"),\n"
    "        (\"compact v2 upstream\", \"compact_v2_upstream_failed\", \"WARN\"),\n"
    "        (\"context automatically compacted\",\n"
    "            \"context_auto_compacted\",\n"
    "            \"INFO\",\n"
    "        ),",
    "runtime transition classifiers",
)

# ---------------------------------------------------------------------------
# Exit Guard: exact PID + creation-time identity was already safe in r32. r43
# hardens the proof by re-checking the tracked identities after termination and
# logging *post-cleanup* survivors instead of the pre-cleanup target count.
# ---------------------------------------------------------------------------
replace_once(
    EXIT_GUARD,
    "# CAS-NO-LAGGING-R32-MCP-EXIT-GUARD\n",
    "# CAS-NO-LAGGING-R32-MCP-EXIT-GUARD\n# CAS-R43-POST-CLEANUP-VERIFICATION\n",
    "exit-guard marker",
)

old_cleanup = '''  $survivors = @($tracked.Values | Where-Object { Same-Identity $_ } | Sort-Object Depth -Descending)
  $stopped = 0
  foreach ($r in $survivors) {
    # Cheap race guard immediately before every exact-PID stop.
    if (@(Get-DesktopProcessesCheap).Count -gt 0) {
      Write-Event 'cleanup_cancelled_desktop_reappeared' @{ stopped=$stopped }
      return $false
    }
    if (-not (Same-Identity $r)) { continue }
    try {
      Stop-Process -Id $r.Pid -Force -ErrorAction Stop
      $stopped++
      Write-Event 'helper_stopped' @{ pid=$r.Pid; name=$r.Name }
    } catch {
      Write-Event 'helper_stop_failed' @{ pid=$r.Pid; name=$r.Name }
    }
  }
  Write-Event 'cleanup_complete' @{ tracked=$tracked.Count; survivors=$survivors.Count; stopped=$stopped }
  return $true
'''
new_cleanup = '''  $targets = @($tracked.Values | Where-Object { Same-Identity $_ } | Sort-Object Depth -Descending)
  $stopped = 0
  foreach ($r in $targets) {
    # Cheap race guard immediately before every exact-PID stop.
    if (@(Get-DesktopProcessesCheap).Count -gt 0) {
      Write-Event 'cleanup_cancelled_desktop_reappeared' @{ stopped=$stopped }
      return $false
    }
    if (-not (Same-Identity $r)) { continue }
    try {
      Stop-Process -Id $r.Pid -Force -ErrorAction Stop
      $stopped++
      Write-Event 'helper_stopped' @{ pid=$r.Pid; name=$r.Name }
    } catch {
      Write-Event 'helper_stop_failed' @{ pid=$r.Pid; name=$r.Name }
    }
  }

  # CAS-R43: Termination of another process is not a proof of disappearance.
  # Re-check the exact PID + creation-time/path identity; never fall back to
  # Stop-Process -Name / taskkill /IM or any broad runtime-name cleanup.
  Start-Sleep -Milliseconds 250
  $remaining = @($targets | Where-Object { Same-Identity $_ })
  Write-Event 'cleanup_verified' @{ attempted=$targets.Count; stopped=$stopped; remaining=$remaining.Count }
  Write-Event 'cleanup_complete' @{ tracked=$tracked.Count; attempted=$targets.Count; survivors=$remaining.Count; stopped=$stopped }
  return $true
'''
replace_once(EXIT_GUARD, old_cleanup, new_cleanup, "exit-guard post-cleanup verification")

print("r43 health/MCP hardening overlay: APPLIED")
