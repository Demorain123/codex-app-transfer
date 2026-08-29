from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R46-GENERIC-REPAIR-SAME-FAULT-GUARD"

text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    print("r46 generic repair same-fault guard already applied")
    raise SystemExit(0)

static_anchor = '''static RECOVERY_LAST: OnceLock<Mutex<Option<Instant>>> = OnceLock::new();

fn recovery_last() -> &'static Mutex<Option<Instant>> {
    RECOVERY_LAST.get_or_init(|| Mutex::new(None))
}
'''
static_new = static_anchor + '''
// CAS-R46-GENERIC-REPAIR-SAME-FAULT-GUARD
// The 45s cooldown prevents double-click bursts. This second guard prevents a user from
// treating the generic repair button as a lottery after reload / cooldown expiry: one
// unchanged health signature gets at most one repair attempt per Transfer process.
static RECOVERY_FAULT_SIGNATURE_LAST: OnceLock<Mutex<Option<String>>> = OnceLock::new();

fn recovery_fault_signature_last() -> &'static Mutex<Option<String>> {
    RECOVERY_FAULT_SIGNATURE_LAST.get_or_init(|| Mutex::new(None))
}

fn recovery_fault_signature_r46(snapshot: &ChainHealthSnapshot) -> String {
    [
        snapshot.overall.as_str(),
        snapshot.diagnosis.code.as_str(),
        snapshot.transfer.code.as_str(),
        snapshot.gateway.code.as_str(),
        snapshot.runtime.layer.code.as_str(),
        snapshot.account.code.as_str(),
        snapshot.upstream.code.as_str(),
        snapshot.session.code.as_str(),
        snapshot.mcp.code.as_str(),
    ]
    .join("|")
}
'''
if static_anchor not in text:
    raise SystemExit("r46 same-fault guard: recovery_last anchor missing")
text = text.replace(static_anchor, static_new, 1)

before_anchor = '''    let before = build_snapshot(&state).await;
    let classification = recovery_classification(&before).to_owned();
'''
before_new = '''    let before = build_snapshot(&state).await;
    let fault_signature = recovery_fault_signature_r46(&before);
    {
        let mut previous = recovery_fault_signature_last().lock().await;
        if previous.as_deref() == Some(fault_signature.as_str()) {
            return Json(json!({
                "success": false,
                "error": "recovery_same_fault_already_attempted",
                "message": "相同故障状态已经执行过一次“尝试修复”。请先查看修复报告/日志并点击“立即检查”；只有健康状态发生变化后才允许再次执行，避免形成重启/刷新循环。",
                "faultSignatureChanged": false,
            }));
        }
        // Record before mutation so even a failed restart/refresh cannot be hammered in a
        // loop. A real health-code change automatically permits the next targeted action.
        *previous = Some(fault_signature);
    }
    let classification = recovery_classification(&before).to_owned();
'''
if before_anchor not in text:
    raise SystemExit("r46 same-fault guard: before snapshot anchor missing")
text = text.replace(before_anchor, before_new, 1)

# Unit tests avoid AdminState/process mutations and prove only signature semantics.
test_anchor = '''fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
'''
tests = r'''#[cfg(test)]
mod r46_generic_repair_loop_guard_tests {
    use super::*;

    fn layer(code: &str) -> HealthLayer {
        HealthLayer::new("error", code, code)
    }

    fn snapshot(upstream_code: &str, diagnosis_code: &str) -> ChainHealthSnapshot {
        ChainHealthSnapshot {
            observed_at: "test".into(),
            overall: "error".into(),
            overall_summary: "test".into(),
            provider: None,
            codex: layer("codex_running"),
            session: layer("session_recent_failure"),
            mcp: layer("mcp_healthy"),
            transfer: layer("transfer_listening"),
            gateway: layer("gateway_healthy"),
            runtime: RuntimeHealth {
                layer: layer("native_runtime_reachable"),
                kind: "test".into(),
                docker_desktop: None,
                docker_server_version: None,
                compose_project: None,
                containers: Vec::new(),
                owner_pid: None,
                owner_process: None,
            },
            account: layer("account_quota_unobserved"),
            upstream: layer(upstream_code),
            diagnosis: layer(diagnosis_code),
            recommendations: Vec::new(),
            privacy: Vec::new(),
        }
    }

    #[test]
    fn r46_same_fault_signature_is_stable_for_unchanged_health_codes() {
        let a = snapshot("upstream_5xx", "fault_upstream");
        let b = snapshot("upstream_5xx", "fault_upstream");
        assert_eq!(recovery_fault_signature_r46(&a), recovery_fault_signature_r46(&b));
    }

    #[test]
    fn r46_same_fault_signature_unlocks_after_meaningful_health_change() {
        let failed = snapshot("upstream_5xx", "fault_upstream");
        let recovered = snapshot("upstream_recent_complete", "fault_none");
        assert_ne!(
            recovery_fault_signature_r46(&failed),
            recovery_fault_signature_r46(&recovered)
        );
    }
}

'''
if test_anchor not in text:
    raise SystemExit("r46 same-fault guard: classification anchor missing")
text = text.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    MARKER,
    "recovery_same_fault_already_attempted",
    "RECOVERY_FAULT_SIGNATURE_LAST",
    "r46_same_fault_signature_unlocks_after_meaningful_health_change",
):
    if invariant not in text:
        raise SystemExit(f"r46 same-fault guard invariant missing: {invariant}")

TARGET.write_text(text, encoding="utf-8")
print("R46 GENERIC REPAIR SAME-FAULT LOOP GUARD PASS")
