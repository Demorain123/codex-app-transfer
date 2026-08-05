from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R34-RUNTIME-BEHAVIOR-HEALTH"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r34 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    if old not in body:
        raise SystemExit(f"r34 anchor missing: {label}")
    if body.count(old) != 1:
        raise SystemExit(f"r34 anchor not unique ({body.count(old)}): {label}")
    return body.replace(old, new, 1)


telemetry_rel = "crates/proxy/src/telemetry.rs"
telemetry = load(telemetry_rel)
if MARKER not in telemetry:
    lifecycle_code = r'''
// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
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
                record.status = Some(status);
                record.bytes = bytes;
                record.terminal = Some("completed".to_owned());
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

'''
    telemetry = replace_once(
        telemetry,
        "#[derive(Debug)]\npub struct ProxyTelemetry {",
        lifecycle_code + "#[derive(Debug)]\npub struct ProxyTelemetry {",
        "telemetry lifecycle definitions",
    )
    telemetry = replace_once(
        telemetry,
        "pub struct ProxyTelemetry {\n    pub stats: ProxyStats,\n    pub logs: LogBuffer,\n}",
        "pub struct ProxyTelemetry {\n    pub stats: ProxyStats,\n    pub logs: LogBuffer,\n    pub lifecycles: RequestLifecycleTracker,\n}",
        "telemetry tracker field",
    )
    telemetry = replace_once(
        telemetry,
        "Self {\n            stats: ProxyStats::default(),\n            logs: LogBuffer::new(200),\n        }",
        "Self {\n            stats: ProxyStats::default(),\n            logs: LogBuffer::new(200),\n            lifecycles: RequestLifecycleTracker::default(),\n        }",
        "telemetry tracker default",
    )
    save(telemetry_rel, telemetry)

forward_rel = "crates/proxy/src/forward.rs"
forward = load(forward_rel)
if MARKER not in forward:
    helper = r'''
// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
// Select a stable-but-non-reversible conversation correlation. Raw identity
// header values never enter telemetry; the existing FNV helper emits 8 hex chars.
fn request_lifecycle_correlation_r34(headers: &HeaderMap) -> String {
    for name in [
        "thread-id",
        "x-session-id",
        "session-id",
        "session_id",
        "x-client-request-id",
    ] {
        let fingerprint = sub2api_retry_runtime_diag_header_fingerprint(headers, name);
        if fingerprint != "-" {
            return format!("{name}:{fingerprint}");
        }
    }
    "uncorrelated".to_owned()
}

'''
    forward = replace_once(
        forward,
        "pub async fn forward_handler(\n",
        helper + "pub async fn forward_handler(\n",
        "forward lifecycle correlation helper",
    )
    old_send = '''    let (initial_resp, mut outbound_headers_snapshot) = build_and_send_upstream(
        &state,
        &parts.method,
        &parts.headers,
        &resolved,
        &plan.body,
        &plan.upstream_headers,
        &upstream_url,
    )
    .await?;
'''
    new_send = '''    // CAS-R34-RUNTIME-BEHAVIOR-HEALTH: start only after local diagnostic
    // short-circuits have passed, so every record describes a real upstream attempt.
    let lifecycle_id = telemetry.lifecycles.start(
        request_lifecycle_correlation_r34(&parts.headers),
        resolved.provider.id.clone(),
        retry_runtime_diag_model.unwrap_or("<unknown>").to_owned(),
    );
    telemetry.lifecycles.mark_forwarded(lifecycle_id);
    let (initial_resp, mut outbound_headers_snapshot) = match build_and_send_upstream(
        &state,
        &parts.method,
        &parts.headers,
        &resolved,
        &plan.body,
        &plan.upstream_headers,
        &upstream_url,
    )
    .await
    {
        Ok(pair) => pair,
        Err(error) => {
            telemetry
                .lifecycles
                .mark_failed(lifecycle_id, "upstream_send");
            return Err(error);
        }
    };
    telemetry
        .lifecycles
        .mark_headers(lifecycle_id, initial_resp.status().as_u16());
'''
    forward = replace_once(forward, old_send, new_send, "initial upstream lifecycle")
    old_transform = '''    let response_plan = adapter.transform_response_stream(
        status,
        upstream_headers,
        upstream_stream,
        &resolved.provider,
        &plan,
    )?;
'''
    new_transform = '''    let response_plan = match adapter.transform_response_stream(
        status,
        upstream_headers,
        upstream_stream,
        &resolved.provider,
        &plan,
    ) {
        Ok(plan) => plan,
        Err(error) => {
            telemetry
                .lifecycles
                .mark_failed(lifecycle_id, "response_transform");
            return Err(error.into());
        }
    };
'''
    forward = replace_once(forward, old_transform, new_transform, "response transform lifecycle")
    old_status = '''    let success = response_plan.status.is_success();
    telemetry.stats.record(success);
'''
    new_status = '''    let success = response_plan.status.is_success();
    telemetry
        .lifecycles
        .mark_headers(lifecycle_id, response_plan.status.as_u16());
    telemetry.stats.record(success);
'''
    forward = replace_once(forward, old_status, new_status, "final response lifecycle status")
    old_body = '''    let codex_stream: codex_app_transfer_adapters::ByteStream = if forward_trace_enabled() {
        Box::pin(CodexRespStream::new(
            response_plan.stream,
            codex_method,
            codex_path,
            codex_status,
            codex_ct,
        ))
    } else {
        response_plan.stream
    };
    Ok(builder.body(Body::from_stream(codex_stream))?)
'''
    new_body = '''    let codex_stream: codex_app_transfer_adapters::ByteStream = if forward_trace_enabled() {
        Box::pin(CodexRespStream::new(
            response_plan.stream,
            codex_method,
            codex_path,
            codex_status,
            codex_ct,
        ))
    } else {
        response_plan.stream
    };
    let codex_stream: codex_app_transfer_adapters::ByteStream = Box::pin(
        RequestLifecycleStreamR34::new(codex_stream, lifecycle_id, codex_status),
    );
    Ok(builder.body(Body::from_stream(codex_stream))?)
'''
    forward = replace_once(forward, old_body, new_body, "final lifecycle stream wrapper")
    stream_code = r'''
// CAS-R34-RUNTIME-BEHAVIOR-HEALTH-STREAM
// Wrap the final proxy→Codex stream, not the raw upstream stream. This means the
// lifecycle reflects what Codex can actually consume after adapter conversion.
struct RequestLifecycleStreamR34 {
    inner: codex_app_transfer_adapters::ByteStream,
    id: u64,
    status: u16,
    bytes: u64,
    first_event: bool,
    finished: bool,
}

impl RequestLifecycleStreamR34 {
    fn new(
        inner: codex_app_transfer_adapters::ByteStream,
        id: u64,
        status: u16,
    ) -> Self {
        Self {
            inner,
            id,
            status,
            bytes: 0,
            first_event: false,
            finished: false,
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
                Poll::Ready(Some(Ok(chunk)))
            }
            Poll::Ready(Some(Err(error))) => {
                this.finished = true;
                proxy_telemetry()
                    .lifecycles
                    .mark_failed(this.id, "response_stream");
                Poll::Ready(Some(Err(error)))
            }
            Poll::Ready(None) => {
                this.finished = true;
                proxy_telemetry()
                    .lifecycles
                    .mark_completed(this.id, this.status, this.bytes);
                Poll::Ready(None)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

impl Drop for RequestLifecycleStreamR34 {
    fn drop(&mut self) {
        if !self.finished {
            proxy_telemetry().lifecycles.mark_cancelled(self.id);
        }
    }
}

'''
    forward = replace_once(
        forward,
        "/// [MOC-194] tee **proxy→Codex 转换后响应**:",
        stream_code + "/// [MOC-194] tee **proxy→Codex 转换后响应**:",
        "lifecycle stream type",
    )
    save(forward_rel, forward)

health_rel = "src-tauri/src/admin/handlers/chain_health.rs"
health = load(health_rel)
if MARKER not in health:
    health = replace_once(
        health,
        "    restart_count: u64,\n    cpu: Option<String>,",
        "    restart_count: u64,\n    restart_delta: u64,\n    cpu: Option<String>,",
        "container restart delta field",
    )
    health = replace_once(
        health,
        "    codex: HealthLayer,\n    transfer: HealthLayer,",
        "    codex: HealthLayer,\n    session: HealthLayer,\n    mcp: HealthLayer,\n    transfer: HealthLayer,",
        "snapshot behavior layers",
    )
    baseline_code = r'''

// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
// Docker RestartCount is cumulative for the container lifetime. Keep an in-memory
// baseline and alert only on an increase observed while Transfer is running.
static DOCKER_RESTART_BASELINE_R34: OnceLock<std::sync::Mutex<HashMap<String, u64>>> = OnceLock::new();

fn observe_restart_delta_r34(id: &str, current: u64) -> u64 {
    let store = DOCKER_RESTART_BASELINE_R34
        .get_or_init(|| std::sync::Mutex::new(HashMap::new()));
    let mut store = store.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let delta = store
        .get(id)
        .map(|previous| current.saturating_sub(*previous))
        .unwrap_or(0);
    store.insert(id.to_owned(), current);
    delta
}
'''
    health = replace_once(
        health,
        "pub async fn chain_health(\n",
        baseline_code + "\npub async fn chain_health(\n",
        "restart baseline state",
    )
    health = replace_once(
        health,
        "    let codex = codex_layer();\n\n    let proxy_status",
        "    let codex = codex_layer();\n    let session = session_layer();\n    let mcp = mcp_layer();\n\n    let proxy_status",
        "build behavior layers",
    )
    health = replace_once(
        health,
        "    let recommendations = recommendations(&transfer, &gateway, &runtime, &upstream);\n    let overall = overall_status([&codex, &transfer, &gateway, &runtime.layer, &upstream]);",
        "    let recommendations = recommendations(\n        &session, &mcp, &transfer, &gateway, &runtime, &upstream,\n    );\n    let overall = overall_status([\n        &codex, &session, &mcp, &transfer, &gateway, &runtime.layer, &upstream,\n    ]);",
        "overall behavior layers",
    )
    health = replace_once(
        health,
        "        codex,\n        transfer,",
        "        codex,\n        session,\n        mcp,\n        transfer,",
        "serialize behavior layers",
    )
    old_container = '''        containers.push(DockerContainerHealth {
            target: target_prefixes
'''
    new_container = '''        let restart_count = value
            .get("RestartCount")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let restart_delta = observe_restart_delta_r34(&id, restart_count);
        containers.push(DockerContainerHealth {
            target: target_prefixes
'''
    health = replace_once(health, old_container, new_container, "restart delta calculation")
    health = replace_once(
        health,
        '''            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            cpu:''',
        '''            restart_count,
            restart_delta,
            cpu:''',
        "restart delta assignment",
    )
    health = replace_once(
        health,
        '''    } else if containers.iter().any(|container| {
        container.health.as_deref() == Some("starting")
            || !container.running
            || container.restart_count > 0
    }) {
        level = "degraded";
        code = "docker_stack_degraded";
        summary = "Docker 容器栈正在启动或存在历史重启";
    }
''',
        '''    } else if containers.iter().any(|container| {
        container.health.as_deref() == Some("starting")
            || !container.running
            || container.restart_delta > 0
    }) {
        level = "degraded";
        code = "docker_stack_degraded";
        summary = "Docker 容器栈正在启动或最近观测到新的容器重启";
    }
''',
        "restart count false-positive fix",
    )
    behavior_code = r'''

// CAS-R34-RUNTIME-BEHAVIOR-HEALTH-SESSION
fn session_layer() -> HealthLayer {
    let records = proxy_telemetry().lifecycles.snapshot();
    if records.is_empty() {
        return HealthLayer::new(
            "idle",
            "session_no_requests",
            "尚无可用于判断会话 / Turn 行为的结构化请求证据",
        )
        .fact("mode=metadata-only-no-content");
    }

    let now = Local::now().timestamp_millis();
    let recent_cutoff = now.saturating_sub(30 * 60 * 1000);
    let recent: Vec<_> = records
        .iter()
        .filter(|record| record.accepted_at_ms >= recent_cutoff)
        .collect();
    let in_flight: Vec<_> = recent
        .iter()
        .copied()
        .filter(|record| record.terminal.is_none())
        .collect();
    let completed = recent
        .iter()
        .filter(|record| record.terminal.as_deref() == Some("completed"))
        .count();
    let failed = recent
        .iter()
        .filter(|record| {
            record
                .terminal
                .as_deref()
                .is_some_and(|value| value.starts_with("failed:"))
        })
        .count();
    let cancelled = recent
        .iter()
        .filter(|record| record.terminal.as_deref() == Some("cancelled"))
        .count();

    let mut longest_wait_seconds = 0u64;
    let mut hard_stall = false;
    let mut soft_stall = false;
    for record in &in_flight {
        let (anchor, hard_after, soft_after) = if let Some(first) = record.first_event_at_ms {
            (first, 15 * 60, 5 * 60)
        } else if let Some(headers) = record.headers_at_ms {
            (headers, 90, 20)
        } else {
            (record.forwarded_at_ms.unwrap_or(record.accepted_at_ms), 90, 20)
        };
        let age = now.saturating_sub(anchor).max(0) as u64 / 1000;
        longest_wait_seconds = longest_wait_seconds.max(age);
        hard_stall |= age >= hard_after;
        soft_stall |= age >= soft_after;
    }

    let mut retry_recoveries = 0usize;
    for current in recent
        .iter()
        .copied()
        .filter(|record| record.terminal.as_deref() == Some("completed"))
    {
        let recovered = recent.iter().copied().any(|prior| {
            if prior.id == current.id
                || prior.accepted_at_ms >= current.accepted_at_ms
                || prior.correlation != current.correlation
                || prior.provider != current.provider
                || prior.model != current.model
            {
                return false;
            }
            let gap = current.accepted_at_ms.saturating_sub(prior.accepted_at_ms);
            if !(5_000..=180_000).contains(&gap) {
                return false;
            }
            prior.terminal.as_deref() == Some("cancelled")
                || prior
                    .terminal
                    .as_deref()
                    .is_some_and(|value| value.starts_with("failed:"))
                || (prior.headers_at_ms.is_none() && gap >= 20_000)
        });
        if recovered {
            retry_recoveries += 1;
        }
    }

    let (status, code, summary) = if hard_stall {
        (
            "error",
            "session_turn_stalled",
            "检测到请求在响应头、首事件或流收尾阶段长时间停滞",
        )
    } else if soft_stall {
        (
            "degraded",
            "session_turn_waiting",
            "检测到正在等待的会话 / Turn，需要继续观察",
        )
    } else if retry_recoveries > 0 {
        (
            "degraded",
            "session_retry_recovered",
            "检测到一次静默/失败请求后由后续重试恢复",
        )
    } else if failed > 0 || cancelled > 0 {
        (
            "degraded",
            "session_recent_failure",
            "最近 30 分钟存在失败或取消的 Turn",
        )
    } else {
        (
            "ok",
            "session_behavior_healthy",
            "最近结构化请求生命周期未发现明确会话异常",
        )
    };

    HealthLayer::new(status, code, summary)
        .latency((longest_wait_seconds > 0).then_some(longest_wait_seconds * 1000))
        .fact(format!("recent_requests={}", recent.len()))
        .fact(format!(
            "in_flight={} completed={} failed={} cancelled={}",
            in_flight.len(), completed, failed, cancelled
        ))
        .fact(format!("retry_recoveries={retry_recoveries}"))
        .fact("correlation=fingerprinted-no-prompt")
}

#[cfg(target_os = "windows")]
#[derive(Clone)]
struct WindowsProcessTopologyR34 {
    pid: u32,
    parent_pid: u32,
    name: String,
}

#[cfg(target_os = "windows")]
fn windows_process_topology_r34() -> Vec<WindowsProcessTopologyR34> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };
    unsafe {
        let Ok(snapshot) = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) else {
            return Vec::new();
        };
        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        let mut rows = Vec::new();
        if Process32FirstW(snapshot, &mut entry).is_ok() {
            loop {
                let len = entry
                    .szExeFile
                    .iter()
                    .position(|value| *value == 0)
                    .unwrap_or(entry.szExeFile.len());
                rows.push(WindowsProcessTopologyR34 {
                    pid: entry.th32ProcessID,
                    parent_pid: entry.th32ParentProcessID,
                    name: String::from_utf16_lossy(&entry.szExeFile[..len]),
                });
                if Process32NextW(snapshot, &mut entry).is_err() {
                    break;
                }
            }
        }
        let _ = CloseHandle(snapshot);
        rows
    }
}

#[cfg(target_os = "windows")]
fn mcp_helper_candidate_r34(name: &str) -> bool {
    let base = name.trim_end_matches(".exe").to_ascii_lowercase();
    matches!(
        base.as_str(),
        "node"
            | "node_repl"
            | "python"
            | "python3"
            | "pythonw"
            | "uv"
            | "uvx"
            | "npx"
            | "deno"
            | "bun"
            | "dotnet"
            | "java"
    ) || [
        "mcp",
        "playwright",
        "context7",
        "tavily",
        "chrome-devtools",
        "contextweaver",
        "grok-search",
    ]
    .iter()
    .any(|needle| base.contains(needle))
}

#[cfg(target_os = "windows")]
fn guard_recent_failures_r34() -> (usize, usize, Option<String>) {
    use std::io::{Read, Seek, SeekFrom};
    let Some(local) = std::env::var_os("LOCALAPPDATA") else {
        return (0, 0, None);
    };
    let path = std::path::PathBuf::from(local)
        .join("CodexMcpJanitorR32")
        .join("events.jsonl");
    let Ok(mut file) = std::fs::File::open(path) else {
        return (0, 0, None);
    };
    let len = file.metadata().map(|meta| meta.len()).unwrap_or(0);
    let cap = 128 * 1024u64;
    if len > cap {
        let _ = file.seek(SeekFrom::Start(len - cap));
    }
    let mut text = String::new();
    if file.read_to_string(&mut text).is_err() {
        return (0, 0, None);
    }
    let cutoff = Local::now().timestamp().saturating_sub(30 * 60);
    let mut stop_failed = 0usize;
    let mut inventory_failed = 0usize;
    let mut last_cleanup = None;
    for line in text.lines().rev().take(300) {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let recent = value
            .get("ts")
            .and_then(Value::as_str)
            .and_then(|value| chrono::DateTime::parse_from_rfc3339(value).ok())
            .is_some_and(|ts| ts.timestamp() >= cutoff);
        if !recent {
            continue;
        }
        match value.get("event").and_then(Value::as_str).unwrap_or("") {
            "helper_stop_failed" => stop_failed += 1,
            "inventory_failed" | "final_inventory_failed" => inventory_failed += 1,
            "cleanup_complete" if last_cleanup.is_none() => {
                let tracked = value.get("tracked").and_then(Value::as_u64).unwrap_or(0);
                let survivors = value.get("survivors").and_then(Value::as_u64).unwrap_or(0);
                let stopped = value.get("stopped").and_then(Value::as_u64).unwrap_or(0);
                last_cleanup = Some(format!(
                    "cleanup tracked={tracked} survivors={survivors} stopped={stopped}"
                ));
            }
            _ => {}
        }
    }
    (stop_failed, inventory_failed, last_cleanup)
}

fn mcp_layer() -> HealthLayer {
    #[cfg(target_os = "windows")]
    {
        let rows = windows_process_topology_r34();
        let by_id: HashMap<u32, &WindowsProcessTopologyR34> =
            rows.iter().map(|row| (row.pid, row)).collect();
        let roots: HashSet<u32> = rows
            .iter()
            .filter(|row| {
                row.name.eq_ignore_ascii_case("chatgpt.exe")
                    || row.name.eq_ignore_ascii_case("codex.exe")
            })
            .map(|row| row.pid)
            .collect();

        let mut names: HashMap<String, usize> = HashMap::new();
        let mut helpers = 0usize;
        for row in &rows {
            if roots.contains(&row.pid) || !mcp_helper_candidate_r34(&row.name) {
                continue;
            }
            let mut parent = row.parent_pid;
            let mut owned = false;
            let mut visited = HashSet::new();
            for _ in 0..64 {
                if roots.contains(&parent) {
                    owned = true;
                    break;
                }
                if parent == 0 || !visited.insert(parent) {
                    break;
                }
                let Some(next) = by_id.get(&parent) else {
                    break;
                };
                parent = next.parent_pid;
            }
            if owned {
                helpers += 1;
                *names.entry(row.name.to_ascii_lowercase()).or_default() += 1;
            }
        }
        let max_duplicate = names.values().copied().max().unwrap_or(0);
        let duplicate_name = names
            .iter()
            .max_by_key(|(_, count)| *count)
            .map(|(name, count)| format!("{name}={count}"));
        let (stop_failed, inventory_failed, last_cleanup) = guard_recent_failures_r34();

        let (status, code, summary) = if helpers >= 64 {
            (
                "error",
                "mcp_process_explosion",
                "Codex generation 下的 MCP/helper 进程数量异常膨胀",
            )
        } else if helpers >= 24 || max_duplicate >= 12 || stop_failed > 0 {
            (
                "degraded",
                "mcp_process_count_high",
                "MCP/helper 数量、重复实例或清理失败需要关注",
            )
        } else if inventory_failed > 0 {
            (
                "degraded",
                "mcp_guard_inventory_failed",
                "MCP Exit Guard 最近无法完成一次进程拓扑盘点",
            )
        } else if roots.is_empty() {
            (
                "idle",
                "mcp_codex_not_running",
                "Codex 未运行，当前没有活动 generation 可检查",
            )
        } else {
            (
                "ok",
                "mcp_generation_bounded",
                "当前 Codex generation 的 MCP/helper 进程处于有界范围",
            )
        };
        let mut layer = HealthLayer::new(status, code, summary)
            .fact(format!("codex_roots={}", roots.len()))
            .fact(format!("owned_helpers={helpers}"))
            .fact(format!("max_duplicate={max_duplicate}"))
            .fact(format!(
                "guard_stop_failed={stop_failed} guard_inventory_failed={inventory_failed}"
            ));
        if let Some(duplicate) = duplicate_name {
            layer = layer.fact(format!("largest_group={duplicate}"));
        }
        if let Some(cleanup) = last_cleanup {
            layer = layer.fact(cleanup);
        }
        return layer;
    }
    #[cfg(not(target_os = "windows"))]
    HealthLayer::new(
        "unknown",
        "mcp_probe_windows_only",
        "当前版本仅在 Windows 提供 MCP 进程拓扑探针",
    )
}
'''
    health = replace_once(
        health,
        "fn passive_upstream_layer() -> HealthLayer {",
        behavior_code + "\n\nfn passive_upstream_layer() -> HealthLayer {",
        "session and MCP health functions",
    )
    health = replace_once(
        health,
        '''fn recommendations(
    transfer: &HealthLayer,
    gateway: &HealthLayer,
    runtime: &RuntimeHealth,
    upstream: &HealthLayer,
) -> Vec<String> {
''',
        '''fn recommendations(
    session: &HealthLayer,
    mcp: &HealthLayer,
    transfer: &HealthLayer,
    gateway: &HealthLayer,
    runtime: &RuntimeHealth,
    upstream: &HealthLayer,
) -> Vec<String> {
''',
        "recommendations behavior parameters",
    )
    health = replace_once(
        health,
        '''    let mut out = Vec::new();
    match transfer.code.as_str() {''',
        '''    let mut out = Vec::new();
    match session.code.as_str() {
        "session_turn_stalled" => out.push(
            "会话 / Turn 已长期停滞：不要连续重复发送；先查看它停在响应头、首事件还是流收尾阶段。"
                .into(),
        ),
        "session_retry_recovered" => out.push(
            "检测到首次静默/失败后由重试恢复；保留该时间点的脱敏诊断包用于定位 Codex 状态竞态。"
                .into(),
        ),
        _ => {}
    }
    match mcp.code.as_str() {
        "mcp_process_explosion" => out.push(
            "MCP/helper 进程已异常膨胀：暂停创建新子代理，完成当前工作后退出 Codex，让 Exit Guard 回收本 generation。"
                .into(),
        ),
        "mcp_process_count_high" => out.push(
            "MCP/helper 数量偏高：观察 owned_helpers 是否持续增长，并检查重复最多的 helper 组。"
                .into(),
        ),
        "mcp_guard_inventory_failed" => out.push(
            "MCP Exit Guard 最近盘点失败；检查其 events.jsonl 与 PowerShell/CIM 可用性。".into(),
        ),
        _ => {}
    }
    match transfer.code.as_str() {''',
        "behavior recommendations",
    )
    health = health.replace(
        '"等待 health=starting 的容器就绪；若 RestartCount 持续增加，查看该容器日志。".into(),',
        '"等待 health=starting 的容器就绪；若界面显示 recent restart 增加，再查看该容器日志。".into(),',
        1,
    )
    health = replace_once(
        health,
        '            "命令与网络探针均有硬超时，不会无限等待".into(),',
        '            "命令与网络探针均有硬超时，不会无限等待".into(),\n            "会话关联只保存不可逆短指纹与阶段时间，不读取消息正文".into(),\n            "MCP 探针只检查当前 Codex 进程树中的候选 helper 名称与数量".into(),',
        "privacy behavior statements",
    )
    save(health_rel, health)

api_rel = "frontend/src/api/chainHealth.ts"
api = load(api_rel)
if MARKER not in api:
    api = replace_once(
        api,
        "  restartCount: number\n  cpu?: string | null",
        "  restartCount: number\n  restartDelta: number\n  cpu?: string | null",
        "frontend restart delta",
    )
    api = replace_once(
        api,
        "  codex: ChainHealthLayer\n  transfer: ChainHealthLayer",
        "  codex: ChainHealthLayer\n  session: ChainHealthLayer\n  mcp: ChainHealthLayer\n  transfer: ChainHealthLayer",
        "frontend behavior layers",
    )
    api = api.replace("// CAS-R33-CHAIN-HEALTH", "// CAS-R33-CHAIN-HEALTH\n// CAS-R34-RUNTIME-BEHAVIOR-HEALTH", 1)
    save(api_rel, api)

page_rel = "frontend/src/pages/ProxyPage.vue"
page = load(page_rel)
if MARKER not in page:
    page = replace_once(
        page,
        "    { key: 'codex', label: t('chainHealth.layer.codex'), data: h.codex },\n    { key: 'transfer'",
        "    { key: 'codex', label: t('chainHealth.layer.codex'), data: h.codex },\n    { key: 'session', label: t('chainHealth.layer.session'), data: h.session },\n    { key: 'mcp', label: t('chainHealth.layer.mcp'), data: h.mcp },\n    { key: 'transfer'",
        "behavior cards",
    )
    page = replace_once(
        page,
        "<span v-if=\"container.restartCount\">restart {{ container.restartCount }}</span>",
        "<span v-if=\"container.restartCount\">restart {{ container.restartCount }}</span>\n            <span v-if=\"container.restartDelta\">recent +{{ container.restartDelta }}</span>",
        "recent restart display",
    )
    page = page.replace("// CAS-R33-CHAIN-HEALTH", "// CAS-R33-CHAIN-HEALTH\n// CAS-R34-RUNTIME-BEHAVIOR-HEALTH", 1)
    save(page_rel, page)

for rel, labels in [
    (
        "frontend/src/i18n/zh.ts",
        {
            '"chainHealth.layer.codex": \'Codex\',': '"chainHealth.layer.codex": \'Codex\',\n  "chainHealth.layer.session": \'会话 / Turn\',\n  "chainHealth.layer.mcp": \'MCP 健康\',',
        },
    ),
    (
        "frontend/src/i18n/en.ts",
        {
            '"chainHealth.layer.codex": \'Codex\',': '"chainHealth.layer.codex": \'Codex\',\n  "chainHealth.layer.session": \'Session / Turn\',\n  "chainHealth.layer.mcp": \'MCP Health\',',
        },
    ),
]:
    body = load(rel)
    if MARKER not in body:
        for old, new in labels.items():
            body = replace_once(body, old, new, f"{rel} behavior labels")
        body = body.replace(
            "// Auto-extracted",
            f"// {MARKER}\n// Auto-extracted",
            1,
        )
        save(rel, body)

print("r34 runtime behavior health overlay: APPLIED")
