from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R46-MODEL-SWITCH-FORENSICS-V2"

source = FORWARD.read_text(encoding="utf-8")
if MARKER in source:
    print("r46 model-switch forensics v2 already applied")
    raise SystemExit(0)

helper_anchor = "pub async fn forward_handler(\n"
if helper_anchor not in source:
    raise SystemExit("r46 forensics v2: forward_handler anchor missing")

helpers = r'''
// CAS-R46-MODEL-SWITCH-FORENSICS-V2
// Privacy-bounded structural diagnostics for long cross-model threads. Never records
// prompt/response text, tool arguments, raw thread/session ids, credentials, encrypted
// reasoning/compaction contents, or attachments.
#[derive(Clone, Debug, Default)]
struct RequestForensicsR46 {
    session: String,
    request_kind: String,
    compaction_trigger: String,
    compaction_reason: String,
    requested_model: String,
    resolved_model: String,
    effective_before: String,
    model_switch: bool,
    helper_rebound: bool,
    cross_model_compaction_mismatch: bool,
    request_bytes: usize,
    body_fingerprint: String,
    input_items: usize,
    message_items: usize,
    reasoning_items: usize,
    compaction_items: usize,
    toolish_items: usize,
    unknown_items: usize,
    tools_declared: usize,
    previous_response_id: bool,
    instructions_bytes: usize,
    input_types: String,
}

fn turn_metadata_r46(headers: &HeaderMap) -> Option<serde_json::Value> {
    let raw = headers.get("x-codex-turn-metadata")?.to_str().ok()?;
    serde_json::from_str(raw).ok()
}

fn fingerprint_bytes_r46(bytes: &[u8]) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{hash:016x}")
}

fn input_type_counts_r46(
    value: &serde_json::Value,
) -> (usize, usize, usize, usize, usize, usize, String) {
    let Some(items) = value.get("input").and_then(serde_json::Value::as_array) else {
        return (0, 0, 0, 0, 0, 0, "-".to_owned());
    };
    let mut message = 0usize;
    let mut reasoning = 0usize;
    let mut compaction = 0usize;
    let mut toolish = 0usize;
    let mut unknown = 0usize;
    let mut types = std::collections::BTreeMap::<String, usize>::new();
    for item in items {
        let kind = item
            .get("type")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("<none>");
        *types.entry(kind.to_owned()).or_default() += 1;
        match kind {
            "message" => message += 1,
            "reasoning" => reasoning += 1,
            "compaction" => compaction += 1,
            other if other.contains("call") || other.contains("tool") => toolish += 1,
            _ => unknown += 1,
        }
    }
    let summary = types
        .into_iter()
        .map(|(kind, count)| format!("{kind}:{count}"))
        .collect::<Vec<_>>()
        .join(",");
    (
        items.len(),
        message,
        reasoning,
        compaction,
        toolish,
        unknown,
        if summary.is_empty() { "-".into() } else { summary },
    )
}

fn analyze_request_forensics_r46(
    headers: &HeaderMap,
    body: &[u8],
    requested_model: Option<&str>,
    resolved_model: Option<&str>,
    effective_before: Option<&str>,
    compaction_helper: bool,
) -> RequestForensicsR46 {
    let metadata = turn_metadata_r46(headers);
    let request_kind = metadata
        .as_ref()
        .and_then(|value| value.get("request_kind"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or(if compaction_helper { "compaction" } else { "turn" })
        .to_owned();
    let compaction_trigger = metadata
        .as_ref()
        .and_then(|value| value.get("compaction"))
        .and_then(|value| value.get("trigger"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or("-")
        .to_owned();
    let compaction_reason = metadata
        .as_ref()
        .and_then(|value| value.get("compaction"))
        .and_then(|value| value.get("reason"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or("-")
        .to_owned();
    let requested_model = requested_model.unwrap_or("<unknown>").to_owned();
    let resolved_model = resolved_model.unwrap_or("<unknown>").to_owned();
    let effective_before = effective_before.unwrap_or("<none>").to_owned();
    let same_effective = effective_before == "<none>"
        || model_equivalent_r45(&effective_before, &resolved_model);
    let model_switch = !compaction_helper && !same_effective;
    let helper_rebound = compaction_helper
        && requested_model != "<unknown>"
        && resolved_model != "<unknown>"
        && !model_equivalent_r45(&requested_model, &resolved_model);
    let cross_model_compaction_mismatch = compaction_helper
        && effective_before != "<none>"
        && requested_model != "<unknown>"
        && !model_equivalent_r45(&effective_before, &requested_model);

    let parsed = serde_json::from_slice::<serde_json::Value>(body).ok();
    let (
        input_items,
        message_items,
        reasoning_items,
        compaction_items,
        toolish_items,
        unknown_items,
        input_types,
    ) = parsed
        .as_ref()
        .map(input_type_counts_r46)
        .unwrap_or((0, 0, 0, 0, 0, 0, "<invalid-json>".to_owned()));
    let tools_declared = parsed
        .as_ref()
        .and_then(|value| value.get("tools"))
        .and_then(serde_json::Value::as_array)
        .map(Vec::len)
        .unwrap_or(0);
    let previous_response_id = parsed
        .as_ref()
        .and_then(|value| value.get("previous_response_id"))
        .is_some_and(|value| !value.is_null());
    let instructions_bytes = parsed
        .as_ref()
        .and_then(|value| value.get("instructions"))
        .and_then(serde_json::Value::as_str)
        .map(str::len)
        .unwrap_or(0);
    let session = conversation_fingerprint_r45(headers)
        .map(|value| value[..8.min(value.len())].to_owned())
        .unwrap_or_else(|| "-".into());

    RequestForensicsR46 {
        session,
        request_kind,
        compaction_trigger,
        compaction_reason,
        requested_model,
        resolved_model,
        effective_before,
        model_switch,
        helper_rebound,
        cross_model_compaction_mismatch,
        request_bytes: body.len(),
        body_fingerprint: fingerprint_bytes_r46(body),
        input_items,
        message_items,
        reasoning_items,
        compaction_items,
        toolish_items,
        unknown_items,
        tools_declared,
        previous_response_id,
        instructions_bytes,
        input_types,
    }
}

fn log_request_forensics_r46(ctx: &RequestForensicsR46) {
    if ctx.request_bytes < 1024 * 1024
        && !ctx.model_switch
        && ctx.request_kind != "compaction"
        && !ctx.helper_rebound
        && !ctx.cross_model_compaction_mismatch
    {
        return;
    }
    let event = if ctx.cross_model_compaction_mismatch {
        "cross_model_compaction_mismatch"
    } else if ctx.helper_rebound {
        "compaction_model_rebound"
    } else if ctx.model_switch {
        "model_switch"
    } else if ctx.request_kind == "compaction" {
        "compaction"
    } else {
        "large_history"
    };
    proxy_telemetry().logs.add(
        if ctx.cross_model_compaction_mismatch { "WARN" } else { "INFO" },
        format!(
            "[model-switch-forensics-r46] event={} session={} kind={} requested_model={} resolved_model={} effective_before={} model_switch={} helper_rebound={} cross_model_compaction_mismatch={} compaction_trigger={} compaction_reason={} request_bytes={} body_fp={} input_items={} message_items={} reasoning_items={} compaction_items={} toolish_items={} unknown_items={} tools_declared={} previous_response_id={} instructions_bytes={} input_types=[{}]",
            event,
            ctx.session,
            ctx.request_kind,
            ctx.requested_model,
            ctx.resolved_model,
            ctx.effective_before,
            ctx.model_switch,
            ctx.helper_rebound,
            ctx.cross_model_compaction_mismatch,
            ctx.compaction_trigger,
            ctx.compaction_reason,
            ctx.request_bytes,
            ctx.body_fingerprint,
            ctx.input_items,
            ctx.message_items,
            ctx.reasoning_items,
            ctx.compaction_items,
            ctx.toolish_items,
            ctx.unknown_items,
            ctx.tools_declared,
            ctx.previous_response_id,
            ctx.instructions_bytes,
            ctx.input_types,
        ),
    );
}

fn log_result_forensics_r46(ctx: &RequestForensicsR46, raw_status: u16, client_status: u16) {
    if raw_status < 400 && raw_status == client_status {
        return;
    }
    let raw_client_mismatch = raw_status != client_status;
    let failed_compaction_preserves_history = ctx.request_kind == "compaction" && raw_status >= 400;
    let repeated_giant_history_risk = raw_status >= 400 && ctx.request_bytes >= 8 * 1024 * 1024;
    proxy_telemetry().logs.add(
        "WARN",
        format!(
            "[model-switch-forensics-r46] event=result session={} kind={} model={} raw_status={} client_status={} raw_client_mismatch={} failed_compaction_preserves_history={} repeated_giant_history_risk={} request_bytes={} body_fp={} input_types=[{}]",
            ctx.session,
            ctx.request_kind,
            ctx.resolved_model,
            raw_status,
            client_status,
            raw_client_mismatch,
            failed_compaction_preserves_history,
            repeated_giant_history_risk,
            ctx.request_bytes,
            ctx.body_fingerprint,
            ctx.input_types,
        ),
    );
    if raw_client_mismatch && raw_status >= 400 && client_status < 400 {
        proxy_telemetry().logs.add(
            "WARN",
            format!(
                "[model-switch-forensics-r46] event=raw_client_status_mismatch session={} raw={} client={} note=client_may_render_success_despite_upstream_failure",
                ctx.session, raw_status, client_status
            ),
        );
    }
}

'''
source = source.replace(helper_anchor, helpers + helper_anchor, 1)

# r45's CURRENT final tree (after apply_r45_compaction_metadata_truth.py) already
# classifies compaction with (headers, body). Capture effective-model state before r45
# mutates it, but keep r45's authoritative classifier itself.
old_ctx = '''    let r45_compaction_helper = is_compaction_helper_request_r45(&parts.headers, &body_bytes);
    let r45_conversation_fingerprint = conversation_fingerprint_r45(&parts.headers);
'''
new_ctx = '''    let r45_conversation_fingerprint = conversation_fingerprint_r45(&parts.headers);
    let r46_effective_before = r45_conversation_fingerprint
        .as_deref()
        .and_then(effective_model_for_r45);
    let r45_compaction_helper =
        is_compaction_helper_request_r45(&parts.headers, &body_bytes);
'''
if old_ctx not in source:
    raise SystemExit("r46 forensics v2: current r45 metadata-truth anchor missing")
source = source.replace(old_ctx, new_ctx, 1)

resolved_anchor = '''    let resolved_model = body_model(&body_bytes);

    // Only a main, non-helper turn can advance the authoritative session model.
'''
resolved_new = '''    let resolved_model = body_model(&body_bytes);
    let r46_forensics = analyze_request_forensics_r46(
        &parts.headers,
        &body_bytes,
        original_model.as_deref(),
        resolved_model.as_deref(),
        r46_effective_before.as_deref(),
        r45_compaction_helper,
    );
    log_request_forensics_r46(&r46_forensics);

    // Only a main, non-helper turn can advance the authoritative session model.
'''
if resolved_anchor not in source:
    raise SystemExit("r46 forensics v2: resolved model anchor missing")
source = source.replace(resolved_anchor, resolved_new, 1)

result_anchor = '''    telemetry.logs.add(
        if success { "INFO" } else { "ERROR" },
        format!("client response status {}", response_plan.status.as_u16()),
    );
'''
result_new = result_anchor + '''    log_result_forensics_r46(
        &r46_forensics,
        status.as_u16(),
        response_plan.status.as_u16(),
    );
'''
if result_anchor not in source:
    raise SystemExit("r46 forensics v2: client status anchor missing")
source = source.replace(result_anchor, result_new, 1)

test_anchor = '''    #[test]
    fn r45_compaction_helper_detection_is_structural() {
'''
tests = r'''    #[test]
    fn r46_metadata_truth_keeps_feature_flag_out_of_request_role() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"turn"}"#.parse().unwrap(),
        );
        headers.insert(
            "x-codex-beta-features",
            "remote_compaction_v2".parse().unwrap(),
        );
        assert!(!is_compaction_helper_request_r45(
            &headers,
            br#"{"model":"gpt-5.6-terra","input":[]}"#,
        ));
        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"compaction","compaction":{"trigger":"manual"}}"#
                .parse()
                .unwrap(),
        );
        assert!(is_compaction_helper_request_r45(
            &headers,
            br#"{"model":"gpt-5.6-terra","input":[]}"#,
        ));
    }

    #[test]
    fn r46_shape_counts_never_copy_message_content() {
        let value = serde_json::json!({
            "input": [
                {"type":"message","content":"SUPER_SECRET_CANARY"},
                {"type":"reasoning","encrypted_content":"SECRET_REASONING"},
                {"type":"compaction","encrypted_content":"SECRET_COMPACT"},
                {"type":"function_call","arguments":"SECRET_ARGS"}
            ],
            "tools": [{"type":"function","name":"x"}],
            "previous_response_id": "resp_123",
            "instructions": "hidden instructions"
        });
        let (_, messages, reasoning, compact, toolish, _, types) = input_type_counts_r46(&value);
        assert_eq!((messages, reasoning, compact, toolish), (1, 1, 1, 1));
        assert!(types.contains("message:1"));
        assert!(!types.contains("SUPER_SECRET_CANARY"));
        assert!(!types.contains("SECRET_REASONING"));
        assert!(!types.contains("SECRET_ARGS"));
    }

    #[test]
    fn r46_body_fingerprint_is_stable_without_echoing_body() {
        let body = b"sensitive payload";
        let fp1 = fingerprint_bytes_r46(body);
        let fp2 = fingerprint_bytes_r46(body);
        assert_eq!(fp1, fp2);
        assert_eq!(fp1.len(), 16);
        assert!(!fp1.contains("sensitive"));
    }

'''
if test_anchor not in source:
    raise SystemExit("r46 forensics v2: focused test anchor missing")
source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    "CAS-R46-MODEL-SWITCH-FORENSICS-V2",
    "event=raw_client_status_mismatch",
    "cross_model_compaction_mismatch",
    "input_types=[{}]",
    "r46_metadata_truth_keeps_feature_flag_out_of_request_role",
):
    if invariant not in source:
        raise SystemExit(f"r46 forensics v2 invariant missing: {invariant}")

FORWARD.write_text(source, encoding="utf-8")
print("R46 MODEL-SWITCH FORENSICS V2 PASS")
