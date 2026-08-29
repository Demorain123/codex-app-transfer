from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"

MARKER = "CAS-R45-MODEL-SWITCH-CONTINUITY"
TERMINAL_MARKER = "CAS-R45-RESPONSES-SEMANTIC-TERMINAL"

source = FORWARD.read_text(encoding="utf-8")
if MARKER in source and TERMINAL_MARKER in source:
    print("r45 model-switch/terminal rewrite already applied")
    raise SystemExit(0)

helper_anchor = "pub async fn forward_handler(\n"
if helper_anchor not in source:
    raise SystemExit("r45 rewrite: forward_handler anchor missing")

helpers = r'''
// CAS-R45-MODEL-SWITCH-CONTINUITY
//
// Cross-model sessions (for example Luna -> Grok) can issue an internal compaction
// request whose body still carries the old/default model. If that stale helper request
// is routed before correction, it may hit the wrong provider/model and poison the
// handoff. Keep a bounded, privacy-preserving (FNV64 conversation fingerprint only)
// effective-model map. Normal main-turn requests advance it; compaction helpers may
// consume it, but never overwrite it.
//
// Persistence is intentionally tiny and contains only fingerprint -> model. It lets a
// resumed thread retain the last effective model across Transfer restarts without
// storing prompt text, raw session/thread IDs, credentials, or tool arguments.
#[derive(Default)]
struct EffectiveModelStoreR45 {
    loaded: bool,
    models: std::collections::HashMap<String, String>,
}

static EFFECTIVE_MODELS_R45: std::sync::OnceLock<std::sync::Mutex<EffectiveModelStoreR45>> =
    std::sync::OnceLock::new();

fn effective_model_store_r45() -> &'static std::sync::Mutex<EffectiveModelStoreR45> {
    EFFECTIVE_MODELS_R45.get_or_init(|| std::sync::Mutex::new(EffectiveModelStoreR45::default()))
}

fn conversation_fingerprint_r45(headers: &HeaderMap) -> Option<String> {
    // Prefer rollout/session identity over per-request identity. These values never
    // leave this function raw; only a one-way local fingerprint is retained.
    let value = ["x-session-id", "session-id", "session_id", "thread-id"]
        .iter()
        .find_map(|name| headers.get(*name).and_then(|v| v.to_str().ok()))
        .map(str::trim)
        .filter(|v| !v.is_empty())?;
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in value.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    Some(format!("{hash:016x}"))
}

fn effective_model_path_r45() -> Option<std::path::PathBuf> {
    codex_app_transfer_registry::config_dir().map(|dir| dir.join("effective-models-r45.json"))
}

fn load_effective_models_r45(state: &mut EffectiveModelStoreR45) {
    if state.loaded {
        return;
    }
    state.loaded = true;
    let Some(path) = effective_model_path_r45() else {
        return;
    };
    let Ok(bytes) = std::fs::read(&path) else {
        return;
    };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        proxy_telemetry().logs.add(
            "WARN",
            "[model-switch-r45] persisted effective-model map is invalid JSON; ignoring it"
                .to_owned(),
        );
        return;
    };
    let Some(models) = value.get("models").and_then(|v| v.as_object()) else {
        return;
    };
    for (fingerprint, model) in models.iter().take(1024) {
        if fingerprint.len() != 16 || !fingerprint.bytes().all(|b| b.is_ascii_hexdigit()) {
            continue;
        }
        let Some(model) = model.as_str().map(str::trim).filter(|m| !m.is_empty()) else {
            continue;
        };
        state
            .models
            .insert(fingerprint.to_ascii_lowercase(), model.to_owned());
    }
}

fn persist_effective_models_r45(state: &EffectiveModelStoreR45) {
    let Some(path) = effective_model_path_r45() else {
        return;
    };
    let Some(parent) = path.parent() else {
        return;
    };
    if std::fs::create_dir_all(parent).is_err() {
        return;
    }
    let value = serde_json::json!({
        "version": 1,
        "models": state.models,
    });
    let Ok(bytes) = serde_json::to_vec_pretty(&value) else {
        return;
    };
    let tmp = path.with_extension(format!("json.tmp.{}", std::process::id()));
    if std::fs::write(&tmp, bytes).is_ok() {
        if let Err(error) = std::fs::rename(&tmp, &path) {
            let _ = std::fs::remove_file(&tmp);
            proxy_telemetry().logs.add(
                "WARN",
                format!("[model-switch-r45] failed to persist effective-model map: {error}"),
            );
        }
    }
}

fn effective_model_for_r45(fingerprint: &str) -> Option<String> {
    let mut state = effective_model_store_r45()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    load_effective_models_r45(&mut state);
    state.models.get(fingerprint).cloned()
}

fn activate_effective_model_r45(fingerprint: &str, model: &str) {
    let model = strip_internal_model_suffix(model.trim());
    if model.is_empty() {
        return;
    }
    let mut state = effective_model_store_r45()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    load_effective_models_r45(&mut state);
    let previous = state.models.get(fingerprint).cloned();
    if previous.as_deref().is_some_and(|v| v.eq_ignore_ascii_case(&model)) {
        return;
    }
    if state.models.len() >= 1024 && !state.models.contains_key(fingerprint) {
        if let Some(evict) = state.models.keys().next().cloned() {
            state.models.remove(&evict);
        }
    }
    state.models.insert(fingerprint.to_owned(), model.clone());
    persist_effective_models_r45(&state);
    proxy_telemetry().logs.add(
        "INFO",
        format!(
            "[model-switch-r45] action=activate session={} from={} to={}",
            &fingerprint[..8.min(fingerprint.len())],
            previous.as_deref().unwrap_or("<none>"),
            model,
        ),
    );
}

fn is_auxiliary_model_request_r45(headers: &HeaderMap) -> bool {
    headers.contains_key("x-openai-subagent")
        || headers.contains_key("x-codex-parent-thread-id")
        || headers.contains_key("x-openai-memgen-request")
}

fn value_has_compaction_marker_r45(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::String(s) => matches!(
            s.as_str(),
            "remote_compaction_v2" | "local_compaction_v2" | "compaction"
        ),
        serde_json::Value::Array(items) => items.iter().any(value_has_compaction_marker_r45),
        serde_json::Value::Object(map) => {
            if map
                .get("type")
                .and_then(|v| v.as_str())
                .is_some_and(|t| t == "compaction")
            {
                return true;
            }
            map.values().any(value_has_compaction_marker_r45)
        }
        _ => false,
    }
}

fn is_compaction_helper_request_r45(body: &[u8]) -> bool {
    serde_json::from_slice::<serde_json::Value>(body)
        .ok()
        .is_some_and(|value| value_has_compaction_marker_r45(&value))
}

fn model_equivalent_r45(left: &str, right: &str) -> bool {
    strip_internal_model_suffix(left.trim())
        .eq_ignore_ascii_case(&strip_internal_model_suffix(right.trim()))
}

// CAS-R45-RESPONSES-SEMANTIC-TERMINAL
//
// A Responses stream is semantically terminal when it emits response.completed,
// response.incomplete, or response.failed. The client is allowed to stop polling after
// that event, so transport EOF cannot be the sole source of truth for lifecycle health.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ResponseSemanticTerminalR45 {
    Completed,
    Incomplete,
    Failed,
}

#[derive(Default)]
struct ResponseTerminalDetectorR45 {
    buffer: Vec<u8>,
}

fn next_sse_frame_end_r45(buf: &[u8]) -> Option<usize> {
    let mut i = 0usize;
    while i < buf.len() {
        if i + 4 <= buf.len() && &buf[i..i + 4] == b"\r\n\r\n" {
            return Some(i + 4);
        }
        if i + 2 <= buf.len() && &buf[i..i + 2] == b"\n\n" {
            return Some(i + 2);
        }
        i += 1;
    }
    None
}

fn terminal_from_sse_frame_r45(frame: &[u8]) -> Option<ResponseSemanticTerminalR45> {
    let text = String::from_utf8_lossy(frame);
    let mut event_name: Option<&str> = None;
    let mut data = String::new();
    for raw in text.lines() {
        let line = raw.trim_end_matches('\r');
        if let Some(value) = line.strip_prefix("event:") {
            event_name = Some(value.trim());
        } else if let Some(value) = line.strip_prefix("data:") {
            if !data.is_empty() {
                data.push('\n');
            }
            data.push_str(value.trim_start());
        }
    }
    let classify = |kind: &str| match kind {
        "response.completed" => Some(ResponseSemanticTerminalR45::Completed),
        "response.incomplete" => Some(ResponseSemanticTerminalR45::Incomplete),
        "response.failed" => Some(ResponseSemanticTerminalR45::Failed),
        _ => None,
    };
    if let Some(terminal) = event_name.and_then(classify) {
        return Some(terminal);
    }
    if data.trim() == "[DONE]" || data.trim().is_empty() {
        return None;
    }
    serde_json::from_str::<serde_json::Value>(&data)
        .ok()
        .and_then(|value| value.get("type").and_then(|v| v.as_str()).and_then(classify))
}

impl ResponseTerminalDetectorR45 {
    fn push(&mut self, chunk: &[u8]) -> Option<ResponseSemanticTerminalR45> {
        const MAX_BUFFER: usize = 64 * 1024;
        if self.buffer.len().saturating_add(chunk.len()) > MAX_BUFFER {
            // Keep the newest half. A valid terminal frame is tiny; this protects
            // diagnostics from an unbounded malformed SSE frame without affecting wire bytes.
            let keep = self.buffer.len().min(MAX_BUFFER / 2);
            if keep > 0 {
                let from = self.buffer.len() - keep;
                self.buffer.drain(..from);
            }
        }
        if chunk.len() >= MAX_BUFFER {
            self.buffer.clear();
            self.buffer
                .extend_from_slice(&chunk[chunk.len() - MAX_BUFFER..]);
        } else {
            self.buffer.extend_from_slice(chunk);
        }

        while let Some(end) = next_sse_frame_end_r45(&self.buffer) {
            let frame: Vec<u8> = self.buffer.drain(..end).collect();
            if let Some(terminal) = terminal_from_sse_frame_r45(&frame) {
                return Some(terminal);
            }
        }
        None
    }
}

'''
source = source.replace(helper_anchor, helpers + helper_anchor, 1)

resolver_old = '''    let original_model = body_model(&body_bytes);
    let resolved = match state.resolver.resolve(&parts, &body_bytes) {
'''
resolver_new = '''    // Preserve the raw model for diagnostics, then repair only a structurally
    // confirmed compaction helper. Ordinary turns are never rewritten from the registry:
    // a user's explicit Luna <-> Grok switch must remain authoritative.
    let original_model = body_model(&body_bytes);
    let r45_compaction_helper = is_compaction_helper_request_r45(&body_bytes);
    let r45_conversation_fingerprint = conversation_fingerprint_r45(&parts.headers);
    if r45_compaction_helper {
        if let (Some(fingerprint), Some(incoming_model)) = (
            r45_conversation_fingerprint.as_deref(),
            original_model.as_deref(),
        ) {
            if let Some(current_model) = effective_model_for_r45(fingerprint) {
                if !model_equivalent_r45(incoming_model, &current_model) {
                    if let Some(rewritten) = rewrite_model_field(&body_bytes, &current_model) {
                        proxy_telemetry().logs.add(
                            "WARN",
                            format!(
                                "[model-switch-r45] action=rebind_compaction_model session={} from={} to={} reason=stale_helper_model",
                                &fingerprint[..8.min(fingerprint.len())],
                                incoming_model,
                                current_model,
                            ),
                        );
                        body_bytes = rewritten;
                    }
                }
            }
        }
    }

    let resolved = match state.resolver.resolve(&parts, &body_bytes) {
'''
if resolver_old not in source:
    raise SystemExit("r45 rewrite: resolver/original_model anchor missing")
source = source.replace(resolver_old, resolver_new, 1)

resolved_anchor = '''    let resolved_model = body_model(&body_bytes);

    // 4. 走 adapter 拿到上游路径 + 改写后的 body。Codex 的本地
'''
resolved_new = '''    let resolved_model = body_model(&body_bytes);

    // Only a main, non-helper turn can advance the authoritative session model.
    // This prevents compaction/subagent/memory helpers from switching the registry
    // back to a global default such as Luna after the user selected Grok.
    if !r45_compaction_helper && !is_auxiliary_model_request_r45(&parts.headers) {
        if let (Some(fingerprint), Some(model)) = (
            r45_conversation_fingerprint.as_deref(),
            resolved_model.as_deref(),
        ) {
            activate_effective_model_r45(fingerprint, model);
        }
    }

    // 4. 走 adapter 拿到上游路径 + 改写后的 body。Codex 的本地
'''
if resolved_anchor not in source:
    raise SystemExit("r45 rewrite: resolved_model anchor missing")
source = source.replace(resolved_anchor, resolved_new, 1)

record_old = '''    record_session_upstream_model(&parts.headers, resolved_model.as_deref());
'''
record_new = '''    if !r45_compaction_helper && !is_auxiliary_model_request_r45(&parts.headers) {
        record_session_upstream_model(&parts.headers, resolved_model.as_deref());
    }
'''
if record_old not in source:
    raise SystemExit("r45 rewrite: session-model recorder anchor missing")
source = source.replace(record_old, record_new, 1)

ct_old = '''    let codex_ct = response_plan
        .headers
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .map(str::to_owned);
'''
ct_new = ct_old + '''    let expects_response_terminal_r45 = is_local_responses_route(&client_path)
        && codex_ct
            .as_deref()
            .is_some_and(|value| value.to_ascii_lowercase().contains("text/event-stream"));
'''
if ct_old not in source:
    raise SystemExit("r45 rewrite: codex content-type anchor missing")
source = source.replace(ct_old, ct_new, 1)

call_old = '''        RequestLifecycleStreamR34::new(codex_stream, lifecycle_id, codex_status),
'''
call_new = '''        RequestLifecycleStreamR34::new(
            codex_stream,
            lifecycle_id,
            codex_status,
            expects_response_terminal_r45,
        ),
'''
if call_old not in source:
    raise SystemExit("r45 rewrite: lifecycle constructor call anchor missing")
source = source.replace(call_old, call_new, 1)

stream_start = source.find("// CAS-R34-RUNTIME-BEHAVIOR-HEALTH-STREAM\n// Wrap the final proxy→Codex stream")
stream_end = source.find("/// [MOC-194] tee **proxy→Codex 转换后响应**", stream_start)
if stream_start < 0 or stream_end < 0:
    raise SystemExit("r45 rewrite: lifecycle stream block anchors missing")

new_stream = r'''// CAS-R34-RUNTIME-BEHAVIOR-HEALTH-STREAM
// CAS-R45-RESPONSES-SEMANTIC-TERMINAL
// Wrap the final proxy→Codex stream. r45 additionally treats Responses SSE terminal
// events as authoritative, so a client Drop after response.completed is not mislabeled
// as cancelled merely because transport EOF was never polled.
struct RequestLifecycleStreamR34 {
    inner: codex_app_transfer_adapters::ByteStream,
    id: u64,
    status: u16,
    bytes: u64,
    first_event: bool,
    finished: bool,
    expects_response_terminal: bool,
    terminal_recorded: bool,
    terminal_detector: ResponseTerminalDetectorR45,
}

impl RequestLifecycleStreamR34 {
    fn new(
        inner: codex_app_transfer_adapters::ByteStream,
        id: u64,
        status: u16,
        expects_response_terminal: bool,
    ) -> Self {
        Self {
            inner,
            id,
            status,
            bytes: 0,
            first_event: false,
            finished: false,
            expects_response_terminal,
            terminal_recorded: false,
            terminal_detector: ResponseTerminalDetectorR45::default(),
        }
    }

    fn record_terminal(&mut self, terminal: ResponseSemanticTerminalR45) {
        if self.terminal_recorded {
            return;
        }
        self.terminal_recorded = true;
        match terminal {
            ResponseSemanticTerminalR45::Completed => proxy_telemetry()
                .lifecycles
                .mark_completed(self.id, self.status, self.bytes),
            ResponseSemanticTerminalR45::Incomplete => proxy_telemetry()
                .lifecycles
                .mark_failed(self.id, "response_incomplete"),
            ResponseSemanticTerminalR45::Failed => proxy_telemetry()
                .lifecycles
                .mark_failed(self.id, "response_failed"),
        }
    }
}

impl Stream for RequestLifecycleStreamR34 {
    type Item = Result<Bytes, std::io::Error>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        let this = self.as_mut().get_mut();
        match this.inner.as_mut().poll_next(cx) {
            Poll::Ready(Some(Ok(chunk))) => {
                if !this.first_event && !chunk.is_empty() {
                    this.first_event = true;
                    proxy_telemetry().lifecycles.mark_first_event(this.id);
                }
                this.bytes = this.bytes.saturating_add(chunk.len() as u64);
                if this.expects_response_terminal && !this.terminal_recorded {
                    if let Some(terminal) = this.terminal_detector.push(&chunk) {
                        this.record_terminal(terminal);
                    }
                }
                Poll::Ready(Some(Ok(chunk)))
            }
            Poll::Ready(Some(Err(error))) => {
                this.finished = true;
                if !this.terminal_recorded {
                    proxy_telemetry()
                        .lifecycles
                        .mark_failed(this.id, "response_stream");
                }
                Poll::Ready(Some(Err(error)))
            }
            Poll::Ready(None) => {
                this.finished = true;
                if !this.terminal_recorded {
                    if this.expects_response_terminal {
                        // HTTP/SSE EOF without a semantic terminal is a truncated Responses
                        // stream, not a successful completion.
                        proxy_telemetry()
                            .lifecycles
                            .mark_failed(this.id, "response_eof_without_terminal");
                    } else {
                        proxy_telemetry()
                            .lifecycles
                            .mark_completed(this.id, this.status, this.bytes);
                    }
                }
                Poll::Ready(None)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

impl Drop for RequestLifecycleStreamR34 {
    fn drop(&mut self) {
        if !self.finished && !self.terminal_recorded {
            proxy_telemetry().lifecycles.mark_cancelled(self.id);
        }
    }
}

'''
source = source[:stream_start] + new_stream + source[stream_end:]

test_anchor = '''    #[test]
    fn hop_headers_recognized() {
'''
tests = r'''    #[test]
    fn r45_compaction_helper_detection_is_structural() {
        assert!(is_compaction_helper_request_r45(
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction","encrypted_content":"x"}]}"#
        ));
        assert!(is_compaction_helper_request_r45(
            br#"{"model":"gpt-5.6-luna","metadata":{"feature":"remote_compaction_v2"}}"#
        ));
        assert!(!is_compaction_helper_request_r45(
            br#"{"model":"grok-4.6","input":[{"role":"user","content":"please discuss compaction and summaries"}]}"#
        ));
    }

    #[test]
    fn r45_semantic_terminal_detector_handles_chunk_boundaries() {
        let mut detector = ResponseTerminalDetectorR45::default();
        assert_eq!(
            detector.push(b"event: response.compl"),
            None,
            "partial event must not terminate"
        );
        assert_eq!(
            detector.push(b"eted\ndata: {\"type\":\"response.completed\",\"response\":{}}\n\n"),
            Some(ResponseSemanticTerminalR45::Completed)
        );

        let mut detector = ResponseTerminalDetectorR45::default();
        assert_eq!(
            detector.push(b"data: {\"type\":\"response.incomplete\"}\r\n\r\n"),
            Some(ResponseSemanticTerminalR45::Incomplete)
        );

        let mut detector = ResponseTerminalDetectorR45::default();
        assert_eq!(
            detector.push(b"data: {\"type\":\"response.failed\"}\n\n"),
            Some(ResponseSemanticTerminalR45::Failed)
        );

        let mut detector = ResponseTerminalDetectorR45::default();
        assert_eq!(detector.push(b"data: [DONE]\n\n"), None);
    }

    #[test]
    fn r45_auxiliary_requests_do_not_advance_main_model() {
        let mut headers = HeaderMap::new();
        headers.insert("x-openai-subagent", "worker".parse().unwrap());
        assert!(is_auxiliary_model_request_r45(&headers));
        headers.remove("x-openai-subagent");
        headers.insert(
            "x-openai-memgen-request",
            "1".parse().unwrap(),
        );
        assert!(is_auxiliary_model_request_r45(&headers));
        assert!(!is_auxiliary_model_request_r45(&HeaderMap::new()));
    }

'''
if test_anchor not in source:
    raise SystemExit("r45 rewrite: Rust tests anchor missing")
source = source.replace(test_anchor, tests + test_anchor, 1)

for invariant in (
    "CAS-R45-MODEL-SWITCH-CONTINUITY",
    "rebind_compaction_model",
    "effective-models-r45.json",
    "CAS-R45-RESPONSES-SEMANTIC-TERMINAL",
    "response_eof_without_terminal",
    "r45_compaction_helper_detection_is_structural",
    "r45_semantic_terminal_detector_handles_chunk_boundaries",
):
    if invariant not in source:
        raise SystemExit(f"r45 rewrite generated-source invariant missing: {invariant}")

FORWARD.write_text(source, encoding="utf-8")
print("R45 MODEL-SWITCH CONTINUITY + RESPONSES TERMINAL REWRITE PASS")
