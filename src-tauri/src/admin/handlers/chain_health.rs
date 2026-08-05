//! CAS-R33-CHAIN-HEALTH
//!
//! Privacy-bounded, non-destructive chain health diagnostics for the active Codex route.
//! Automatic checks never send a model inference request and never read prompt text,
//! credentials, container environment variables, or response bodies.

use std::collections::{HashMap, HashSet};
use std::net::IpAddr;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use axum::{
    extract::{Query, State},
    response::IntoResponse,
    Json,
};
use chrono::{Local, NaiveTime, Timelike};
use codex_app_transfer_proxy::proxy_telemetry;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::net::{lookup_host, TcpStream};
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio::time::timeout;

use super::super::registry_io::load as load_registry;
use super::super::state::AdminState;

const CACHE_TTL: Duration = Duration::from_secs(8);
const DNS_TIMEOUT: Duration = Duration::from_secs(2);
const TCP_TIMEOUT: Duration = Duration::from_secs(2);
const HTTP_TIMEOUT: Duration = Duration::from_secs(4);
const COMMAND_TIMEOUT: Duration = Duration::from_millis(2600);
const MAX_CONTAINERS: usize = 12;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct HealthLayer {
    status: String,
    code: String,
    summary: String,
    latency_ms: Option<u64>,
    facts: Vec<String>,
}

impl HealthLayer {
    fn new(status: &str, code: &str, summary: impl Into<String>) -> Self {
        Self {
            status: status.to_owned(),
            code: code.to_owned(),
            summary: summary.into(),
            latency_ms: None,
            facts: Vec::new(),
        }
    }

    fn latency(mut self, value: Option<u64>) -> Self {
        self.latency_ms = value;
        self
    }

    fn fact(mut self, value: impl Into<String>) -> Self {
        self.facts.push(value.into());
        self
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProviderTarget {
    id: String,
    name: String,
    base_url: String,
    display_url: String,
    api_format: String,
    host: String,
    port: u16,
    loopback: bool,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
struct DockerContainerHealth {
    id: String,
    name: String,
    service: Option<String>,
    running: bool,
    status: String,
    health: Option<String>,
    restarting: bool,
    oom_killed: bool,
    exit_code: i64,
    restart_count: u64,
    restart_delta: u64,
    cpu: Option<String>,
    memory: Option<String>,
    pids: Option<String>,
    target: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeHealth {
    layer: HealthLayer,
    kind: String,
    docker_desktop: Option<String>,
    docker_server_version: Option<String>,
    compose_project: Option<String>,
    containers: Vec<DockerContainerHealth>,
    owner_pid: Option<u32>,
    owner_process: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ChainHealthSnapshot {
    observed_at: String,
    overall: String,
    overall_summary: String,
    provider: Option<ProviderTarget>,
    codex: HealthLayer,
    session: HealthLayer,
    mcp: HealthLayer,
    transfer: HealthLayer,
    gateway: HealthLayer,
    runtime: RuntimeHealth,
    upstream: HealthLayer,
    recommendations: Vec<String>,
    privacy: Vec<String>,
}

#[derive(Debug, Clone)]
struct CachedSnapshot {
    captured: Instant,
    snapshot: ChainHealthSnapshot,
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ChainHealthQuery {
    force: Option<bool>,
}

static CACHE: OnceLock<Mutex<Option<CachedSnapshot>>> = OnceLock::new();

fn cache() -> &'static Mutex<Option<CachedSnapshot>> {
    CACHE.get_or_init(|| Mutex::new(None))
}

// CAS-R34-RUNTIME-BEHAVIOR-HEALTH
// Docker RestartCount is cumulative for the container lifetime. Keep an in-memory
// baseline and alert only on an increase observed while Transfer is running.
static DOCKER_RESTART_BASELINE_R34: OnceLock<std::sync::Mutex<HashMap<String, u64>>> =
    OnceLock::new();

fn observe_restart_delta_r34(id: &str, current: u64) -> u64 {
    let store = DOCKER_RESTART_BASELINE_R34.get_or_init(|| std::sync::Mutex::new(HashMap::new()));
    let mut store = store
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let delta = store
        .get(id)
        .map(|previous| current.saturating_sub(*previous))
        .unwrap_or(0);
    store.insert(id.to_owned(), current);
    delta
}

pub async fn chain_health(
    State(state): State<AdminState>,
    Query(query): Query<ChainHealthQuery>,
) -> impl IntoResponse {
    if !query.force.unwrap_or(false) {
        let guard = cache().lock().await;
        if let Some(cached) = guard.as_ref() {
            if cached.captured.elapsed() < CACHE_TTL {
                return Json(json!({"success": true, "health": cached.snapshot}));
            }
        }
    }

    let snapshot = build_snapshot(&state).await;
    *cache().lock().await = Some(CachedSnapshot {
        captured: Instant::now(),
        snapshot: snapshot.clone(),
    });
    Json(json!({"success": true, "health": snapshot}))
}

async fn build_snapshot(state: &AdminState) -> ChainHealthSnapshot {
    let cfg = load_registry().unwrap_or_else(|_| json!({}));
    let provider = active_provider(&cfg);
    let codex = codex_layer();
    let session = session_layer();
    let mcp = mcp_layer();

    let proxy_status = state.proxy_manager.status();
    let stats = proxy_telemetry().stats.snapshot();
    let transfer = if proxy_status.running {
        let port = proxy_status
            .addr
            .as_deref()
            .and_then(|value| value.rsplit(':').next())
            .unwrap_or("unknown");
        HealthLayer::new("ok", "transfer_listening", "Transfer 本地转发器正在监听")
            .fact(format!("listener={port}"))
            .fact(format!(
                "requests={} success={} failed={}",
                stats.total, stats.success, stats.failed
            ))
            .fact(format!(
                "active_provider={}",
                proxy_status.active_provider.as_deref().unwrap_or("none")
            ))
    } else {
        HealthLayer::new("error", "transfer_stopped", "Transfer 本地转发器未运行")
            .fact(format!("requests={} failed={}", stats.total, stats.failed))
    };

    let gateway = match provider.as_ref() {
        Some(target) => probe_gateway(target).await,
        None => HealthLayer::new("unknown", "provider_missing", "没有可诊断的活动 provider"),
    };

    let runtime = match provider.as_ref() {
        Some(target) if target.loopback => probe_local_runtime(target, &gateway).await,
        Some(_) => RuntimeHealth {
            layer: HealthLayer::new(
                "ok",
                "remote_gateway",
                "活动网关位于远程主机，不检查本机 Docker",
            )
            .fact("runtime=remote"),
            kind: "remote".into(),
            docker_desktop: None,
            docker_server_version: None,
            compose_project: None,
            containers: Vec::new(),
            owner_pid: None,
            owner_process: None,
        },
        None => RuntimeHealth {
            layer: HealthLayer::new("unknown", "runtime_unknown", "无法确定网关运行环境"),
            kind: "unknown".into(),
            docker_desktop: None,
            docker_server_version: None,
            compose_project: None,
            containers: Vec::new(),
            owner_pid: None,
            owner_process: None,
        },
    };

    let upstream = passive_upstream_layer();
    let recommendations = recommendations(&session, &mcp, &transfer, &gateway, &runtime, &upstream);
    let overall = overall_status([
        &codex,
        &session,
        &mcp,
        &transfer,
        &gateway,
        &runtime.layer,
        &upstream,
    ]);
    let overall_summary = match overall.as_str() {
        "error" => "链路存在明确故障，展开建议可查看最可能的阻断层",
        "degraded" => "链路可用性下降或有请求等待，需要继续观察",
        "ok" => "自动无额度探针未发现明确故障",
        _ => "当前证据不足，等待一次真实请求后可获得更多被动证据",
    }
    .to_owned();

    ChainHealthSnapshot {
        observed_at: Local::now().to_rfc3339(),
        overall,
        overall_summary,
        provider,
        codex,
        session,
        mcp,
        transfer,
        gateway,
        runtime,
        upstream,
        recommendations,
        privacy: vec![
            "自动检查不发送模型推理请求".into(),
            "不读取 prompt、响应正文、SSH 命令、API Key 或 OAuth token".into(),
            "Docker 检查不读取容器环境变量，也不开放 Docker socket".into(),
            "命令与网络探针均有硬超时，不会无限等待".into(),
            "会话关联只保存不可逆短指纹与阶段时间，不读取消息正文".into(),
            "MCP 探针只检查当前 Codex 进程树中的候选 helper 名称与数量".into(),
        ],
    }
}

fn active_provider(cfg: &Value) -> Option<ProviderTarget> {
    let active_id = cfg.get("activeProvider")?.as_str()?;
    let provider = cfg
        .get("providers")?
        .as_array()?
        .iter()
        .find(|item| item.get("id").and_then(Value::as_str) == Some(active_id))?;
    let raw = provider.get("baseUrl")?.as_str()?.trim();
    let mut url = reqwest::Url::parse(raw).ok()?;
    if !matches!(url.scheme(), "http" | "https") {
        return None;
    }
    let _ = url.set_username("");
    let _ = url.set_password(None);
    url.set_query(None);
    url.set_fragment(None);
    let host = url.host_str()?.to_owned();
    let port = url.port_or_known_default()?;
    let loopback = host.eq_ignore_ascii_case("localhost")
        || host
            .parse::<IpAddr>()
            .map(|ip| ip.is_loopback())
            .unwrap_or(false);
    Some(ProviderTarget {
        id: active_id.to_owned(),
        name: provider
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or(active_id)
            .to_owned(),
        // CAS-R33-CHAIN-HEALTH-PRIVACY: never serialize URL userinfo/query/fragment.
        base_url: url.to_string().trim_end_matches('/').to_owned(),
        display_url: url.to_string().trim_end_matches('/').to_owned(),
        api_format: provider
            .get("apiFormat")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_owned(),
        host,
        port,
        loopback,
    })
}

async fn probe_gateway(target: &ProviderTarget) -> HealthLayer {
    let dns_started = Instant::now();
    let resolved = match timeout(
        DNS_TIMEOUT,
        lookup_host((target.host.as_str(), target.port)),
    )
    .await
    {
        Ok(Ok(addrs)) => {
            let mut unique = Vec::new();
            for addr in addrs {
                if !unique.contains(&addr) {
                    unique.push(addr);
                }
                if unique.len() >= 4 {
                    break;
                }
            }
            unique
        }
        Ok(Err(error)) => {
            return HealthLayer::new("error", "gateway_dns_failed", "网关主机 DNS 解析失败")
                .fact(format!("error={}", compact_error(&error.to_string())));
        }
        Err(_) => {
            return HealthLayer::new("error", "gateway_dns_timeout", "网关主机 DNS 解析超时")
                .latency(Some(DNS_TIMEOUT.as_millis() as u64));
        }
    };
    let dns_ms = dns_started.elapsed().as_millis() as u64;
    if resolved.is_empty() {
        return HealthLayer::new("error", "gateway_dns_empty", "DNS 未返回可连接地址")
            .latency(Some(dns_ms));
    }

    let tcp_started = Instant::now();
    let tcp_result = timeout(TCP_TIMEOUT, async {
        for addr in &resolved {
            if TcpStream::connect(addr).await.is_ok() {
                return true;
            }
        }
        false
    })
    .await;
    let tcp_ms = tcp_started.elapsed().as_millis() as u64;
    match tcp_result {
        Err(_) => {
            return HealthLayer::new("error", "gateway_tcp_timeout", "网关端口连接超时")
                .latency(Some(tcp_ms))
                .fact(format!("target={}:{}", target.host, target.port))
                .fact(format!("dns_ms={dns_ms}"));
        }
        Ok(false) => {
            return HealthLayer::new("error", "gateway_tcp_refused", "网关端口未接受连接")
                .latency(Some(tcp_ms))
                .fact(format!("target={}:{}", target.host, target.port))
                .fact(format!("dns_ms={dns_ms}"));
        }
        Ok(true) => {}
    }

    let client = match reqwest::Client::builder()
        .connect_timeout(TCP_TIMEOUT)
        .timeout(HTTP_TIMEOUT)
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!(
            "Codex-App-Transfer-Chain-Health/",
            env!("CARGO_PKG_VERSION")
        ))
        .build()
    {
        Ok(client) => client,
        Err(error) => {
            return HealthLayer::new(
                "degraded",
                "gateway_http_client_failed",
                "TCP 可达，但 HTTP 探针初始化失败",
            )
            .fact(format!("error={}", compact_error(&error.to_string())));
        }
    };

    let http_started = Instant::now();
    let response = match client.head(&target.display_url).send().await {
        Ok(response) => Ok(response),
        Err(_) => client.get(&target.display_url).send().await,
    };
    let http_ms = http_started.elapsed().as_millis() as u64;
    match response {
        Ok(response) => {
            let status = response.status().as_u16();
            let (level, code, summary) = match status {
                401 | 403 => (
                    "degraded",
                    "gateway_auth_required",
                    "网关可达，但鉴权未通过或未携带凭据",
                ),
                429 => (
                    "degraded",
                    "gateway_rate_limited",
                    "网关可达，但当前处于限流状态",
                ),
                500..=599 => (
                    "error",
                    "gateway_http_5xx",
                    "网关返回 5xx，应用或其依赖可能异常",
                ),
                _ => (
                    "ok",
                    "gateway_http_reachable",
                    "网关 DNS、TCP 与 HTTP 均可响应",
                ),
            };
            HealthLayer::new(level, code, summary)
                .latency(Some(http_ms))
                .fact(format!("http_status={status}"))
                .fact(format!(
                    "dns_ms={dns_ms} tcp_ms={tcp_ms} http_headers_ms={http_ms}"
                ))
                .fact(format!("endpoint={}", target.display_url))
        }
        Err(error) => {
            let code = if error.is_timeout() {
                "gateway_http_timeout"
            } else if error.is_connect() {
                "gateway_http_connect_error"
            } else if error.is_redirect() {
                "gateway_http_redirect_error"
            } else {
                "gateway_http_error"
            };
            HealthLayer::new("error", code, "网关 TCP 可达，但 HTTP 没有正常返回响应头")
                .latency(Some(http_ms))
                .fact(format!("error={}", compact_error(&error.to_string())))
                .fact(format!("dns_ms={dns_ms} tcp_ms={tcp_ms}"))
        }
    }
}

#[derive(Debug)]
enum CommandKind {
    Ok,
    Exit,
    Timeout,
    NotFound,
    SpawnError,
}

#[derive(Debug)]
struct CommandResult {
    kind: CommandKind,
    stdout: String,
    stderr: String,
    exit_code: Option<i32>,
}

async fn run_command(program: &str, args: &[String], limit: Duration) -> CommandResult {
    let mut command = Command::new(program);
    command.args(args).kill_on_drop(true);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt as _;
        command.as_std_mut().creation_flags(0x0800_0000);
    }
    match timeout(limit, command.output()).await {
        Err(_) => CommandResult {
            kind: CommandKind::Timeout,
            stdout: String::new(),
            stderr: String::new(),
            exit_code: None,
        },
        Ok(Err(error)) if error.kind() == std::io::ErrorKind::NotFound => CommandResult {
            kind: CommandKind::NotFound,
            stdout: String::new(),
            stderr: compact_error(&error.to_string()),
            exit_code: None,
        },
        Ok(Err(error)) => CommandResult {
            kind: CommandKind::SpawnError,
            stdout: String::new(),
            stderr: compact_error(&error.to_string()),
            exit_code: None,
        },
        Ok(Ok(output)) => CommandResult {
            kind: if output.status.success() {
                CommandKind::Ok
            } else {
                CommandKind::Exit
            },
            stdout: String::from_utf8_lossy(&output.stdout).trim().to_owned(),
            stderr: compact_error(&String::from_utf8_lossy(&output.stderr)),
            exit_code: output.status.code(),
        },
    }
}

async fn probe_local_runtime(target: &ProviderTarget, gateway: &HealthLayer) -> RuntimeHealth {
    let desktop = run_command(
        "docker",
        &[
            "desktop".into(),
            "status".into(),
            "--format".into(),
            "json".into(),
        ],
        Duration::from_millis(1600),
    )
    .await;
    let desktop_status = if matches!(desktop.kind, CommandKind::Ok) {
        Some(compact_error(&desktop.stdout))
    } else {
        None
    };

    let info = run_command(
        "docker",
        &[
            "info".into(),
            "--format".into(),
            "{{json .ServerVersion}}".into(),
        ],
        COMMAND_TIMEOUT,
    )
    .await;
    match info.kind {
        CommandKind::Timeout => {
            return RuntimeHealth {
                layer: HealthLayer::new(
                    "error",
                    "docker_daemon_timeout",
                    "Docker CLI 自身超时，Docker Engine/Desktop 可能卡死",
                )
                .latency(Some(COMMAND_TIMEOUT.as_millis() as u64))
                .fact("probe=docker info"),
                kind: "docker".into(),
                docker_desktop: desktop_status,
                docker_server_version: None,
                compose_project: None,
                containers: Vec::new(),
                owner_pid: None,
                owner_process: None,
            };
        }
        CommandKind::NotFound => {
            return native_runtime(target, gateway, "docker_cli_not_found").await
        }
        CommandKind::Exit | CommandKind::SpawnError => {
            return RuntimeHealth {
                layer: HealthLayer::new(
                    "error",
                    "docker_daemon_unavailable",
                    "检测到 Docker CLI，但无法连接 Docker Engine",
                )
                .fact(format!("exit_code={:?}", info.exit_code))
                .fact(format!("error={}", info.stderr)),
                kind: "docker".into(),
                docker_desktop: desktop_status,
                docker_server_version: None,
                compose_project: None,
                containers: Vec::new(),
                owner_pid: None,
                owner_process: None,
            };
        }
        CommandKind::Ok => {}
    }

    let server_version = info.stdout.trim_matches('"').to_owned();
    let target_ids_result = run_command(
        "docker",
        &[
            "ps".into(),
            "-aq".into(),
            "--filter".into(),
            format!("publish={}", target.port),
        ],
        COMMAND_TIMEOUT,
    )
    .await;
    if !matches!(target_ids_result.kind, CommandKind::Ok) {
        return RuntimeHealth {
            layer: HealthLayer::new(
                "degraded",
                "docker_container_query_failed",
                "Docker Engine 可达，但容器查询失败",
            )
            .fact(format!("error={}", target_ids_result.stderr)),
            kind: "docker".into(),
            docker_desktop: desktop_status,
            docker_server_version: Some(server_version),
            compose_project: None,
            containers: Vec::new(),
            owner_pid: None,
            owner_process: None,
        };
    }

    let target_ids: Vec<String> = target_ids_result
        .stdout
        .lines()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .take(MAX_CONTAINERS)
        .map(ToOwned::to_owned)
        .collect();
    if target_ids.is_empty() {
        let mut native = native_runtime(target, gateway, "docker_no_port_mapping").await;
        native.docker_desktop = desktop_status;
        native.docker_server_version = Some(server_version);
        return native;
    }

    let initial = inspect_containers(&target_ids).await;
    let compose_project = initial.iter().find_map(compose_project_of);
    let mut all_ids: HashSet<String> = target_ids.iter().cloned().collect();
    if let Some(project) = compose_project.as_deref() {
        let project_ids = run_command(
            "docker",
            &[
                "ps".into(),
                "-aq".into(),
                "--filter".into(),
                format!("label=com.docker.compose.project={project}"),
            ],
            COMMAND_TIMEOUT,
        )
        .await;
        if matches!(project_ids.kind, CommandKind::Ok) {
            for id in project_ids
                .stdout
                .lines()
                .map(str::trim)
                .filter(|v| !v.is_empty())
            {
                if all_ids.len() >= MAX_CONTAINERS {
                    break;
                }
                all_ids.insert(id.to_owned());
            }
        }
    }
    let all_ids: Vec<String> = all_ids.into_iter().collect();
    let inspected = inspect_containers(&all_ids).await;
    let stats = container_stats(&all_ids).await;
    let target_prefixes: Vec<&str> = target_ids.iter().map(String::as_str).collect();
    let mut containers = Vec::new();
    for value in inspected {
        if is_compose_oneoff(&value) {
            continue;
        }
        let id = value
            .get("Id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let name = value
            .get("Name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim_start_matches('/')
            .to_owned();
        let state = &value;
        let health = state
            .get("HealthStatus")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned);
        let stat = stats.get(&id).or_else(|| {
            stats
                .iter()
                .find(|(key, _)| id.starts_with(key.as_str()))
                .map(|(_, v)| v)
        });
        containers.push(DockerContainerHealth {
            target: target_prefixes
                .iter()
                .any(|prefix| id.starts_with(*prefix) || prefix.starts_with(&id)),
            id: id.chars().take(12).collect(),
            name,
            service: compose_service_of(&value),
            running: state
                .get("Running")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            status: state
                .get("Status")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .to_owned(),
            health,
            restarting: state
                .get("Restarting")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            oom_killed: state
                .get("OOMKilled")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            exit_code: state.get("ExitCode").and_then(Value::as_i64).unwrap_or(0),
            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            restart_delta: observe_restart_delta_r34(
                &id,
                value
                    .get("RestartCount")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
            ),
            cpu: stat
                .and_then(|v| v.get("CPUPerc"))
                .and_then(Value::as_str)
                .map(ToOwned::to_owned),
            memory: stat
                .and_then(|v| v.get("MemUsage"))
                .and_then(Value::as_str)
                .map(ToOwned::to_owned),
            pids: stat
                .and_then(|v| v.get("PIDs"))
                .and_then(Value::as_str)
                .map(ToOwned::to_owned),
        });
    }
    containers.sort_by_key(|container| (!container.target, container.name.clone()));

    let mut level = "ok";
    let mut code = "docker_stack_healthy";
    let mut summary = "Docker Engine 与目标容器栈正常";
    if containers.iter().any(|container| {
        container.oom_killed
            || container.restarting
            || container.health.as_deref() == Some("unhealthy")
            || (!container.running && container.exit_code != 0)
    }) {
        level = "error";
        code = "docker_stack_failed";
        summary = "目标容器或 Compose 依赖存在退出、OOM、重启或 unhealthy";
    } else if containers.iter().any(|container| {
        container.health.as_deref() == Some("starting")
            || !container.running
            || container.restart_delta > 0
    }) {
        level = "degraded";
        code = "docker_stack_degraded";
        summary = "Docker 容器栈正在启动或最近观测到新的容器重启";
    }
    let mut layer = HealthLayer::new(level, code, summary)
        .fact(format!("docker_server={server_version}"))
        .fact(format!("containers={}", containers.len()));
    if let Some(project) = compose_project.as_deref() {
        layer = layer.fact(format!("compose_project={project}"));
    }
    RuntimeHealth {
        layer,
        kind: "docker".into(),
        docker_desktop: desktop_status,
        docker_server_version: Some(server_version),
        compose_project,
        containers,
        owner_pid: None,
        owner_process: None,
    }
}

async fn inspect_containers(ids: &[String]) -> Vec<Value> {
    if ids.is_empty() {
        return Vec::new();
    }
    // CAS-R33-CHAIN-HEALTH-INSPECT-PRIVACY: request a strict safe projection.
    // Bare `docker inspect` includes configuration secrets and mount details even
    // when the UI never renders them. Keep all unrequested fields outside Transfer.
    // CAS-R33-CHAIN-HEALTH-STATE-PROJECTION: project only scalar state fields.
    // Container state also carries historical healthcheck command output; diagnostics
    // need only the current status and must not ingest that output history.
    // CAS-R33-CHAIN-HEALTH-LABEL-PROJECTION: request only the three standard
    // Compose identity labels needed for dependency grouping. Custom labels stay
    // outside Transfer because they may contain user-defined sensitive metadata.
    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"HealthStatus":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"Restarting":{{json .State.Restarting}},"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},"RestartCount":{{json .RestartCount}},"ComposeProject":{{json (index .Config.Labels "com.docker.compose.project")}},"ComposeService":{{json (index .Config.Labels "com.docker.compose.service")}},"ComposeOneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}}}"#;
    let mut args = vec![
        "inspect".to_owned(),
        "--format".to_owned(),
        projection.to_owned(),
    ];
    args.extend(ids.iter().take(MAX_CONTAINERS).cloned());
    let result = run_command("docker", &args, Duration::from_secs(4)).await;
    if !matches!(result.kind, CommandKind::Ok) {
        return Vec::new();
    }
    result
        .stdout
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .collect()
}

async fn container_stats(ids: &[String]) -> HashMap<String, Value> {
    if ids.is_empty() {
        return HashMap::new();
    }
    let mut args = vec![
        "stats".to_owned(),
        "--no-stream".to_owned(),
        "--format".to_owned(),
        "{{json .}}".to_owned(),
    ];
    args.extend(ids.iter().take(8).cloned());
    let result = run_command("docker", &args, Duration::from_secs(4)).await;
    if !matches!(result.kind, CommandKind::Ok) {
        return HashMap::new();
    }
    let mut out = HashMap::new();
    for line in result.stdout.lines() {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let key = value
            .get("ID")
            .or_else(|| value.get("Container"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        if !key.is_empty() {
            out.insert(key, value);
        }
    }
    out
}

fn nonempty_string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn compose_project_of(value: &Value) -> Option<String> {
    nonempty_string(value, "ComposeProject")
}

fn compose_service_of(value: &Value) -> Option<String> {
    nonempty_string(value, "ComposeService")
}

fn is_compose_oneoff(value: &Value) -> bool {
    value
        .get("ComposeOneoff")
        .and_then(Value::as_str)
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

async fn native_runtime(
    target: &ProviderTarget,
    gateway: &HealthLayer,
    reason: &str,
) -> RuntimeHealth {
    let owner = native_port_owner(target.port).await;
    let reachable = gateway.status == "ok" || gateway.status == "degraded";
    let (status, code, summary) = if reachable {
        (
            "ok",
            "native_runtime_reachable",
            "本机端口由非 Docker 服务提供，网关探针可达",
        )
    } else if owner.is_some() {
        (
            "degraded",
            "native_runtime_unresponsive",
            "本机进程正在监听端口，但网关 HTTP 不正常",
        )
    } else {
        (
            "unknown",
            "native_runtime_unknown",
            "未发现映射该端口的 Docker 容器或可识别本机进程",
        )
    };
    let mut layer = HealthLayer::new(status, code, summary).fact(format!("reason={reason}"));
    if let Some((pid, name)) = owner.as_ref() {
        layer = layer.fact(format!("pid={pid} process={name}"));
    }
    RuntimeHealth {
        layer,
        kind: "native_or_unknown".into(),
        docker_desktop: None,
        docker_server_version: None,
        compose_project: None,
        containers: Vec::new(),
        owner_pid: owner.as_ref().map(|(pid, _)| *pid),
        owner_process: owner.map(|(_, name)| name),
    }
}

#[cfg(target_os = "windows")]
async fn native_port_owner(port: u16) -> Option<(u32, String)> {
    let result = run_command(
        "netstat",
        &["-ano".into(), "-p".into(), "tcp".into()],
        Duration::from_secs(2),
    )
    .await;
    if !matches!(result.kind, CommandKind::Ok) {
        return None;
    }
    let pid = result.stdout.lines().find_map(|line| {
        let cols: Vec<&str> = line.split_whitespace().collect();
        if cols.len() < 5
            || !cols[0].eq_ignore_ascii_case("TCP")
            || !cols[3].eq_ignore_ascii_case("LISTENING")
        {
            return None;
        }
        let local_port = cols[1].rsplit(':').next()?.parse::<u16>().ok()?;
        (local_port == port)
            .then(|| cols[4].parse::<u32>().ok())
            .flatten()
    })?;
    let name = windows_process_rows()
        .into_iter()
        .find(|(candidate, _)| *candidate == pid)
        .map(|(_, name)| name)
        .unwrap_or_else(|| "unknown".into());
    Some((pid, name))
}

#[cfg(not(target_os = "windows"))]
async fn native_port_owner(_port: u16) -> Option<(u32, String)> {
    None
}

fn codex_layer() -> HealthLayer {
    #[cfg(target_os = "windows")]
    {
        let rows = windows_process_rows();
        let chatgpt = rows
            .iter()
            .filter(|(_, name)| name.eq_ignore_ascii_case("chatgpt.exe"))
            .count();
        let codex = rows
            .iter()
            .filter(|(_, name)| name.eq_ignore_ascii_case("codex.exe"))
            .count();
        if chatgpt + codex == 0 {
            return HealthLayer::new(
                "idle",
                "codex_not_running",
                "未检测到 Codex Desktop / app-server 进程",
            );
        }
        let mut layer = HealthLayer::new("ok", "codex_running", "Codex Desktop 运行时已检测到")
            .fact(format!("chatgpt.exe={chatgpt}"))
            .fact(format!("codex.exe={codex}"));
        if codex > 8 {
            layer.status = "degraded".into();
            layer.code = "codex_process_count_high".into();
            layer.summary = "Codex 相关进程数量偏高，需要结合 MCP/子代理监控观察".into();
        }
        return layer;
    }
    #[cfg(not(target_os = "windows"))]
    HealthLayer::new(
        "unknown",
        "codex_probe_windows_only",
        "当前版本仅在 Windows 提供 Codex 原生进程探针",
    )
}

#[cfg(target_os = "windows")]
fn windows_process_rows() -> Vec<(u32, String)> {
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
                rows.push((
                    entry.th32ProcessID,
                    String::from_utf16_lossy(&entry.szExeFile[..len]),
                ));
                if Process32NextW(snapshot, &mut entry).is_err() {
                    break;
                }
            }
        }
        let _ = CloseHandle(snapshot);
        rows
    }
}

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
            (
                record.forwarded_at_ms.unwrap_or(record.accepted_at_ms),
                90,
                20,
            )
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
            in_flight.len(),
            completed,
            failed,
            cancelled
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

fn passive_upstream_layer() -> HealthLayer {
    let logs = proxy_telemetry().logs.get_all();
    let mut last_forward: Option<(usize, String)> = None;
    let mut last_status: Option<(usize, String, u16)> = None;
    let mut last_timing: Option<(usize, String)> = None;
    let mut last_error: Option<(usize, String)> = None;
    for (index, entry) in logs.iter().enumerate() {
        let message = entry.message.as_str();
        if message.contains("forwarding →") || message.contains("forwarding ->") {
            last_forward = Some((index, entry.time.clone()));
        }
        if let Some(code) = parse_upstream_status(message) {
            last_status = Some((index, entry.time.clone(), code));
        }
        if message.starts_with("upstream timing ") {
            last_timing = Some((index, entry.time.clone()));
        }
        if entry.level.eq_ignore_ascii_case("error")
            && (message.contains("upstream") || message.contains("request"))
        {
            last_error = Some((index, compact_error(message)));
        }
    }

    let Some((forward_index, forward_time)) = last_forward else {
        return HealthLayer::new(
            "idle",
            "upstream_no_requests",
            "尚无可用于判断上游的真实请求证据",
        )
        .fact("mode=passive-no-inference");
    };
    let age = age_seconds(&forward_time).unwrap_or(0);
    let status_index = last_status.as_ref().map(|item| item.0).unwrap_or(0);
    let timing_index = last_timing.as_ref().map(|item| item.0).unwrap_or(0);
    if forward_index > status_index {
        let level = if age >= 90 {
            "error"
        } else if age >= 20 {
            "degraded"
        } else {
            "ok"
        };
        let code = if age >= 90 {
            "upstream_headers_stalled"
        } else {
            "upstream_waiting_headers"
        };
        return HealthLayer::new(level, code, "请求已转发，但尚未收到网关/上游响应头")
            .latency(Some(age.saturating_mul(1000)))
            .fact(format!("waiting_seconds={age}"))
            .fact("evidence=proxy-log-order-best-effort");
    }
    if status_index > timing_index {
        return HealthLayer::new(
            "ok",
            "upstream_streaming",
            "已收到响应头，流式响应仍在进行或尚未记录收尾",
        )
        .latency(Some(age.saturating_mul(1000)))
        .fact("evidence=proxy-log-order-best-effort");
    }
    if let Some((error_index, error)) = last_error {
        if error_index > timing_index {
            return HealthLayer::new(
                "error",
                "upstream_recent_error",
                "最近一次请求在 Transfer/上游阶段失败",
            )
            .fact(format!("error={error}"));
        }
    }
    if let Some((_, _, status)) = last_status {
        let (level, code, summary) = match status {
            401 | 403 => (
                "degraded",
                "upstream_auth_error",
                "最近请求到达上游，但鉴权失败",
            ),
            429 => (
                "degraded",
                "upstream_rate_limited",
                "最近请求被限流或账号配额不足",
            ),
            500..=599 => ("error", "upstream_5xx", "最近请求收到网关/上游 5xx"),
            _ => (
                "ok",
                "upstream_recent_complete",
                "最近请求已获得响应并记录收尾时间",
            ),
        };
        return HealthLayer::new(level, code, summary)
            .fact(format!("http_status={status}"))
            .fact("mode=passive-no-inference");
    }
    HealthLayer::new(
        "unknown",
        "upstream_evidence_incomplete",
        "检测到转发记录，但上游证据不完整",
    )
}

fn parse_upstream_status(message: &str) -> Option<u16> {
    let rest = message.strip_prefix("upstream status ")?;
    rest.split_whitespace().next()?.parse().ok()
}

fn age_seconds(hms: &str) -> Option<u64> {
    let then = NaiveTime::parse_from_str(hms, "%H:%M:%S").ok()?;
    let now = Local::now().time();
    let now_seconds = now.num_seconds_from_midnight() as i64;
    let then_seconds = then.num_seconds_from_midnight() as i64;
    let mut delta = now_seconds - then_seconds;
    if delta < 0 {
        delta += 24 * 60 * 60;
    }
    Some(delta as u64)
}

fn recommendations(
    session: &HealthLayer,
    mcp: &HealthLayer,
    transfer: &HealthLayer,
    gateway: &HealthLayer,
    runtime: &RuntimeHealth,
    upstream: &HealthLayer,
) -> Vec<String> {
    let mut out = Vec::new();
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
    match transfer.code.as_str() {
        "transfer_stopped" => out.push("先启动 Transfer 转发器，再测试 Codex 新会话。".into()),
        _ => {}
    }
    match runtime.layer.code.as_str() {
        "docker_daemon_timeout" => out.push(
            "Docker CLI 探针超时：先保存工作并重启 Docker Desktop；仅重启 Codex 通常无效。".into(),
        ),
        "docker_daemon_unavailable" => out.push(
            "Docker Engine 不可用：检查 Docker Desktop 是否启动，以及 Linux/Windows engine 是否正确。".into(),
        ),
        "docker_stack_failed" => out.push(
            "展开容器明细，优先处理 OOM、unhealthy、restarting 或非零退出的 Sub2API/Redis/PostgreSQL 服务。".into(),
        ),
        "docker_stack_degraded" => out.push(
            "等待 health=starting 的容器就绪；若界面显示 recent restart 增加，再查看该容器日志。".into(),
        ),
        _ => {}
    }
    match gateway.code.as_str() {
        "gateway_tcp_timeout" | "gateway_tcp_refused" => {
            out.push("检查活动 provider 的端口、容器端口映射和本机防火墙。".into())
        }
        "gateway_http_timeout" | "gateway_http_error" => out.push(
            "端口已建立但 HTTP 无响应：网关进程、数据库、Redis 或 Docker Engine 可能卡住。".into(),
        ),
        "gateway_auth_required" => out.push(
            "网关本身可达；继续检查 Transfer provider 的 API Key/OAuth 与网关 token。".into(),
        ),
        "gateway_rate_limited" => {
            out.push("检查网关账号池的额度、RPM/TPM、冷却和已用尽账号是否仍被调度。".into())
        }
        "gateway_http_5xx" => out
            .push("网关返回 5xx：查看网关及其数据库/Redis日志，再判断是否为真正上游故障。".into()),
        _ => {}
    }
    match upstream.code.as_str() {
        "upstream_headers_stalled" => out.push(
            "请求转发后 90 秒仍无响应头：不要连续重复发送；先检查网关/Docker，再取消或重启失效请求。".into(),
        ),
        "upstream_auth_error" => out.push("最近真实请求鉴权失败，需要重新登录或更换有效账号。".into()),
        "upstream_rate_limited" => out.push("最近真实请求被限流，检查账号配额与网关调度策略。".into()),
        "upstream_5xx" => out.push("最近真实请求收到 5xx，可结合网关日志确认是网关还是最终上游。".into()),
        _ => {}
    }
    if out.is_empty() {
        out.push(
            "自动探针未发现明确故障；用全新 Codex 会话发送一次极小请求，再观察被动上游状态。"
                .into(),
        );
    }
    out
}

fn overall_status<'a>(layers: impl IntoIterator<Item = &'a HealthLayer>) -> String {
    let mut rank = 0;
    let mut selected = "unknown";
    for layer in layers {
        let current = match layer.status.as_str() {
            "error" => 4,
            "degraded" => 3,
            "ok" => 2,
            "idle" => 1,
            _ => 0,
        };
        if current > rank {
            rank = current;
            selected = layer.status.as_str();
        }
    }
    selected.to_owned()
}

fn compact_error(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(220)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_provider_redacts_userinfo_query_and_fragment() {
        let cfg = json!({
            "activeProvider": "p1",
            "providers": [{
                "id": "p1",
                "name": "local",
                "baseUrl": "http://user:secret@127.0.0.1:8113/v1?token=secret#frag",
                "apiFormat": "openai_responses"
            }]
        });
        let provider = active_provider(&cfg).unwrap();
        assert_eq!(provider.display_url, "http://127.0.0.1:8113/v1");
        assert!(provider.loopback);
        assert!(!provider.display_url.contains("secret"));
    }

    #[test]
    fn upstream_status_parser_is_strict() {
        assert_eq!(
            parse_upstream_status("upstream status 200 http://x"),
            Some(200)
        );
        assert_eq!(parse_upstream_status("something status 200"), None);
    }

    #[test]
    fn compose_oneoff_is_ignored() {
        assert!(is_compose_oneoff(&json!({"ComposeOneoff": "True"})));
        assert_eq!(
            compose_project_of(&json!({"ComposeProject": "deploy"})).as_deref(),
            Some("deploy")
        );
    }

    #[test]
    fn severity_prefers_explicit_error() {
        let ok = HealthLayer::new("ok", "ok", "ok");
        let degraded = HealthLayer::new("degraded", "d", "d");
        let error = HealthLayer::new("error", "e", "e");
        assert_eq!(overall_status([&ok, &degraded, &error]), "error");
    }
}
