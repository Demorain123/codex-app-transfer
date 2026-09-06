from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE"
HOOK_MARKER = "CAS-R63-AUTH-EPOCH-REQUEST-FENCE-HOOK"
RETRY_MARKER = "CAS-R63-INVALID-ENCRYPTED-CONTENT-RECOVERY"

source = FORWARD.read_text(encoding="utf-8")
if MARKER in source and HOOK_MARKER in source and RETRY_MARKER in source:
    print("r63 auth-epoch encrypted-history fence already applied")
    raise SystemExit(0)

# r63 deliberately extends the already-proven r50 portable replay primitive instead
# of inventing a second interpretation of Codex reasoning/compaction items.
for required in (
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "portableize_input_item_r50",
    "PortableReplayStatsR50",
    "r45_conversation_fingerprint",
    "r45_compaction_helper",
):
    if required not in source:
        raise SystemExit(f"r63 requires generated r50 baseline marker/symbol: {required}")

helper_anchor = "pub async fn forward_handler(\n"
if helper_anchor not in source:
    raise SystemExit("r63 forward_handler anchor missing")

if MARKER not in source:
    helpers = r'''
// CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE
//
// A Codex Responses thread can contain provider/account-bound opaque state in
// reasoning.encrypted_content. r50 already protects model-family switches. r63 adds
// the orthogonal authentication-generation boundary: when the same persisted thread
// is observed under a different real ChatGPT account, the on-disk rollout remains
// untouched but every outbound replay for that thread is permanently fenced into a
// portable form. This is intentionally sticky because rewriting a request copy does
// not remove old opaque items from Codex's persisted history.
//
// Only irreversible fingerprints are persisted. Raw account ids, access tokens,
// cookies, prompts, session ids and encrypted blobs are never written or logged.
#[derive(Clone, Debug, PartialEq, Eq)]
struct AuthEpochSessionR63 {
    account_fp: String,
    epoch: u64,
    fence_active: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct AuthEpochDecisionR63 {
    epoch: u64,
    switched: bool,
    fence_active: bool,
    previous_account_fp: Option<String>,
    current_account_fp: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct EncryptedReplayStatsR63 {
    before_bytes: usize,
    after_bytes: usize,
    previous_response_id_dropped: bool,
    reasoning_dropped: usize,
    compaction_portable_messages: usize,
    empty_compactions_dropped: usize,
    unknown_encrypted_items_dropped: usize,
}

fn fingerprint_account_id_r63(value: &str) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in value.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{:08x}", (hash ^ (hash >> 32)) as u32)
}

fn current_chatgpt_account_fingerprint_r63(state: &ProxyState) -> Option<String> {
    // The provider callback is already the canonical lazy reader for the current real
    // ChatGPT auth.json (r25). We consume only account_id, immediately drop the token,
    // and retain only an irreversible 8-hex fingerprint.
    let auth = state.chatgpt_mcp_auth_provider.as_ref().and_then(|provider| provider())?;
    let account_id = auth.account_id?;
    let account_id = account_id.trim();
    if account_id.is_empty() {
        None
    } else {
        Some(fingerprint_account_id_r63(account_id))
    }
}

fn auth_epoch_path_r63() -> Option<std::path::PathBuf> {
    codex_app_transfer_registry::paths::resolve_home().map(|home| {
        home.join(".codex-app-transfer")
            .join("auth-epoch-r63.json")
    })
}

fn load_auth_epoch_sessions_r63() -> std::collections::HashMap<String, AuthEpochSessionR63> {
    let Some(path) = auth_epoch_path_r63() else {
        return std::collections::HashMap::new();
    };
    let Ok(bytes) = std::fs::read(path) else {
        return std::collections::HashMap::new();
    };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        return std::collections::HashMap::new();
    };
    let Some(sessions) = value.get("sessions").and_then(serde_json::Value::as_object) else {
        return std::collections::HashMap::new();
    };
    let mut out = std::collections::HashMap::with_capacity(sessions.len());
    for (session, raw) in sessions {
        let Some(account_fp) = raw.get("account_fp").and_then(serde_json::Value::as_str) else {
            continue;
        };
        let epoch = raw
            .get("epoch")
            .and_then(serde_json::Value::as_u64)
            .unwrap_or(1)
            .max(1);
        let fence_active = raw
            .get("fence_active")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false);
        // Persisted values are fingerprints only. Reject malformed/oversized values
        // rather than accidentally carrying arbitrary text into diagnostics.
        if session.len() > 96 || account_fp.len() > 32 {
            continue;
        }
        out.insert(
            session.clone(),
            AuthEpochSessionR63 {
                account_fp: account_fp.to_owned(),
                epoch,
                fence_active,
            },
        );
    }
    out
}

fn auth_epoch_sessions_r63(
) -> &'static std::sync::Mutex<std::collections::HashMap<String, AuthEpochSessionR63>> {
    static STORE: std::sync::OnceLock<
        std::sync::Mutex<std::collections::HashMap<String, AuthEpochSessionR63>>,
    > = std::sync::OnceLock::new();
    STORE.get_or_init(|| std::sync::Mutex::new(load_auth_epoch_sessions_r63()))
}

fn persist_auth_epoch_sessions_r63(
    sessions: &std::collections::HashMap<String, AuthEpochSessionR63>,
) {
    let Some(path) = auth_epoch_path_r63() else {
        return;
    };
    let mut serial = serde_json::Map::with_capacity(sessions.len());
    for (session, state) in sessions {
        serial.insert(
            session.clone(),
            serde_json::json!({
                "account_fp": state.account_fp,
                "epoch": state.epoch,
                "fence_active": state.fence_active,
            }),
        );
    }
    let payload = serde_json::json!({
        "version": 1,
        "sessions": serial,
    });
    let Ok(bytes) = serde_json::to_vec_pretty(&payload) else {
        return;
    };
    if let Some(parent) = path.parent() {
        if let Err(error) = std::fs::create_dir_all(parent) {
            proxy_telemetry().logs.add(
                "WARN",
                format!("[auth-epoch-r63] action=persist_skip reason=create_dir_failed error={error}"),
            );
            return;
        }
    }
    let tmp = path.with_extension("json.tmp");
    if let Err(error) = std::fs::write(&tmp, bytes) {
        proxy_telemetry().logs.add(
            "WARN",
            format!("[auth-epoch-r63] action=persist_skip reason=write_failed error={error}"),
        );
        return;
    }
    if let Err(error) = std::fs::rename(&tmp, &path) {
        // Windows rename does not replace an existing destination. Fall back to a
        // direct write through rename-via-remove; losing this metadata only reduces
        // pre-emptive protection and never mutates Codex history.
        let _ = std::fs::remove_file(&path);
        if let Err(second) = std::fs::rename(&tmp, &path) {
            proxy_telemetry().logs.add(
                "WARN",
                format!("[auth-epoch-r63] action=persist_skip reason=rename_failed first={error} second={second}"),
            );
            let _ = std::fs::remove_file(&tmp);
        }
    }
}

fn advance_auth_epoch_state_r63(
    previous: Option<AuthEpochSessionR63>,
    current_account_fp: Option<&str>,
) -> (Option<AuthEpochSessionR63>, AuthEpochDecisionR63, bool) {
    let Some(current) = current_account_fp.filter(|value| !value.trim().is_empty()) else {
        let decision = previous
            .as_ref()
            .map(|state| AuthEpochDecisionR63 {
                epoch: state.epoch,
                switched: false,
                fence_active: state.fence_active,
                previous_account_fp: Some(state.account_fp.clone()),
                current_account_fp: None,
            })
            .unwrap_or_default();
        return (previous, decision, false);
    };

    match previous {
        None => {
            let state = AuthEpochSessionR63 {
                account_fp: current.to_owned(),
                epoch: 1,
                fence_active: false,
            };
            let decision = AuthEpochDecisionR63 {
                epoch: 1,
                switched: false,
                fence_active: false,
                previous_account_fp: None,
                current_account_fp: Some(current.to_owned()),
            };
            (Some(state), decision, true)
        }
        Some(mut state) if state.account_fp == current => {
            let decision = AuthEpochDecisionR63 {
                epoch: state.epoch,
                switched: false,
                fence_active: state.fence_active,
                previous_account_fp: Some(state.account_fp.clone()),
                current_account_fp: Some(current.to_owned()),
            };
            (Some(state), decision, false)
        }
        Some(mut state) => {
            let previous_fp = state.account_fp.clone();
            state.account_fp = current.to_owned();
            state.epoch = state.epoch.saturating_add(1).max(2);
            // Sticky by design: the persisted rollout can still contain opaque items
            // from every earlier account generation, so every future replay is fenced.
            state.fence_active = true;
            let decision = AuthEpochDecisionR63 {
                epoch: state.epoch,
                switched: true,
                fence_active: true,
                previous_account_fp: Some(previous_fp),
                current_account_fp: Some(current.to_owned()),
            };
            (Some(state), decision, true)
        }
    }
}

fn observe_auth_epoch_r63(
    session_key: Option<&str>,
    current_account_fp: Option<&str>,
) -> AuthEpochDecisionR63 {
    let Some(session) = session_key.filter(|value| !value.trim().is_empty()) else {
        return AuthEpochDecisionR63::default();
    };
    let Ok(mut guard) = auth_epoch_sessions_r63().lock() else {
        return AuthEpochDecisionR63::default();
    };
    let previous = guard.get(session).cloned();
    let (next, decision, changed) =
        advance_auth_epoch_state_r63(previous, current_account_fp);
    if let Some(next) = next {
        guard.insert(session.to_owned(), next);
    }
    if changed {
        persist_auth_epoch_sessions_r63(&guard);
    }
    if decision.switched {
        proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[auth-epoch-r63] action=switch session={} from={} to={} epoch={} fence_active=true",
                &session[..session.len().min(32)],
                decision.previous_account_fp.as_deref().unwrap_or("-"),
                decision.current_account_fp.as_deref().unwrap_or("-"),
                decision.epoch,
            ),
        );
    }
    decision
}

fn activate_encrypted_history_fence_r63(
    session_key: Option<&str>,
    current_account_fp: Option<&str>,
) {
    let Some(session) = session_key.filter(|value| !value.trim().is_empty()) else {
        return;
    };
    let Ok(mut guard) = auth_epoch_sessions_r63().lock() else {
        return;
    };
    let entry = guard.entry(session.to_owned()).or_insert_with(|| AuthEpochSessionR63 {
        account_fp: current_account_fp.unwrap_or("").to_owned(),
        epoch: 1,
        fence_active: true,
    });
    if entry.account_fp.is_empty() {
        if let Some(current) = current_account_fp {
            entry.account_fp = current.to_owned();
        }
    }
    entry.fence_active = true;
    persist_auth_epoch_sessions_r63(&guard);
}

fn portableize_encrypted_history_r63(
    body: &[u8],
    drop_unknown_encrypted_items: bool,
) -> Option<(Vec<u8>, EncryptedReplayStatsR63)> {
    let mut value = serde_json::from_slice::<serde_json::Value>(body).ok()?;
    let obj = value.as_object_mut()?;
    let mut stats = EncryptedReplayStatsR63 {
        before_bytes: body.len(),
        ..EncryptedReplayStatsR63::default()
    };
    let mut changed = false;

    if obj
        .get("previous_response_id")
        .is_some_and(|value| !value.is_null())
    {
        obj.remove("previous_response_id");
        stats.previous_response_id_dropped = true;
        changed = true;
    }

    let mut lower = |item: serde_json::Value| -> Option<serde_json::Value> {
        let kind = item
            .get("type")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("");
        match kind {
            "reasoning" => {
                stats.reasoning_dropped += 1;
                None
            }
            "compaction" | "context_compaction" | "compaction_summary" => {
                let summary = item
                    .get("encrypted_content")
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("")
                    .trim();
                if summary.is_empty() {
                    stats.empty_compactions_dropped += 1;
                    None
                } else {
                    stats.compaction_portable_messages += 1;
                    Some(serde_json::json!({
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": summary}],
                    }))
                }
            }
            _ if drop_unknown_encrypted_items
                && item
                    .get("encrypted_content")
                    .and_then(serde_json::Value::as_str)
                    .is_some_and(|value| !value.trim().is_empty()) =>
            {
                stats.unknown_encrypted_items_dropped += 1;
                None
            }
            _ => Some(item),
        }
    };

    if let Some(input) = obj.get_mut("input") {
        match input {
            serde_json::Value::Array(items) => {
                let old = std::mem::take(items);
                let old_len = old.len();
                let mut portable = Vec::with_capacity(old_len);
                for item in old {
                    if let Some(item) = lower(item) {
                        portable.push(item);
                    }
                }
                if portable.len() != old_len
                    || stats.compaction_portable_messages > 0
                    || stats.unknown_encrypted_items_dropped > 0
                {
                    changed = true;
                }
                *items = portable;
            }
            serde_json::Value::Object(_) => {
                let item = std::mem::replace(input, serde_json::Value::Null);
                match lower(item) {
                    Some(item) => *input = item,
                    None => *input = serde_json::Value::Array(Vec::new()),
                }
                if stats.reasoning_dropped > 0
                    || stats.compaction_portable_messages > 0
                    || stats.empty_compactions_dropped > 0
                    || stats.unknown_encrypted_items_dropped > 0
                {
                    changed = true;
                }
            }
            _ => {}
        }
    }

    if !changed {
        return None;
    }
    let rewritten = serde_json::to_vec(&value).ok()?;
    stats.after_bytes = rewritten.len();
    Some((rewritten, stats))
}

fn invalid_encrypted_content_error_r63(body: &[u8]) -> bool {
    let text = String::from_utf8_lossy(body).to_ascii_lowercase();
    if text.contains("invalid_encrypted_content") {
        return true;
    }
    text.contains("encrypted content")
        && (text.contains("could not be decrypted")
            || text.contains("could not be verified")
            || text.contains("could not be parsed"))
}

fn log_encrypted_replay_r63(
    action: &str,
    session_key: Option<&str>,
    epoch: u64,
    stats: &EncryptedReplayStatsR63,
) {
    let session = session_key
        .map(|value| &value[..value.len().min(32)])
        .unwrap_or("-");
    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[encrypted-history-r63] action={} session={} auth_epoch={} previous_response_id_dropped={} reasoning_dropped={} compaction_portable_messages={} empty_compactions_dropped={} unknown_encrypted_items_dropped={} before_bytes={} after_bytes={}",
            action,
            session,
            epoch,
            stats.previous_response_id_dropped,
            stats.reasoning_dropped,
            stats.compaction_portable_messages,
            stats.empty_compactions_dropped,
            stats.unknown_encrypted_items_dropped,
            stats.before_bytes,
            stats.after_bytes,
        ),
    );
}

'''
    source = source.replace(helper_anchor, helpers + helper_anchor, 1)

if HOOK_MARKER not in source:
    hook_anchor = "    let r46_forensics = analyze_request_forensics_r46(\n"
    if hook_anchor not in source:
        raise SystemExit("r63 request-fence anchor missing (r50/r46 composition drift)")
    hook = r'''    // CAS-R63-AUTH-EPOCH-REQUEST-FENCE-HOOK
    // r50 has already handled a model-family switch above. r63 independently
    // observes the real ChatGPT account generation. Once a persisted thread crosses
    // an account boundary, keep every future outbound copy portable because the
    // old encrypted items remain in Codex's on-disk rollout.
    let r63_session_key = if is_local_responses_route(&client_path) {
        r45_conversation_fingerprint.clone().or_else(|| {
            let fallback = request_lifecycle_correlation_r34(&parts.headers);
            (fallback != "uncorrelated").then_some(fallback)
        })
    } else {
        None
    };
    let r63_account_fp = if r63_session_key.is_some() && !r45_compaction_helper {
        current_chatgpt_account_fingerprint_r63(&state)
    } else {
        None
    };
    let r63_auth_decision = if !r45_compaction_helper {
        observe_auth_epoch_r63(r63_session_key.as_deref(), r63_account_fp.as_deref())
    } else {
        AuthEpochDecisionR63::default()
    };
    if r63_auth_decision.fence_active && !r45_compaction_helper {
        if let Some((rewritten, stats)) = portableize_encrypted_history_r63(&body_bytes, false) {
            body_bytes = Bytes::from(rewritten);
            log_encrypted_replay_r63(
                "auth_boundary_portable_replay",
                r63_session_key.as_deref(),
                r63_auth_decision.epoch,
                &stats,
            );
        }
    }

'''
    source = source.replace(hook_anchor, hook + hook_anchor, 1)

if RETRY_MARKER not in source:
    retry_anchor = "        if codex_app_transfer_adapters::is_orphan_function_call_error(&body_bytes) {\n"
    if retry_anchor not in source:
        raise SystemExit("r63 400 retry anchor missing")
    retry = r'''        // CAS-R63-INVALID-ENCRYPTED-CONTENT-RECOVERY
        // A backend-confirmed encrypted-content failure is deterministic for the
        // same replay. Rebuild one portable request and retry exactly once. The
        // retry response bypasses this initial-400 decision block, so this cannot
        // become a retry loop. Unknown encrypted item types are dropped only here,
        // after explicit backend evidence; the pre-emptive auth fence is narrower.
        if invalid_encrypted_content_error_r63(&body_bytes) {
            activate_encrypted_history_fence_r63(
                r63_session_key.as_deref(),
                r63_account_fp.as_deref(),
            );
            match portableize_encrypted_history_r63(&plan.body, true) {
                Some((repaired, stats)) => {
                    log_encrypted_replay_r63(
                        "invalid_encrypted_content_recovery_retry_1",
                        r63_session_key.as_deref(),
                        r63_auth_decision.epoch.max(1),
                        &stats,
                    );
                    plan.body = Bytes::from(repaired);
                    let pair = build_and_send_upstream(
                        &state,
                        &parts.method,
                        &parts.headers,
                        &resolved,
                        &plan.body,
                        &plan.upstream_headers,
                        &upstream_url,
                    )
                    .await?;
                    telemetry.logs.add(
                        "INFO",
                        format!(
                            "[encrypted-history-r63] action=recovery_retry_result retry=1 status={} provider={}",
                            pair.0.status().as_u16(),
                            resolved.provider.id
                        ),
                    );
                    live_resp = Some(pair.0);
                    outbound_headers_snapshot = pair.1;
                }
                None => {
                    telemetry.logs.add(
                        "WARN",
                        "[encrypted-history-r63] action=recovery_skip reason=no_portable_rewrite_available"
                            .to_string(),
                    );
                    captured_4xx = Some((st, hs, body_bytes));
                }
            }
        } else if codex_app_transfer_adapters::is_orphan_function_call_error(&body_bytes) {
'''
    source = source.replace(retry_anchor, retry, 1)

# Focused pure regression tests. They deliberately avoid touching the global persisted
# store so cargo test stays deterministic/parallel-safe.
test_anchor = '''    #[test]
    fn r46_metadata_truth_keeps_feature_flag_out_of_request_role() {
'''
if "r63_auth_epoch_switch_is_sticky_and_increments" not in source:
    if test_anchor not in source:
        raise SystemExit("r63 focused-test anchor missing")
    tests = r'''    #[test]
    fn r63_auth_epoch_switch_is_sticky_and_increments() {
        let (first, d1, changed1) = advance_auth_epoch_state_r63(None, Some("acct-a"));
        assert!(changed1);
        assert!(!d1.switched);
        assert!(!d1.fence_active);
        assert_eq!(d1.epoch, 1);

        let (second, d2, changed2) = advance_auth_epoch_state_r63(first, Some("acct-b"));
        assert!(changed2);
        assert!(d2.switched);
        assert!(d2.fence_active);
        assert_eq!(d2.epoch, 2);

        let (_third, d3, changed3) = advance_auth_epoch_state_r63(second, Some("acct-b"));
        assert!(!changed3);
        assert!(!d3.switched);
        assert!(d3.fence_active, "fence must remain sticky after account switch");
        assert_eq!(d3.epoch, 2);
    }

    #[test]
    fn r63_auth_boundary_drops_reasoning_and_portableizes_compaction_only() {
        let body = br#"{
            "model":"gpt-5.6-luna",
            "previous_response_id":"resp_old_account",
            "input":[
                {"type":"message","role":"user","content":"keep me"},
                {"type":"reasoning","encrypted_content":"OPAQUE_ACCOUNT_A"},
                {"type":"compaction","encrypted_content":"portable checkpoint"},
                {"type":"future_private","encrypted_content":"UNKNOWN_KEEP_PREEMPTIVE"}
            ]
        }"#;
        let (rewritten, stats) = portableize_encrypted_history_r63(body, false).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&rewritten).unwrap();
        assert!(value.get("previous_response_id").is_none());
        let input = value["input"].as_array().unwrap();
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("reasoning")));
        assert!(input.iter().all(|item| item.get("type").and_then(|v| v.as_str()) != Some("compaction")));
        assert!(input.iter().any(|item| item.get("type").and_then(|v| v.as_str()) == Some("future_private")));
        assert!(input.iter().any(|item| item.pointer("/content/0/text").and_then(|v| v.as_str()) == Some("portable checkpoint")));
        assert_eq!(stats.reasoning_dropped, 1);
        assert_eq!(stats.compaction_portable_messages, 1);
        assert_eq!(stats.unknown_encrypted_items_dropped, 0);
    }

    #[test]
    fn r63_explicit_invalid_error_drops_unknown_encrypted_items() {
        let body = br#"{
            "model":"gpt-5.6-luna",
            "input":[
                {"type":"future_private","encrypted_content":"OPAQUE_UNKNOWN"},
                {"type":"message","role":"user","content":"survives"}
            ]
        }"#;
        let (rewritten, stats) = portableize_encrypted_history_r63(body, true).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&rewritten).unwrap();
        let input = value["input"].as_array().unwrap();
        assert_eq!(input.len(), 1);
        assert_eq!(input[0]["type"], "message");
        assert_eq!(stats.unknown_encrypted_items_dropped, 1);
    }

    #[test]
    fn r63_invalid_encrypted_classifier_is_narrow() {
        assert!(invalid_encrypted_content_error_r63(
            br#"{"error":{"code":"invalid_encrypted_content"}}"#
        ));
        assert!(invalid_encrypted_content_error_r63(
            b"Encrypted content could not be decrypted or parsed"
        ));
        assert!(!invalid_encrypted_content_error_r63(
            b"encrypted content was accepted successfully"
        ));
        assert!(!invalid_encrypted_content_error_r63(b"ordinary bad request"));
    }

    #[test]
    fn r63_same_account_state_does_not_activate_fence() {
        let state = AuthEpochSessionR63 {
            account_fp: "acct-a".to_owned(),
            epoch: 7,
            fence_active: false,
        };
        let (_next, decision, changed) =
            advance_auth_epoch_state_r63(Some(state), Some("acct-a"));
        assert!(!changed);
        assert!(!decision.switched);
        assert!(!decision.fence_active);
        assert_eq!(decision.epoch, 7);
    }

'''
    source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    MARKER,
    HOOK_MARKER,
    RETRY_MARKER,
    "auth-epoch-r63.json",
    "current_chatgpt_account_fingerprint_r63",
    "portableize_encrypted_history_r63",
    "invalid_encrypted_content_error_r63",
    "invalid_encrypted_content_recovery_retry_1",
    "r63_auth_epoch_switch_is_sticky_and_increments",
    "r63_explicit_invalid_error_drops_unknown_encrypted_items",
):
    if invariant not in source:
        raise SystemExit(f"r63 generated-source invariant missing: {invariant}")

FORWARD.write_text(source, encoding="utf-8")
print("R63 AUTH-EPOCH ENCRYPTED-HISTORY FENCE PASS")
print("- persisted session/account fingerprints only; no raw account/token/session/encrypted blob is written")
print("- account boundary activates a sticky per-session portable replay fence")
print("- reasoning opaque state is dropped; plaintext compaction checkpoint is preserved as a standard message")
print("- explicit invalid_encrypted_content performs exactly one portable retry and then surfaces the result")
print("- same-account/same-generation requests remain untouched until a fence is actually needed")
