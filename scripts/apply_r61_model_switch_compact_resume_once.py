from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R61-MODEL-SWITCH-COMPACT-RESUME-ONCE"

source = FORWARD.read_text(encoding="utf-8")
if MARKER in source:
    print("r61 model-switch compact resume-once already applied")
    raise SystemExit(0)

for required in (
    "CAS-R45-MODEL-SWITCH-CONTINUITY",
    "CAS-R46-MODEL-SWITCH-FORENSICS",
    "effective_model_for_r45",
    "is_compaction_request_r46",
    "log_request_forensics_r46",
):
    if required not in source:
        raise SystemExit(f"r61 requires materialized r45/r46 baseline marker: {required}")

helper_anchor = "pub async fn forward_handler(\n"
if helper_anchor not in source:
    raise SystemExit("r61: forward_handler anchor missing")

helpers = r'''
// CAS-R61-MODEL-SWITCH-COMPACT-RESUME-ONCE
//
// Codex intentionally performs a CompHashChanged pre-turn compact with the previous
// step context first.  On supported failures, current Codex then retries that compact
// with the *current* turn/model context before continuing the same pending turn.
//
// r45 predates that upstream fallback.  Its stale-helper guard correctly keeps ordinary
// compaction helpers on the last effective model, but it also rebinds the current-model
// fallback back to the previous model.  In a Luna -> Grok switch this can leave the
// user in a repeated `compact -> turn ends -> next send compacts again` loop.
//
// r61 uses the upstream state machine instead of inventing a second one:
//   1. for an explicitly opted-in Sub2API Responses provider, the first
//      CompHashChanged helper on the *previous* effective model is answered locally
//      with one deterministic invalid_request_error;
//   2. Codex's built-in previous-model -> current-model fallback issues the compact
//      again with the selected turn context;
//   3. a tiny per-conversation process-local marker temporarily exempts that fallback
//      helper from r45's stale-helper rebind;
//   4. the next normal main turn clears the marker, then r45 advances the authoritative
//      effective model as usual.
//
// No prompt text, raw session/thread id, credential, tool argument or encrypted content
// is retained.  Keys are the existing FNV conversation fingerprints.  State is bounded
// and expires after five minutes so an interrupted/cancelled turn cannot poison later
// traffic.
#[derive(Clone, Debug)]
struct ModelSwitchCompactResumeR61 {
    previous_model: String,
    fallback_model: Option<String>,
    armed_at: std::time::Instant,
}

static MODEL_SWITCH_COMPACT_RESUME_R61: std::sync::OnceLock<
    std::sync::Mutex<std::collections::HashMap<String, ModelSwitchCompactResumeR61>>,
> = std::sync::OnceLock::new();

fn model_switch_compact_resume_store_r61(
) -> &'static std::sync::Mutex<std::collections::HashMap<String, ModelSwitchCompactResumeR61>> {
    MODEL_SWITCH_COMPACT_RESUME_R61
        .get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new()))
}

fn prune_model_switch_compact_resume_r61(
    store: &mut std::collections::HashMap<String, ModelSwitchCompactResumeR61>,
) {
    const TTL: std::time::Duration = std::time::Duration::from_secs(5 * 60);
    store.retain(|_, state| state.armed_at.elapsed() <= TTL);
    while store.len() > 256 {
        let Some(oldest) = store
            .iter()
            .min_by_key(|(_, state)| state.armed_at)
            .map(|(key, _)| key.clone())
        else {
            break;
        };
        store.remove(&oldest);
    }
}

fn sub2api_comp_hash_fallback_enabled_r61(
    provider: &codex_app_transfer_registry::Provider,
) -> bool {
    provider.api_format.trim().eq_ignore_ascii_case("responses")
        && provider
            .extra
            .get("sub2apiGrokCompat")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
}

fn is_comp_hash_changed_r61(headers: &HeaderMap) -> bool {
    turn_metadata_r46(headers)
        .as_ref()
        .and_then(|value| value.get("compaction"))
        .and_then(|value| value.get("reason"))
        .and_then(serde_json::Value::as_str)
        .is_some_and(|reason| reason == "comp_hash_changed")
}

fn arm_previous_model_compact_fallback_r61(
    fingerprint: &str,
    previous_model: &str,
) -> bool {
    let previous_model = strip_internal_model_suffix(previous_model.trim());
    if previous_model.is_empty() {
        return false;
    }
    let mut store = model_switch_compact_resume_store_r61()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    prune_model_switch_compact_resume_r61(&mut store);
    if store.contains_key(fingerprint) {
        return false;
    }
    store.insert(
        fingerprint.to_owned(),
        ModelSwitchCompactResumeR61 {
            previous_model: previous_model.clone(),
            fallback_model: None,
            armed_at: std::time::Instant::now(),
        },
    );
    drop(store);
    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[model-switch-r61] action=arm_current_model_fallback session={} previous_model={} reason=comp_hash_changed",
            &fingerprint[..8.min(fingerprint.len())],
            previous_model,
        ),
    );
    true
}

fn allow_armed_current_model_compaction_r61(
    fingerprint: &str,
    incoming_model: &str,
) -> bool {
    let incoming_model = strip_internal_model_suffix(incoming_model.trim());
    if incoming_model.is_empty() {
        return false;
    }

    let mut store = model_switch_compact_resume_store_r61()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    prune_model_switch_compact_resume_r61(&mut store);

    let mut log_line: Option<(String, String)> = None;
    let mut remove_state = false;
    let allow = if let Some(state) = store.get_mut(fingerprint) {
        match state.fallback_model.as_deref() {
            None => {
                state.fallback_model = Some(incoming_model.clone());
                log_line = Some((state.previous_model.clone(), incoming_model.clone()));
                true
            }
            Some(expected) if model_equivalent_r45(expected, &incoming_model) => true,
            Some(_) => {
                remove_state = true;
                false
            }
        }
    } else {
        false
    };
    if remove_state {
        store.remove(fingerprint);
    }
    drop(store);

    if let Some((previous_model, fallback_model)) = log_line {
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[model-switch-r61] action=allow_current_model_compaction session={} previous_model={} fallback_model={}",
                &fingerprint[..8.min(fingerprint.len())],
                previous_model,
                fallback_model,
            ),
        );
    }
    allow
}

fn clear_model_switch_compact_resume_r61(
    fingerprint: &str,
    target_model: Option<&str>,
) {
    let removed = {
        let mut store = model_switch_compact_resume_store_r61()
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        prune_model_switch_compact_resume_r61(&mut store);
        store.remove(fingerprint)
    };
    if let Some(state) = removed {
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[model-switch-r61] action=resume_main_turn session={} previous_model={} compact_model={} target_model={}",
                &fingerprint[..8.min(fingerprint.len())],
                state.previous_model,
                state.fallback_model.as_deref().unwrap_or("<unknown>"),
                target_model.unwrap_or("<unknown>"),
            ),
        );
    }
}

fn previous_model_compact_fallback_response_r61() -> Result<Response, ForwardError> {
    // HTTP 400 + OpenAI invalid_request_error is deliberate.  Current Codex classifies
    // InvalidRequest/UnexpectedStatus as eligible for previous-model -> current-model
    // compaction fallback.  This response never reaches an upstream provider.
    let body = serde_json::json!({
        "error": {
            "message": "r61: retry compaction with the current turn model",
            "type": "invalid_request_error",
            "param": "model",
            "code": "invalid_prompt"
        }
    });
    Ok(Response::builder()
        .status(StatusCode::BAD_REQUEST)
        .header("content-type", "application/json; charset=utf-8")
        .header("cache-control", "no-store")
        .body(Body::from(body.to_string()))?)
}

#[cfg(test)]
mod model_switch_compact_resume_r61_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "r61-test",
            "name": "r61-test",
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
    fn r61_provider_gate_is_explicit_sub2api_responses_only() {
        assert!(sub2api_comp_hash_fallback_enabled_r61(&provider(true)));
        assert!(!sub2api_comp_hash_fallback_enabled_r61(&provider(false)));
    }

    #[test]
    fn r61_comp_hash_reason_is_structural_metadata() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"compaction","compaction":{"trigger":"auto","reason":"comp_hash_changed"}}"#
                .parse()
                .unwrap(),
        );
        assert!(is_comp_hash_changed_r61(&headers));
        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"compaction","compaction":{"trigger":"auto","reason":"context_limit"}}"#
                .parse()
                .unwrap(),
        );
        assert!(!is_comp_hash_changed_r61(&headers));
    }

    #[test]
    fn r61_synthetic_failure_is_non_retryable_style_http_400() {
        let response = previous_model_compact_fallback_response_r61().unwrap();
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            response.headers().get("content-type").unwrap(),
            "application/json; charset=utf-8"
        );
    }
}

'''
source = source.replace(helper_anchor, helpers + helper_anchor, 1)

# r46 has already made request_kind metadata authoritative and computed the persisted
# r45 effective model before this block.  Consult r61 state *before* r45's stale-helper
# rebind so the current-model fallback is not rewritten back to the previous model.
rebind_anchor = '''    let r45_compaction_helper = is_compaction_request_r46(&parts.headers, &body_bytes);
    if r45_compaction_helper {
'''
rebind_new = '''    let r45_compaction_helper = is_compaction_request_r46(&parts.headers, &body_bytes);
    let r61_direct_current_model_compaction = r45_compaction_helper
        && is_comp_hash_changed_r61(&parts.headers)
        && match (original_model.as_deref(), r46_effective_before.as_deref()) {
            (Some(incoming), Some(effective)) => !model_equivalent_r45(incoming, effective),
            _ => false,
        };
    let r61_fallback_attempt = if r45_compaction_helper {
        match (
            r45_conversation_fingerprint.as_deref(),
            original_model.as_deref(),
        ) {
            (Some(fingerprint), Some(incoming)) => {
                allow_armed_current_model_compaction_r61(fingerprint, incoming)
                    || r61_direct_current_model_compaction
            }
            _ => r61_direct_current_model_compaction,
        }
    } else {
        false
    };
    if r61_direct_current_model_compaction && !r61_fallback_attempt {
        unreachable!("direct current-model compaction must be allowed");
    }
    if r61_direct_current_model_compaction {
        if let (Some(fingerprint), Some(incoming)) = (
            r45_conversation_fingerprint.as_deref(),
            original_model.as_deref(),
        ) {
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[model-switch-r61] action=allow_direct_current_model_compaction session={} model={} reason=comp_hash_changed",
                    &fingerprint[..8.min(fingerprint.len())],
                    incoming,
                ),
            );
        }
    }
    if r45_compaction_helper && !r61_fallback_attempt {
'''
if rebind_anchor not in source:
    raise SystemExit("r61: r46/r45 compaction rebind anchor missing")
source = source.replace(rebind_anchor, rebind_new, 1)

resume_anchor = '''    log_request_forensics_r46(&r46_forensics);

    // Only a main, non-helper turn can advance the authoritative session model.
'''
resume_new = '''    log_request_forensics_r46(&r46_forensics);

    // First CompHashChanged helper still uses the previous effective model.  Fail it
    // locally exactly once so Codex activates its built-in current-model compact
    // fallback.  An already-armed/direct fallback is allowed through untouched.
    let r61_previous_model_attempt = r45_compaction_helper
        && is_comp_hash_changed_r61(&parts.headers)
        && !r61_fallback_attempt
        && match (original_model.as_deref(), r46_effective_before.as_deref()) {
            (Some(incoming), Some(effective)) => model_equivalent_r45(incoming, effective),
            _ => false,
        };
    if r61_previous_model_attempt
        && !is_auxiliary_model_request_r45(&parts.headers)
        && sub2api_comp_hash_fallback_enabled_r61(&resolved.provider)
    {
        if let (Some(fingerprint), Some(previous_model)) = (
            r45_conversation_fingerprint.as_deref(),
            r46_effective_before.as_deref(),
        ) {
            if arm_previous_model_compact_fallback_r61(fingerprint, previous_model) {
                return previous_model_compact_fallback_response_r61();
            }
        }
    }

    // A normal main turn means the preflight compact has handed control back to the
    // user's pending turn.  Clear r61 first; r45 immediately below remains the single
    // authority that advances/persists the effective session model.
    if !r45_compaction_helper && !is_auxiliary_model_request_r45(&parts.headers) {
        if let Some(fingerprint) = r45_conversation_fingerprint.as_deref() {
            clear_model_switch_compact_resume_r61(fingerprint, resolved_model.as_deref());
        }
    }

    // Only a main, non-helper turn can advance the authoritative session model.
'''
if resume_anchor not in source:
    raise SystemExit("r61: r46 forensics / r45 activation anchor missing")
source = source.replace(resume_anchor, resume_new, 1)

for invariant in (
    MARKER,
    "arm_current_model_fallback",
    "allow_current_model_compaction",
    "resume_main_turn",
    "previous_model_compact_fallback_response_r61",
    "r61_provider_gate_is_explicit_sub2api_responses_only",
    "if r45_compaction_helper && !r61_fallback_attempt",
):
    if invariant not in source:
        raise SystemExit(f"r61 generated-source invariant missing: {invariant}")

FORWARD.write_text(source, encoding="utf-8")
print("R61 MODEL-SWITCH COMPACT RESUME-ONCE PASS")
print("- CompHashChanged previous-model compact receives one local invalid_request_error")
print("- Codex current-model compact fallback is exempted from r45 stale-helper rebinding")
print("- state is conversation-fingerprint scoped, bounded, process-local and TTL limited")
print("- next normal main turn clears r61 state and lets r45 persist the selected model")
