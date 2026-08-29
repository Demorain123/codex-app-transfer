from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
R43_MARKER = "CAS-R43-REWRITE-HEALTH-MCP"
PREP_MARKER = "CAS-R43-REPLAY-PREFLIGHT-LATEST-LINEAGE"
PEER_PREP_MARKER = "CAS-R43-REPLAY-PREFLIGHT-SHARED-QUORUM"

text = CHAIN.read_text(encoding="utf-8")
if R43_MARKER in text:
    print("r43 replay preflight: r43 health already materialized")
    raise SystemExit(0)

# apply_r43_rewrite_health.py intentionally replaces two r42 fault-attribution regions
# with latest-lineage-wins / short-window quorum semantics. Replaying old overlays from a
# newer checked-in tree can leave source-shape drift even though the behavior is still the
# r42 behavior. Canonicalize ONLY those two bounded r42 regions immediately before r43.
fn_start = text.find("fn fault_attribution_layer_r37(")
if fn_start < 0:
    raise SystemExit("r43 replay preflight: fault_attribution_layer_r37 missing")

changed = False

# 1) Failure-selection block consumed by r43 latest-lineage-wins replacement.
records_start = text.find(
    "    let records = proxy_telemetry().lifecycles.snapshot();",
    fn_start,
)
if records_start < 0:
    raise SystemExit("r43 replay preflight: lifecycle records anchor missing")
if_record = text.find("    if let Some(record) = failed {", records_start)
if if_record < 0:
    raise SystemExit("r43 replay preflight: failed-record boundary missing")

canonical_failed = '''    let records = proxy_telemetry().lifecycles.snapshot();
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

current_failed = text[records_start:if_record]
if current_failed != canonical_failed:
    for forbidden in (
        "CAS-R43-REWRITE-LATEST-LINEAGE-WINS",
        "latest_by_lineage",
        "lifecycle_failed_r43",
    ):
        if forbidden in current_failed:
            raise SystemExit(
                f"r43 replay preflight: refusing to overwrite newer lineage logic: {forbidden}"
            )
    text = text[:records_start] + canonical_failed + text[if_record:]
    changed = True

# 2) Peer-success / shared-failure block consumed by r43 short-window quorum replacement.
# Bound it by the first r42 `other_success` statement and the outer failed-record close,
# rather than relying on formatting inside the block.
fn_start = text.find("fn fault_attribution_layer_r37(")
peer_start = text.find(
    "        let other_success = records.iter().rev().any(|candidate| {",
    fn_start,
)
if peer_start < 0:
    raise SystemExit("r43 replay preflight: peer-success start missing")
peer_end = text.find(
    '    }\n\n    if session.code == "session_turn_stalled" {',
    peer_start,
)
if peer_end < 0:
    raise SystemExit("r43 replay preflight: peer/shared-failure boundary missing")

canonical_peer = '''        let other_success = records.iter().rev().any(|candidate| {
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

current_peer = text[peer_start:peer_end]
if current_peer != canonical_peer:
    for forbidden in (
        "CAS-R43-REWRITE-SHARED-FAILURE-QUORUM",
        "latest_peer_by_correlation",
        "active_failed",
    ):
        if forbidden in current_peer:
            raise SystemExit(
                f"r43 replay preflight: refusing to overwrite newer peer-quorum logic: {forbidden}"
            )
    text = text[:peer_start] + canonical_peer + text[peer_end:]
    changed = True

# Source comments outside the exact replacement regions make the preflight auditable
# without altering the anchors consumed by apply_r43_rewrite_health.py.
marker_anchor = "fn fault_attribution_layer_r37(\n"
markers = []
if PREP_MARKER not in text:
    markers.append(f"// {PREP_MARKER}\n")
if PEER_PREP_MARKER not in text:
    markers.append(f"// {PEER_PREP_MARKER}\n")
if markers:
    text = text.replace(marker_anchor, "".join(markers) + marker_anchor, 1)
    changed = True

if changed:
    CHAIN.write_text(text, encoding="utf-8")
    print("R43 REPLAY PREFLIGHT FAULT-ATTRIBUTION PASS")
else:
    print("r43 replay preflight: r42 fault-attribution anchors already canonical")
