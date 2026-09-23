//! 代理统计与日志缓冲。
//!
//! 这是 `v1.0.3:backend/proxy.py` 中 `ProxyStats`、`LogBuffer` 和全局
//! `stats` / `log_buffer` 的 Rust 等价转译。

use std::{
    collections::{BTreeMap, HashMap},
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex, OnceLock,
    },
};

use chrono::{DateTime, Local, SecondsFormat};
use codex_app_transfer_registry::config_dir;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ProxyStatsSnapshot {
    pub total: u64,
    pub success: u64,
    pub failed: u64,
    pub today: u64,
}

#[derive(Debug)]
struct ProxyStatsState {
    total: u64,
    success: u64,
    failed: u64,
    today: u64,
    date: String,
}

impl Default for ProxyStatsState {
    fn default() -> Self {
        Self {
            total: 0,
            success: 0,
            failed: 0,
            today: 0,
            date: Local::now().format("%Y-%m-%d").to_string(),
        }
    }
}

#[derive(Debug, Default)]
pub struct ProxyStats {
    inner: Mutex<ProxyStatsState>,
}

impl ProxyStats {
    pub fn record(&self, success: bool) {
        let today = Local::now().format("%Y-%m-%d").to_string();
        let mut inner = self.inner.lock().unwrap();
        inner.total += 1;
        if inner.date != today {
            inner.today = 0;
            inner.date = today;
        }
        inner.today += 1;
        if success {
            inner.success += 1;
        } else {
            inner.failed += 1;
        }
    }

    pub fn snapshot(&self) -> ProxyStatsSnapshot {
        let inner = self.inner.lock().unwrap();
        ProxyStatsSnapshot {
            total: inner.total,
            success: inner.success,
            failed: inner.failed,
            today: inner.today,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ProxyLogEntry {
    pub seq: u64,
    pub timestamp: String,
    pub time: String,
    pub level: String,
    pub message: String,
}

// CAS-R72-STRUCTURED-OBSERVABILITY
// Machine-readable local sidecar for forensic correlation. `fields` is built only
// from a strict allowlist of tokens that are already present in the human log line;
// arbitrary error text, URLs, prompt/body content and raw identity headers are never
// promoted into structured attributes.
#[derive(Debug, Serialize)]
struct StructuredLogRecord<'a> {
    seq: u64,
    timestamp: &'a str,
    level: &'a str,
    event: Option<&'a str>,
    message: &'a str,
    fields: BTreeMap<&'static str, String>,
}

// CAS-R71-OBSERVABILITY-CORRELATION
// Keep only bounded, already-fingerprinted runtime diagnostic state. Raw request
// headers and raw thread/session identifiers never enter this map.
#[derive(Debug, Default)]
struct DiagCorrelationState {
    model_by_main_thread: HashMap<String, String>,
}

#[derive(Debug)]
pub struct LogBuffer {
    logs: Mutex<Vec<ProxyLogEntry>>,
    max_size: usize,
    file_lock: Mutex<()>,
    log_dir_override: Option<PathBuf>,
    diag_state: Mutex<DiagCorrelationState>,
    next_seq: AtomicU64,
}

impl LogBuffer {
    pub fn new(max_size: usize) -> Self {
        Self {
            logs: Mutex::new(Vec::new()),
            max_size,
            file_lock: Mutex::new(()),
            log_dir_override: None,
            diag_state: Mutex::new(DiagCorrelationState::default()),
            next_seq: AtomicU64::new(1),
        }
    }

    #[cfg(test)]
    fn new_in_dir(max_size: usize, log_dir: PathBuf) -> Self {
        Self {
            logs: Mutex::new(Vec::new()),
            max_size,
            file_lock: Mutex::new(()),
            log_dir_override: Some(log_dir),
            diag_state: Mutex::new(DiagCorrelationState::default()),
            next_seq: AtomicU64::new(1),
        }
    }

    pub fn add(&self, level: impl Into<String>, message: impl Into<String>) {
        let now = Local::now();
        let level = level.into();
        let message = message.into();
        let (message, transition) = self.enrich_runtime_diag(message);

        self.push_entry(&now, &level, &message);
        if let Some(transition) = transition {
            self.push_entry(&now, "INFO", &transition);
        }
    }

    fn push_entry(&self, now: &DateTime<Local>, level: &str, message: &str) {
        let seq = self.next_seq.fetch_add(1, Ordering::Relaxed);
        let timestamp = now.to_rfc3339_opts(SecondsFormat::Millis, false);
        {
            let mut logs = self.logs.lock().unwrap();
            logs.push(ProxyLogEntry {
                seq,
                timestamp: timestamp.clone(),
                // Milliseconds are necessary to order concurrent main/subagent traffic.
                time: now.format("%H:%M:%S%.3f").to_string(),
                level: level.to_owned(),
                message: message.to_owned(),
            });
            if logs.len() > self.max_size {
                let keep_from = logs.len() - self.max_size;
                logs.drain(0..keep_from);
            }
        }
        self.append_to_files(now, seq, &timestamp, level, message);
    }

    // CAS-R71-OBSERVABILITY-CORRELATION
    // The r18 diagnostic line historically defaulted every non-subagent request to
    // `target=main`. Capability/helper requests without identity metadata therefore
    // looked like main assistant turns. Preserve normal main/subagent values, but
    // rewrite identity-less `target=main` to `target=unclassified` and append explicit
    // request_class + route_target fields based only on privacy-bounded fingerprints.
    fn enrich_runtime_diag(&self, message: String) -> (String, Option<String>) {
        if !message.starts_with("[retry-runtime-diag]") {
            return (message, None);
        }

        let target = diag_field(&message, "target").unwrap_or("-").to_owned();
        let model = diag_field(&message, "model")
            .unwrap_or("<unknown>")
            .to_owned();
        let thread = diag_field(&message, "thread").unwrap_or("-").to_owned();
        let parent = diag_field(&message, "parent").unwrap_or("-").to_owned();
        let session = diag_field(&message, "session").unwrap_or("-").to_owned();
        let client_request = diag_field(&message, "client_request")
            .unwrap_or("-")
            .to_owned();

        let (request_class, route_target) = if target == "subagent" || parent != "-" {
            ("subagent", "subagent")
        } else if thread != "-" || session != "-" {
            ("turn", "main")
        } else {
            // We intentionally do not call this `capability`: without the route/path
            // at this layer we cannot prove which helper produced it. The important
            // fix is that it is no longer asserted to be a main assistant turn.
            ("aux_or_unidentified", "-")
        };

        let trace = if thread != "-" {
            format!("thread-id:{thread}")
        } else if session != "-" {
            format!("session-id:{session}")
        } else {
            "uncorrelated".to_owned()
        };
        let client_req = if client_request != "-" {
            client_request.clone()
        } else {
            "unavailable".to_owned()
        };

        let message = if request_class == "aux_or_unidentified" && target == "main" {
            message.replacen("target=main", "target=unclassified", 1)
        } else {
            message
        };
        let enriched = format!(
            "{message} client_req={client_req} trace={trace} request_class={request_class} route_target={route_target}"
        );

        let transition = if request_class == "turn" && thread != "-" && model != "<unknown>" {
            let mut state = self.diag_state.lock().unwrap_or_else(|p| p.into_inner());
            if !state.model_by_main_thread.contains_key(&thread)
                && state.model_by_main_thread.len() >= 256
            {
                if let Some(oldest_key) = state.model_by_main_thread.keys().next().cloned() {
                    state.model_by_main_thread.remove(&oldest_key);
                }
            }
            let previous = state
                .model_by_main_thread
                .insert(thread.clone(), model.clone());
            previous.filter(|old| old != &model).map(|old| {
                format!(
                    "[model-transition] client_req={client_req} trace=thread-id:{thread} thread={thread} from={old} to={model} request_class=turn route_target=main"
                )
            })
        } else {
            None
        };

        (enriched, transition)
    }

    pub fn get_all(&self) -> Vec<ProxyLogEntry> {
        self.logs.lock().unwrap().clone()
    }

    pub fn clear(&self) {
        self.logs.lock().unwrap().clear();
        self.diag_state
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .model_by_main_thread
            .clear();
        self.archive_logs();
    }

    fn append_to_files(
        &self,
        now: &DateTime<Local>,
        seq: u64,
        timestamp: &str,
        level: &str,
        message: &str,
    ) {
        let Some(dir) = self.log_dir() else {
            return;
        };
        if fs::create_dir_all(&dir).is_err() {
            return;
        }

        // One lock covers both outputs so the human-readable TSV and JSONL sidecar
        // cannot be reordered relative to one another by concurrent requests.
        let _guard = self.file_lock.lock().unwrap();

        let human_path = dir.join(format!("proxy-{}.log", now.format("%Y-%m-%d")));
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(human_path) {
            let _ = writeln!(
                file,
                "{}\t{}\t{}",
                now.format("%Y-%m-%d %H:%M:%S%.3f"),
                level,
                message
            );
        }

        let structured_path = dir.join(format!(
            "proxy-events-{}.jsonl",
            now.format("%Y-%m-%d")
        ));
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(structured_path)
        {
            let record = StructuredLogRecord {
                seq,
                timestamp,
                level,
                event: structured_event_name(message),
                message,
                fields: structured_fields(message),
            };
            if serde_json::to_writer(&mut file, &record).is_ok() {
                let _ = file.write_all(b"\n");
            }
        }
    }

    fn archive_logs(&self) {
        let Some(dir) = self.log_dir() else {
            return;
        };
        if !dir.is_dir() {
            return;
        }
        let backup_dir = self.log_backup_dir();
        if fs::create_dir_all(&backup_dir).is_err() {
            return;
        }
        let tag = Local::now().format("%Y%m%d-%H%M%S").to_string();
        let _guard = self.file_lock.lock().unwrap();
        let Ok(entries) = fs::read_dir(&dir) else {
            return;
        };
        for entry in entries.flatten() {
            let src = entry.path();
            let Some(name) = src.file_name().and_then(|v| v.to_str()) else {
                continue;
            };
            if !src.is_file() {
                continue;
            }

            let (base, ext) = if name.starts_with("proxy-events-") && name.ends_with(".jsonl") {
                (name.trim_end_matches(".jsonl"), "jsonl")
            } else if name.starts_with("proxy-") && name.ends_with(".log") {
                (name.trim_end_matches(".log"), "log")
            } else {
                continue;
            };

            let mut dst = backup_dir.join(format!("{base}_{tag}.{ext}"));
            let mut counter = 1;
            while dst.exists() {
                dst = backup_dir.join(format!("{base}_{tag}_{counter}.{ext}"));
                counter += 1;
            }
            let _ = fs::rename(&src, dst);
        }
    }

    fn log_dir(&self) -> Option<PathBuf> {
        self.log_dir_override.clone().or_else(proxy_log_dir)
    }

    fn log_backup_dir(&self) -> PathBuf {
        self.log_dir()
            .unwrap_or_else(|| PathBuf::from(".codex-app-transfer").join("logs"))
            .join("backup")
    }
}

fn diag_field<'a>(message: &'a str, key: &str) -> Option<&'a str> {
    let prefix = format!("{key}=");
    message
        .split_ascii_whitespace()
        .find_map(|token| token.strip_prefix(&prefix))
}

fn structured_event_name(message: &str) -> Option<&str> {
    let rest = message.strip_prefix('[')?;
    let end = rest.find(']')?;
    let event = &rest[..end];
    (!event.is_empty()
        && event
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_')))
    .then_some(event)
}

fn structured_fields(message: &str) -> BTreeMap<&'static str, String> {
    const SAFE_FIELDS: [&str; 33] = [
        "req",
        "trace",
        "client_req",
        "target",
        "request_class",
        "route_target",
        "model",
        "model_effective",
        "provider",
        "thread",
        "parent",
        "session",
        "from",
        "to",
        "raw_upstream_status",
        "client_status",
        "status",
        "outcome",
        "request_bytes",
        "bytes",
        "subagent_header",
        "parent_thread_header",
        "client_request",
        "attempt",
        "max_retries",
        "delay_ms",
        "reason",
        "retries_used",
        "configured",
        "retry_id",
        "mode",
        "elapsed_ms",
        "max_duration_ms",
    ];

    let mut fields = BTreeMap::new();
    for &key in &SAFE_FIELDS {
        if let Some(value) = diag_field(message, key) {
            fields.insert(
                key,
                value
                    .trim_end_matches(|ch| ch == ',' || ch == ';')
                    .to_owned(),
            );
        }
    }
    fields
}

// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD
// Privacy-bounded request lifecycle telemetry. Records only stage timestamps,
// provider/model labels and fingerprinted correlation supplied by forward.rs.
// Prompt/response bodies, tool arguments, raw thread/session IDs and credentials
// never enter this store.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RequestLifecycleSnapshot {
    pub id: u64,
    pub correlation: String,
    pub provider: String,
    pub model: String,
    pub accepted_at_ms: i64,
    pub forwarded_at_ms: Option<i64>,
    pub headers_at_ms: Option<i64>,
    pub first_event_at_ms: Option<i64>,
    pub completed_at_ms: Option<i64>,
    // CAS-R35-REAL-UPSTREAM-HEALTH
    // `raw_upstream_status` is the final HTTP status returned by the actual
    // provider/gateway before adapter conversion. `client_status` is what
    // Codex receives after conversion (which may legitimately be 200 for a
    // response.failed SSE). Keeping both prevents 503 -> 200 diagnostic loss.
    pub raw_upstream_status: Option<u16>,
    pub client_status: Option<u16>,
    pub request_bytes: u64,
    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD
    // Quota metadata is copied only from standard x-codex response headers.
    // Account identity, when present, is already an irreversible 8-char fingerprint.
    pub quota_primary_used_percent: Option<f32>,
    pub quota_secondary_used_percent: Option<f32>,
    pub quota_primary_reset_after_seconds: Option<u64>,
    pub quota_secondary_reset_after_seconds: Option<u64>,
    pub quota_account_fingerprint: Option<String>,
    pub status: Option<u16>,
    pub bytes: u64,
    pub terminal: Option<String>,
}

#[derive(Debug)]
pub struct RequestLifecycleTracker {
    inner: Mutex<std::collections::VecDeque<RequestLifecycleSnapshot>>,
    next_id: std::sync::atomic::AtomicU64,
    max_size: usize,
}

impl Default for RequestLifecycleTracker {
    fn default() -> Self {
        Self {
            inner: Mutex::new(std::collections::VecDeque::new()),
            next_id: std::sync::atomic::AtomicU64::new(1),
            max_size: 256,
        }
    }
}

impl RequestLifecycleTracker {
    fn now_ms() -> i64 {
        Local::now().timestamp_millis()
    }

    pub fn start(
        &self,
        correlation: impl Into<String>,
        provider: impl Into<String>,
        model: impl Into<String>,
        request_bytes: u64,
    ) -> u64 {
        let id = self
            .next_id
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let correlation = correlation.into();
        let provider = provider.into();
        let model = model.into();
        let mut inner = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        while inner.len() >= self.max_size {
            inner.pop_front();
        }
        inner.push_back(RequestLifecycleSnapshot {
            id,
            correlation: correlation.clone(),
            provider: provider.clone(),
            model: model.clone(),
            accepted_at_ms: Self::now_ms(),
            forwarded_at_ms: None,
            headers_at_ms: None,
            first_event_at_ms: None,
            completed_at_ms: None,
            raw_upstream_status: None,
            client_status: None,
            request_bytes,
            quota_primary_used_percent: None,
            quota_secondary_used_percent: None,
            quota_primary_reset_after_seconds: None,
            quota_secondary_reset_after_seconds: None,
            quota_account_fingerprint: None,
            status: None,
            bytes: 0,
            terminal: None,
        });
        drop(inner);
        emit_lifecycle_event(
            self,
            "INFO",
            format!(
                "[request-start] req={} trace={} provider={} model_effective={} request_bytes={}",
                lifecycle_req_id(id),
                correlation,
                provider,
                model,
                request_bytes
            ),
        );
        id
    }

    fn update(
        &self,
        id: u64,
        f: impl FnOnce(&mut RequestLifecycleSnapshot),
    ) -> Option<RequestLifecycleSnapshot> {
        let mut inner = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        let record = inner.iter_mut().rev().find(|record| record.id == id)?;
        f(record);
        Some(record.clone())
    }

    pub fn mark_forwarded(&self, id: u64) {
        if let Some(record) = self.update(id, |record| {
            record.forwarded_at_ms.get_or_insert_with(Self::now_ms);
        }) {
            emit_lifecycle_event(
                self,
                "INFO",
                format!(
                    "[upstream-start] req={} trace={} provider={} model_effective={}",
                    lifecycle_req_id(id),
                    record.correlation,
                    record.provider,
                    record.model
                ),
            );
        }
    }

    pub fn mark_headers(&self, id: u64, status: u16) {
        self.update(id, |record| {
            record.headers_at_ms.get_or_insert_with(Self::now_ms);
            record.raw_upstream_status = Some(status);
        });
    }

    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD: update quota metadata without
    // storing raw response headers, cookies, account e-mails or bearer credentials.
    pub fn mark_quota(
        &self,
        id: u64,
        primary_used_percent: Option<f32>,
        secondary_used_percent: Option<f32>,
        primary_reset_after_seconds: Option<u64>,
        secondary_reset_after_seconds: Option<u64>,
        account_fingerprint: Option<String>,
    ) {
        self.update(id, |record| {
            if primary_used_percent.is_some() {
                record.quota_primary_used_percent = primary_used_percent;
            }
            if secondary_used_percent.is_some() {
                record.quota_secondary_used_percent = secondary_used_percent;
            }
            if primary_reset_after_seconds.is_some() {
                record.quota_primary_reset_after_seconds = primary_reset_after_seconds;
            }
            if secondary_reset_after_seconds.is_some() {
                record.quota_secondary_reset_after_seconds = secondary_reset_after_seconds;
            }
            if account_fingerprint.is_some() {
                record.quota_account_fingerprint = account_fingerprint;
            }
        });
    }

    pub fn mark_client_status(&self, id: u64, status: u16) {
        if let Some(record) = self.update(id, |record| {
            record.client_status = Some(status);
            // Keep legacy `status` as the client-facing value for old
            // diagnostic consumers; r35 health uses raw_upstream_status.
            record.status = Some(status);
        }) {
            emit_lifecycle_event(
                self,
                if status < 400 { "INFO" } else { "ERROR" },
                format!(
                    "[client-status] req={} trace={} raw_upstream_status={} client_status={status}",
                    lifecycle_req_id(id),
                    record.correlation,
                    record
                        .raw_upstream_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned())
                ),
            );
        }
    }

    pub fn mark_first_event(&self, id: u64) {
        self.update(id, |record| {
            record.first_event_at_ms.get_or_insert_with(Self::now_ms);
        });
    }

    pub fn mark_completed(&self, id: u64, status: u16, bytes: u64) {
        let mut changed = false;
        if let Some(record) = self.update(id, |record| {
            if record.terminal.is_none() {
                changed = true;
                record.completed_at_ms = Some(Self::now_ms());
                record.client_status = Some(status);
                record.status = Some(status);
                record.bytes = bytes;
                record.terminal = Some(
                    if record.raw_upstream_status.is_some_and(|raw| raw >= 400) {
                        "upstream_error"
                    } else {
                        "completed"
                    }
                    .to_owned(),
                );
            }
        }) {
            if !changed {
                return;
            }
            emit_lifecycle_event(
                self,
                if record.terminal.as_deref() == Some("completed") {
                    "INFO"
                } else {
                    "ERROR"
                },
                format!(
                    "[request-end] req={} trace={} outcome={} raw_upstream_status={} client_status={} bytes={}",
                    lifecycle_req_id(id),
                    record.correlation,
                    record.terminal.as_deref().unwrap_or("unknown"),
                    record
                        .raw_upstream_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned()),
                    record
                        .client_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned()),
                    record.bytes
                ),
            );
        }
    }

    pub fn mark_failed(&self, id: u64, stage: &'static str) {
        let mut changed = false;
        if let Some(record) = self.update(id, |record| {
            if record.terminal.is_none() {
                changed = true;
                record.completed_at_ms = Some(Self::now_ms());
                record.terminal = Some(format!("failed:{stage}"));
            }
        }) {
            if !changed {
                return;
            }
            emit_lifecycle_event(
                self,
                "ERROR",
                format!(
                    "[request-end] req={} trace={} outcome={} raw_upstream_status={} client_status={}",
                    lifecycle_req_id(id),
                    record.correlation,
                    record.terminal.as_deref().unwrap_or("failed"),
                    record
                        .raw_upstream_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned()),
                    record
                        .client_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned())
                ),
            );
        }
    }

    pub fn mark_cancelled(&self, id: u64) {
        let mut changed = false;
        if let Some(record) = self.update(id, |record| {
            if record.terminal.is_none() {
                changed = true;
                record.completed_at_ms = Some(Self::now_ms());
                record.terminal = Some("cancelled".to_owned());
            }
        }) {
            if !changed {
                return;
            }
            emit_lifecycle_event(
                self,
                "WARN",
                format!(
                    "[request-end] req={} trace={} outcome=cancelled raw_upstream_status={} client_status={}",
                    lifecycle_req_id(id),
                    record.correlation,
                    record
                        .raw_upstream_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned()),
                    record
                        .client_status
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "-".to_owned())
                ),
            );
        }
    }

    pub fn snapshot(&self) -> Vec<RequestLifecycleSnapshot> {
        self.inner
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .iter()
            .cloned()
            .collect()
    }
}

fn lifecycle_req_id(id: u64) -> String {
    format!("R{id:08}")
}

fn emit_lifecycle_event(tracker: &RequestLifecycleTracker, level: &str, message: String) {
    // Only the tracker owned by the process-global ProxyTelemetry emits UI/file logs.
    // Standalone trackers used by tests stay side-effect free.
    if let Some(telemetry) = TELEMETRY.get() {
        if std::ptr::eq(tracker, &telemetry.lifecycles) {
            telemetry.logs.add(level, message);
        }
    }
}

#[derive(Debug)]
pub struct ProxyTelemetry {
    pub stats: ProxyStats,
    pub logs: LogBuffer,
    pub lifecycles: RequestLifecycleTracker,
}

impl Default for ProxyTelemetry {
    fn default() -> Self {
        Self {
            stats: ProxyStats::default(),
            logs: LogBuffer::new(200),
            lifecycles: RequestLifecycleTracker::default(),
        }
    }
}

// [MOC-232] 上下文 by-source 明细的持久 store(dir / is_safe_conversation_id / persist /
// load / gc)已迁到 `adapters::responses::context_breakdown` —— 计算改 adapter 内
// spawn_blocking 后台跑,compute 与 persist 同处 adapters、数据流最短(proxy 不再触碰)。

static TELEMETRY: OnceLock<ProxyTelemetry> = OnceLock::new();

pub fn proxy_telemetry() -> &'static ProxyTelemetry {
    TELEMETRY.get_or_init(ProxyTelemetry::default)
}

pub fn proxy_log_dir() -> Option<PathBuf> {
    config_dir().map(|dir| dir.join("logs"))
}

#[cfg(test)]
mod tests {
    use super::*;

    // [MOC-232] uuid 校验测试随 store 一起迁到
    // `adapters::responses::context_breakdown`(is_safe_conversation_id_rejects_path_traversal_and_bad_shape)。

    fn unique_temp_dir(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("codex-app-transfer-{name}-{nanos}"))
    }

    #[test]
    fn stats_records_success_failed_and_today() {
        let stats = ProxyStats::default();

        stats.record(true);
        stats.record(false);

        let snapshot = stats.snapshot();
        assert_eq!(snapshot.total, 2);
        assert_eq!(snapshot.success, 1);
        assert_eq!(snapshot.failed, 1);
        assert_eq!(snapshot.today, 2);
    }

    #[test]
    fn log_buffer_keeps_recent_entries_and_writes_daily_files() {
        let dir = unique_temp_dir("logs-write");
        let buffer = LogBuffer::new_in_dir(2, dir.clone());

        buffer.add("INFO", "first request");
        buffer.add("ERROR", "failed request");
        buffer.add("SUCCESS", "finished request");

        let entries = buffer.get_all();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].level, "ERROR");
        assert_eq!(entries[0].message, "failed request");
        assert_eq!(entries[1].level, "SUCCESS");
        assert_eq!(entries[1].message, "finished request");
        assert_eq!(entries[0].seq + 1, entries[1].seq);
        assert_eq!(entries[1].time.len(), 12);
        assert_eq!(entries[1].time.as_bytes()[8], b'.');
        assert!(entries[1].timestamp.contains('T'));

        let today = Local::now().format("%Y-%m-%d").to_string();
        let log_path = dir.join(format!("proxy-{today}.log"));
        let content = fs::read_to_string(log_path).unwrap();
        assert!(content.contains("\tINFO\tfirst request"));
        assert!(content.contains("\tERROR\tfailed request"));
        assert!(content.contains("\tSUCCESS\tfinished request"));

        let jsonl_path = dir.join(format!("proxy-events-{today}.jsonl"));
        let lines: Vec<_> = fs::read_to_string(jsonl_path)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
            .collect();
        assert_eq!(lines.len(), 3);
        assert_eq!(lines[0]["seq"].as_u64(), Some(1));
        assert_eq!(lines[2]["seq"].as_u64(), Some(3));
        assert_eq!(lines[2]["message"].as_str(), Some("finished request"));

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn retry_runtime_diag_without_identity_is_not_asserted_as_main_turn() {
        let dir = unique_temp_dir("logs-r71-aux");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());
        buffer.add(
            "INFO",
            "[retry-runtime-diag] target=main model=gpt-5.6-luna provider=test thread=- parent=- session=- client_request=- subagent_header=false parent_thread_header=false",
        );

        let entries = buffer.get_all();
        assert_eq!(entries.len(), 1);
        assert!(entries[0].message.contains("target=unclassified"));
        assert!(!entries[0].message.contains("target=main"));
        assert!(entries[0]
            .message
            .contains("request_class=aux_or_unidentified"));
        assert!(entries[0].message.contains("route_target=-"));
        assert!(entries[0].message.contains("trace=uncorrelated"));
        assert!(entries[0].message.contains("client_req=unavailable"));

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn retry_runtime_diag_emits_model_transition_for_same_main_thread() {
        let dir = unique_temp_dir("logs-r71-transition");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());
        buffer.add(
            "INFO",
            "[retry-runtime-diag] target=main model=gpt-5.6-terra provider=test thread=0d0f19d1 parent=- session=0d0f19d1 client_request=aaaa1111 subagent_header=false parent_thread_header=false",
        );
        buffer.add(
            "INFO",
            "[retry-runtime-diag] target=main model=gpt-5.6-luna provider=test thread=0d0f19d1 parent=- session=0d0f19d1 client_request=bbbb2222 subagent_header=false parent_thread_header=false",
        );

        let entries = buffer.get_all();
        assert_eq!(entries.len(), 3);
        assert!(entries[0].message.contains("request_class=turn"));
        assert!(entries[0].message.contains("route_target=main"));
        assert!(entries[0].message.contains("trace=thread-id:0d0f19d1"));
        assert!(entries[1].message.contains("client_req=bbbb2222"));
        assert!(entries[2].message.starts_with("[model-transition]"));
        assert!(entries[2].message.contains("from=gpt-5.6-terra"));
        assert!(entries[2].message.contains("to=gpt-5.6-luna"));

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn retry_runtime_diag_subagent_keeps_subagent_classification() {
        let dir = unique_temp_dir("logs-r71-subagent");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());
        buffer.add(
            "INFO",
            "[retry-runtime-diag] target=subagent model=gpt-5.6-luna provider=test thread=658a2dca parent=0d0f19d1 session=0d0f19d1 client_request=cccc3333 subagent_header=true parent_thread_header=true",
        );

        let entries = buffer.get_all();
        assert_eq!(entries.len(), 1);
        assert!(entries[0].message.contains("request_class=subagent"));
        assert!(entries[0].message.contains("route_target=subagent"));
        assert!(!entries[0].message.contains("[model-transition]"));

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn structured_jsonl_extracts_only_safe_correlation_fields() {
        let dir = unique_temp_dir("logs-r72-structured");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());
        buffer.add(
            "INFO",
            "[retry-runtime-diag] target=main model=gpt-5.6-terra provider=test thread=0d0f19d1 parent=- session=0d0f19d1 client_request=aaaa1111 subagent_header=false parent_thread_header=false secret=must-not-promote",
        );

        let today = Local::now().format("%Y-%m-%d").to_string();
        let jsonl_path = dir.join(format!("proxy-events-{today}.jsonl"));
        let raw = fs::read_to_string(jsonl_path).unwrap();
        let value: serde_json::Value = serde_json::from_str(raw.trim()).unwrap();
        assert_eq!(value["event"].as_str(), Some("retry-runtime-diag"));
        assert_eq!(value["fields"]["model"].as_str(), Some("gpt-5.6-terra"));
        assert_eq!(value["fields"]["request_class"].as_str(), Some("turn"));
        assert_eq!(value["fields"]["route_target"].as_str(), Some("main"));
        assert!(value["fields"].get("secret").is_none());

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn log_buffer_clear_archives_human_and_structured_proxy_logs() {
        let dir = unique_temp_dir("logs-clear");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());

        buffer.add("INFO", "before clear");
        let today = Local::now().format("%Y-%m-%d").to_string();
        let log_path = dir.join(format!("proxy-{today}.log"));
        let jsonl_path = dir.join(format!("proxy-events-{today}.jsonl"));
        assert!(log_path.exists());
        assert!(jsonl_path.exists());

        buffer.clear();

        assert!(buffer.get_all().is_empty());
        assert!(!log_path.exists());
        assert!(!jsonl_path.exists());

        let backup_dir = dir.join("backup");
        let archived: Vec<PathBuf> = fs::read_dir(&backup_dir)
            .unwrap()
            .flatten()
            .map(|entry| entry.path())
            .collect();
        assert_eq!(archived.len(), 2);
        assert!(archived.iter().any(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with(&format!("proxy-{today}_")) && name.ends_with(".log"))
        }));
        assert!(archived.iter().any(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.starts_with(&format!("proxy-events-{today}_"))
                        && name.ends_with(".jsonl")
                })
        }));

        let _ = fs::remove_dir_all(dir);
    }
}
