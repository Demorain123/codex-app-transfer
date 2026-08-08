//! 代理统计与日志缓冲。
//!
//! 这是 `v1.0.3:backend/proxy.py` 中 `ProxyStats`、`LogBuffer` 和全局
//! `stats` / `log_buffer` 的 Rust 等价转译。

use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
    sync::{Mutex, OnceLock},
};

use chrono::{DateTime, Local};
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
    pub time: String,
    pub level: String,
    pub message: String,
}

#[derive(Debug)]
pub struct LogBuffer {
    logs: Mutex<Vec<ProxyLogEntry>>,
    max_size: usize,
    file_lock: Mutex<()>,
    log_dir_override: Option<PathBuf>,
}

impl LogBuffer {
    pub fn new(max_size: usize) -> Self {
        Self {
            logs: Mutex::new(Vec::new()),
            max_size,
            file_lock: Mutex::new(()),
            log_dir_override: None,
        }
    }

    #[cfg(test)]
    fn new_in_dir(max_size: usize, log_dir: PathBuf) -> Self {
        Self {
            logs: Mutex::new(Vec::new()),
            max_size,
            file_lock: Mutex::new(()),
            log_dir_override: Some(log_dir),
        }
    }

    pub fn add(&self, level: impl Into<String>, message: impl Into<String>) {
        let now = Local::now();
        let level = level.into();
        let message = message.into();
        {
            let mut logs = self.logs.lock().unwrap();
            logs.push(ProxyLogEntry {
                time: now.format("%H:%M:%S").to_string(),
                level: level.clone(),
                message: message.clone(),
            });
            if logs.len() > self.max_size {
                let keep_from = logs.len() - self.max_size;
                logs.drain(0..keep_from);
            }
        }
        self.append_to_file(now, &level, &message);
    }

    pub fn get_all(&self) -> Vec<ProxyLogEntry> {
        self.logs.lock().unwrap().clone()
    }

    pub fn clear(&self) {
        self.logs.lock().unwrap().clear();
        self.archive_logs();
    }

    fn append_to_file(&self, now: DateTime<Local>, level: &str, message: &str) {
        let Some(dir) = self.log_dir() else {
            return;
        };
        if fs::create_dir_all(&dir).is_err() {
            return;
        }
        let path = dir.join(format!("proxy-{}.log", now.format("%Y-%m-%d")));
        let _guard = self.file_lock.lock().unwrap();
        let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
            return;
        };
        let _ = writeln!(
            file,
            "{}\t{}\t{}",
            now.format("%Y-%m-%d %H:%M:%S"),
            level,
            message
        );
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
            if !name.starts_with("proxy-") || !name.ends_with(".log") || !src.is_file() {
                continue;
            }
            let base = name.trim_end_matches(".log");
            let mut dst = backup_dir.join(format!("{base}_{tag}.log"));
            let mut counter = 1;
            while dst.exists() {
                dst = backup_dir.join(format!("{base}_{tag}_{counter}.log"));
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
        let mut inner = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        while inner.len() >= self.max_size {
            inner.pop_front();
        }
        inner.push_back(RequestLifecycleSnapshot {
            id,
            correlation: correlation.into(),
            provider: provider.into(),
            model: model.into(),
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
        id
    }

    fn update(&self, id: u64, f: impl FnOnce(&mut RequestLifecycleSnapshot)) {
        let mut inner = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(record) = inner.iter_mut().rev().find(|record| record.id == id) {
            f(record);
        }
    }

    pub fn mark_forwarded(&self, id: u64) {
        self.update(id, |record| {
            record.forwarded_at_ms.get_or_insert_with(Self::now_ms);
        });
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
        self.update(id, |record| {
            record.client_status = Some(status);
            // Keep legacy `status` as the client-facing value for old
            // diagnostic consumers; r35 health uses raw_upstream_status.
            record.status = Some(status);
        });
    }

    pub fn mark_first_event(&self, id: u64) {
        self.update(id, |record| {
            record.first_event_at_ms.get_or_insert_with(Self::now_ms);
        });
    }

    pub fn mark_completed(&self, id: u64, status: u16, bytes: u64) {
        self.update(id, |record| {
            if record.terminal.is_none() {
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
        });
    }

    pub fn mark_failed(&self, id: u64, stage: &'static str) {
        self.update(id, |record| {
            if record.terminal.is_none() {
                record.completed_at_ms = Some(Self::now_ms());
                record.terminal = Some(format!("failed:{stage}"));
            }
        });
    }

    pub fn mark_cancelled(&self, id: u64) {
        self.update(id, |record| {
            if record.terminal.is_none() {
                record.completed_at_ms = Some(Self::now_ms());
                record.terminal = Some("cancelled".to_owned());
            }
        });
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
    fn log_buffer_keeps_recent_entries_and_writes_daily_file() {
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

        let today = Local::now().format("%Y-%m-%d").to_string();
        let log_path = dir.join(format!("proxy-{today}.log"));
        let content = fs::read_to_string(log_path).unwrap();
        assert!(content.contains("\tINFO\tfirst request"));
        assert!(content.contains("\tERROR\tfailed request"));
        assert!(content.contains("\tSUCCESS\tfinished request"));

        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn log_buffer_clear_archives_proxy_log_files() {
        let dir = unique_temp_dir("logs-clear");
        let buffer = LogBuffer::new_in_dir(20, dir.clone());

        buffer.add("INFO", "before clear");
        let today = Local::now().format("%Y-%m-%d").to_string();
        let log_path = dir.join(format!("proxy-{today}.log"));
        assert!(log_path.exists());

        buffer.clear();

        assert!(buffer.get_all().is_empty());
        assert!(!log_path.exists());

        let backup_dir = dir.join("backup");
        let archived: Vec<PathBuf> = fs::read_dir(&backup_dir)
            .unwrap()
            .flatten()
            .map(|entry| entry.path())
            .collect();
        assert_eq!(archived.len(), 1);
        assert!(archived[0]
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("")
            .starts_with(&format!("proxy-{today}_")));
        let content = fs::read_to_string(&archived[0]).unwrap();
        assert!(content.contains("\tINFO\tbefore clear"));

        let _ = fs::remove_dir_all(dir);
    }
}
