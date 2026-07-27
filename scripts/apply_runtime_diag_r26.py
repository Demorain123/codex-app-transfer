from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"patched {rel}")


def insert_once(rel: str, anchor: str, block: str, marker: str) -> None:
    text = read(rel)
    if marker in text:
        print(f"already patched {rel}: {marker}")
        return
    if anchor not in text:
        raise SystemExit(f"r26 anchor missing in {rel}: {anchor[:100]!r}")
    write(rel, text.replace(anchor, f"{block}\n\n{anchor}", 1))


# Keep the Windows watcher itself as a plain Rust template so future official
# updates can replay this diagnostic layer without carrying generated-source diffs.
write("src-tauri/src/runtime_diag.rs", read("scripts/runtime_diag_r26.rs"))

insert_once(
    "src-tauri/src/main.rs",
    '#[cfg(target_os = "windows")]\nmod windows_msix;',
    '#[cfg(target_os = "windows")]\nmod runtime_diag; // CAS-RUNTIME-DIAG-R26-MODULE',
    "CAS-RUNTIME-DIAG-R26-MODULE",
)
insert_once(
    "src-tauri/src/main.rs",
    "            tauri::async_runtime::spawn(codex_quota_injector::run_quota_daemon());",
    '            #[cfg(target_os = "windows")]\n            runtime_diag::start_runtime_diag_daemon(); // CAS-RUNTIME-DIAG-R26-START',
    "CAS-RUNTIME-DIAG-R26-START",
)

FORWARD_HELPERS = r'''// CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK
// Diagnostic-only state machine. It correlates repeated HTTP failures for one
// spawned child without logging prompts, request bodies, raw IDs, or credentials.
#[derive(Clone, Debug)]
struct SubagentFailureChainCtxR26 {
    child: String,
    parent: String,
    model: String,
    request_bytes: usize,
    remote_compaction_v2: bool,
}

#[derive(Default, Debug)]
struct SubagentFailureChainStateR26 {
    sequence: Vec<u16>,
    streak: u32,
    peak_body_bytes: usize,
    remote_compaction_v2: bool,
}

static SUBAGENT_FAILURE_CHAINS_R26: std::sync::OnceLock<
    std::sync::Mutex<std::collections::HashMap<String, SubagentFailureChainStateR26>>,
> = std::sync::OnceLock::new();

fn subagent_failure_chain_store_r26() -> &'static std::sync::Mutex<
    std::collections::HashMap<String, SubagentFailureChainStateR26>,
> {
    SUBAGENT_FAILURE_CHAINS_R26
        .get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

fn bytes_contains_ascii_r26(body: &[u8], needle: &[u8]) -> bool {
    !needle.is_empty() && body.windows(needle.len()).any(|window| window == needle)
}

fn first_identity_fingerprint_r26(headers: &HeaderMap, names: &[&str]) -> String {
    for name in names {
        let fp = sub2api_retry_runtime_diag_header_fingerprint(headers, name);
        if fp != "-" {
            return fp;
        }
    }
    "-".to_string()
}

fn observe_subagent_failure_chain_request_r26(
    provider: &codex_app_transfer_registry::Provider,
    headers: &HeaderMap,
    model: Option<&str>,
    body: &[u8],
) -> Option<SubagentFailureChainCtxR26> {
    if !sub2api_retry_runtime_diag_provider_enabled(provider)
        || !sub2api_retry_runtime_diag_is_subagent(headers)
    {
        return None;
    }
    let child = first_identity_fingerprint_r26(
        headers,
        &["x-client-request-id", "thread-id", "x-openai-subagent"],
    );
    let parent = first_identity_fingerprint_r26(headers, &["x-codex-parent-thread-id"]);
    let remote_compaction_v2 = bytes_contains_ascii_r26(body, b"remote_compaction_v2");
    let request_bytes = body.len();
    let model = model.unwrap_or("<unknown>").to_string();

    let existing_failure = subagent_failure_chain_store_r26()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .get(&child)
        .is_some_and(|state| state.streak > 0);
    if remote_compaction_v2 || request_bytes >= 512 * 1024 || existing_failure {
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[subagent-chain-r26] event=request child={} parent={} model={} request_bytes={} remote_compaction_v2={} existing_failure={}",
                child, parent, model, request_bytes, remote_compaction_v2, existing_failure
            ),
        );
    }
    Some(SubagentFailureChainCtxR26 {
        child,
        parent,
        model,
        request_bytes,
        remote_compaction_v2,
    })
}

fn record_subagent_failure_chain_result_r26(
    ctx: Option<&SubagentFailureChainCtxR26>,
    status: u16,
) {
    let Some(ctx) = ctx else {
        return;
    };
    if status < 400 {
        let recovered = {
            let mut store = subagent_failure_chain_store_r26()
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            store.remove(&ctx.child).filter(|state| state.streak > 0)
        };
        if let Some(state) = recovered {
            let sequence = state
                .sequence
                .iter()
                .map(u16::to_string)
                .collect::<Vec<_>>()
                .join(">");
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[subagent-chain-r26] event=recovered child={} parent={} model={} prior_failure_sequence={} prior_failure_streak={} peak_body_bytes={} remote_compaction_v2={}",
                    ctx.child,
                    ctx.parent,
                    ctx.model,
                    sequence,
                    state.streak,
                    state.peak_body_bytes,
                    state.remote_compaction_v2
                ),
            );
        }
        return;
    }
    if status >= 600 {
        return;
    }

    let (sequence, streak, peak_body_bytes, compact, post_transient_to_400) = {
        let mut store = subagent_failure_chain_store_r26()
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if store.len() >= 256 && !store.contains_key(&ctx.child) {
            if let Some(key) = store.keys().next().cloned() {
                store.remove(&key);
            }
        }
        let state = store.entry(ctx.child.clone()).or_default();
        let had_transient = state
            .sequence
            .iter()
            .any(|code| matches!(*code, 429 | 502 | 503 | 504));
        state.streak = state.streak.saturating_add(1);
        state.peak_body_bytes = state.peak_body_bytes.max(ctx.request_bytes);
        state.remote_compaction_v2 |= ctx.remote_compaction_v2;
        state.sequence.push(status);
        if state.sequence.len() > 8 {
            state.sequence.remove(0);
        }
        (
            state.sequence.iter().map(u16::to_string).collect::<Vec<_>>().join(">"),
            state.streak,
            state.peak_body_bytes,
            state.remote_compaction_v2,
            status == 400 && had_transient,
        )
    };

    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[subagent-chain-r26] event=failure child={} parent={} model={} status={} failure_sequence={} failure_streak={} request_bytes={} peak_body_bytes={} remote_compaction_v2={} post_transient_to_400={}",
            ctx.child,
            ctx.parent,
            ctx.model,
            status,
            sequence,
            streak,
            ctx.request_bytes,
            peak_body_bytes,
            compact,
            post_transient_to_400
        ),
    );
}

#[cfg(test)]
mod subagent_failure_chain_r26_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "r26-test",
            "name": "r26-test",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "sk-test",
            "models": {},
            "sub2apiGrokCompat": compat
        }))
        .unwrap()
    }

    #[test]
    fn subagent_failure_chain_r26_detects_remote_compaction_marker() {
        assert!(bytes_contains_ascii_r26(
            br#"{"type":"remote_compaction_v2"}"#,
            b"remote_compaction_v2"
        ));
        assert!(!bytes_contains_ascii_r26(b"normal request", b"remote_compaction_v2"));
    }

    #[test]
    fn subagent_failure_chain_r26_scopes_to_explicit_compat_children() {
        let mut child = HeaderMap::new();
        child.insert("x-openai-subagent", "worker-a".parse().unwrap());
        child.insert("x-codex-parent-thread-id", "parent-a".parse().unwrap());
        assert!(observe_subagent_failure_chain_request_r26(
            &provider(true), &child, Some("grok-4.5"), b"{}"
        ).is_some());
        assert!(observe_subagent_failure_chain_request_r26(
            &provider(false), &child, Some("grok-4.5"), b"{}"
        ).is_none());
        assert!(observe_subagent_failure_chain_request_r26(
            &provider(true), &HeaderMap::new(), Some("grok-4.5"), b"{}"
        ).is_none());
    }

    #[test]
    fn subagent_failure_chain_r26_fingerprints_identity_instead_of_echoing_it() {
        let raw = "019f94f6-09ce-7942-95d3-28d74688a336";
        let mut headers = HeaderMap::new();
        headers.insert("x-client-request-id", raw.parse().unwrap());
        let fp = first_identity_fingerprint_r26(&headers, &["x-client-request-id"]);
        assert_ne!(fp, raw);
        assert_eq!(fp.len(), 8);
    }
}
'''

insert_once(
    "crates/proxy/src/forward.rs",
    "/// CAS-SUB2API-STREAM-RETRY-DIAG-R19-HOOK",
    FORWARD_HELPERS,
    "CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK",
)

forward = read("crates/proxy/src/forward.rs")
if "CAS-SUBAGENT-FAILURE-CHAIN-R26-REQUEST" not in forward:
    anchor = """    let retry_runtime_diag_model = resolved_model.as_deref().or(upstream_model.as_deref());\n    log_sub2api_retry_runtime_diag(&resolved.provider, &parts.headers, retry_runtime_diag_model);\n"""
    if anchor not in forward:
        raise SystemExit("r26 request-chain anchor missing in forward.rs")
    forward = forward.replace(
        anchor,
        anchor
        + """    // CAS-SUBAGENT-FAILURE-CHAIN-R26-REQUEST\n    let subagent_failure_chain_ctx_r26 = observe_subagent_failure_chain_request_r26(\n        &resolved.provider,\n        &parts.headers,\n        retry_runtime_diag_model,\n        &plan.body,\n    );\n""",
        1,
    )

if "CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT" not in forward:
    anchor = """    telemetry.logs.add(\n        if success { \"SUCCESS\" } else { \"ERROR\" },\n        format!(\"upstream status {}\", response_plan.status.as_u16()),\n    );\n"""
    if anchor not in forward:
        raise SystemExit("r26 result-chain anchor missing in forward.rs")
    forward = forward.replace(
        anchor,
        anchor
        + """    // CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT\n    record_subagent_failure_chain_result_r26(\n        subagent_failure_chain_ctx_r26.as_ref(),\n        response_plan.status.as_u16(),\n    );\n""",
        1,
    )
write("crates/proxy/src/forward.rs", forward)

checks = {
    "src-tauri/src/runtime_diag.rs": "CAS-RUNTIME-DIAG-R26",
    "src-tauri/src/main.rs": "CAS-RUNTIME-DIAG-R26-START",
    "crates/proxy/src/forward.rs": "CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT",
}
for rel, marker in checks.items():
    if marker not in read(rel):
        raise SystemExit(f"r26 materialization missing marker in {rel}: {marker}")
print("r26 runtime diagnostics materialization gate: complete")
