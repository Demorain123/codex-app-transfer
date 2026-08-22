from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"


def fail(label: str, detail: str) -> None:
    raise SystemExit(f"r43 semantic anchor prep: {label}: {detail}")


def require_once(text: str, token: str, label: str) -> int:
    count = text.count(token)
    if count != 1:
        fail(label, f"expected exactly one token, found {count}: {token!r}")
    return text.find(token)


# ---------------------------------------------------------------------------
# chain_health.rs
#
# r38-r42 preserve the r37 fault-attribution semantics, but generated/formatting
# passes are allowed to reshape whitespace.  The r43 overlay intentionally uses
# strict replace_once() guards, so normalize only the two known r37 semantic
# regions to their canonical r43 input form.  Boundary + semantic-marker checks
# keep this from silently overwriting a future logic change.
# ---------------------------------------------------------------------------
chain = CHAIN.read_text(encoding="utf-8")
function_token = "fn fault_attribution_layer_r37("
function_start = require_once(chain, function_token, "fault attribution function")
function_end = chain.find("\nfn parse_upstream_status", function_start)
if function_end < 0:
    fail("fault attribution function", "parse_upstream_status boundary missing")

records_token = "    let records = proxy_telemetry().lifecycles.snapshot();\n"
records_start = chain.find(records_token, function_start, function_end)
if records_start < 0:
    fail("latest-lineage input", "records snapshot anchor missing inside fault attribution")
failed_end_token = "\n    if let Some(record) = failed {"
failed_end = chain.find(failed_end_token, records_start, function_end)
if failed_end < 0:
    fail("latest-lineage input", "if-let failed boundary missing")
failed_segment = chain[records_start:failed_end]
for marker in (
    "let now_ms = Local::now().timestamp_millis();",
    "let cutoff = now_ms.saturating_sub(30 * 60 * 1000);",
    "let failed = records.iter().rev().find",
    "raw_upstream_status",
    "upstream_error",
    "failed:",
):
    if marker not in failed_segment:
        fail("latest-lineage input", f"expected r37 semantic marker missing: {marker}")

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
chain = chain[:records_start] + canonical_failed + chain[failed_end:]

# Re-locate the function after the first rewrite, then normalize the r37 peer
# success/shared-failure section.  Keep the outer `if let Some(record)` closing
# brace outside the replacement so only the intended inner attribution logic is
# touched.
function_start = chain.find(function_token)
function_end = chain.find("\nfn parse_upstream_status", function_start)
peer_start = chain.find("        let other_success =", function_start, function_end)
peer_end_token = "\n    }\n\n    if session.code == \"session_turn_stalled\" {"
peer_end = chain.find(peer_end_token, peer_start, function_end) if peer_start >= 0 else -1
if peer_start < 0 or peer_end < 0:
    fail("shared-upstream input", "r37 peer attribution boundaries missing")
peer_segment = chain[peer_start:peer_end]
for marker in (
    "failed_correlations",
    "fault_session_scoped",
    "fault_session_state",
    "fault_shared_upstream",
    "failed_to_start_turn",
):
    if marker not in peer_segment:
        fail("shared-upstream input", f"expected r37 semantic marker missing: {marker}")

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
chain = chain[:peer_start] + canonical_peer + chain[peer_end:]
CHAIN.write_text(chain, encoding="utf-8")
print("r43 semantic anchor prep: normalized chain-health attribution anchors")


# ---------------------------------------------------------------------------
# runtime_diag.rs
#
# The r26 source has been rustfmt-normalized to a multi-line tuple.  r43's strict
# overlay historically expected the same tuple with the first element on the
# opening line.  Normalize just this one tuple after verifying its semantic
# contents; the r43 overlay immediately replaces it with the expanded classifier
# set and cargo fmt later restores canonical Rust formatting.
# ---------------------------------------------------------------------------
runtime = RUNTIME.read_text(encoding="utf-8")
classify_start = require_once(runtime, "fn classify(lower: &str)", "runtime classify function")
needle_pos = runtime.find('"context automatically compacted"', classify_start)
if needle_pos < 0:
    fail("runtime compact tuple", "context automatically compacted marker missing")
tuple_start = runtime.rfind("        (", classify_start, needle_pos)
tuple_end_marker = "        ),"
tuple_end_pos = runtime.find(tuple_end_marker, needle_pos)
if tuple_start < 0 or tuple_end_pos < 0:
    fail("runtime compact tuple", "tuple boundaries missing")
tuple_end = tuple_end_pos + len(tuple_end_marker)
if tuple_end < len(runtime) and runtime[tuple_end] == "\n":
    tuple_end += 1
segment = runtime[tuple_start:tuple_end]
for marker in ('"context automatically compacted"', '"context_auto_compacted"', '"INFO"'):
    if marker not in segment:
        fail("runtime compact tuple", f"expected semantic marker missing: {marker}")

canonical_runtime_tuple = '''        ("context automatically compacted",
            "context_auto_compacted",
            "INFO",
        ),
'''
runtime = runtime[:tuple_start] + canonical_runtime_tuple + runtime[tuple_end:]
RUNTIME.write_text(runtime, encoding="utf-8")
print("r43 semantic anchor prep: normalized runtime compact classifier anchor")
print("r43 semantic anchor prep: PASS")
