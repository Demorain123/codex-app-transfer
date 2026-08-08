from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r37 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r37 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Proxy lifecycle: capture only the small, standard Codex quota headers that
# already come back on a REAL response. This sends no extra inference request.
# If Sub2API does not preserve these headers the fields simply stay None and the
# guard falls back to passive 429/503/no-available-account evidence.
# ---------------------------------------------------------------------------
rel = "crates/proxy/src/telemetry.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "    pub request_bytes: u64,\n    pub status: Option<u16>,",
        "    pub request_bytes: u64,\n"
        "    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n"
        "    // Quota metadata is copied only from standard x-codex response headers.\n"
        "    // Account identity, when present, is already an irreversible 8-char fingerprint.\n"
        "    pub quota_primary_used_percent: Option<f32>,\n"
        "    pub quota_secondary_used_percent: Option<f32>,\n"
        "    pub quota_primary_reset_after_seconds: Option<u64>,\n"
        "    pub quota_secondary_reset_after_seconds: Option<u64>,\n"
        "    pub quota_account_fingerprint: Option<String>,\n"
        "    pub status: Option<u16>,",
        "quota lifecycle fields",
    )
    body = replace_once(
        body,
        "            request_bytes,\n            status: None,",
        "            request_bytes,\n"
        "            quota_primary_used_percent: None,\n"
        "            quota_secondary_used_percent: None,\n"
        "            quota_primary_reset_after_seconds: None,\n"
        "            quota_secondary_reset_after_seconds: None,\n"
        "            quota_account_fingerprint: None,\n"
        "            status: None,",
        "quota lifecycle initialization",
    )
    anchor = '''    pub fn mark_client_status(&self, id: u64, status: u16) {
'''
    method = '''    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD: update quota metadata without
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

'''
    body = replace_once(body, anchor, method + anchor, "quota lifecycle method")
    # Put a stable file-level marker close to the r35 lifecycle comment.
    body = body.replace(
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH\n",
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH\n// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        1,
    )
    save(rel, body)


# ---------------------------------------------------------------------------
# Forwarder: copy Codex plan-limit headers from the FINAL raw provider response.
# These headers are informational and must never by themselves abort a stream.
# ---------------------------------------------------------------------------
rel = "crates/proxy/src/forward.rs"
body = load(rel)
if MARKER not in body:
    anchor = '''    telemetry
        .lifecycles
        .mark_headers(lifecycle_id, status.as_u16());
'''
    quota_capture = '''    telemetry
        .lifecycles
        .mark_headers(lifecycle_id, status.as_u16());
    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD
    // OpenAI Codex exposes 5h/weekly plan usage through x-codex-* headers.
    // Sub2API may or may not preserve them. Capture only numeric quota metadata
    // plus an irreversible account fingerprint when the header is available.
    let quota_primary_used_percent = upstream_headers
        .get("x-codex-primary-used-percent")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<f32>().ok());
    let quota_secondary_used_percent = upstream_headers
        .get("x-codex-secondary-used-percent")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<f32>().ok());
    let quota_primary_reset_after_seconds = upstream_headers
        .get("x-codex-primary-reset-after-seconds")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok());
    let quota_secondary_reset_after_seconds = upstream_headers
        .get("x-codex-secondary-reset-after-seconds")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok());
    let quota_account_fingerprint = {
        let fp = sub2api_retry_runtime_diag_header_fingerprint(&upstream_headers, "x-codex-user-id");
        (fp != "-").then_some(fp)
    };
    telemetry.lifecycles.mark_quota(
        lifecycle_id,
        quota_primary_used_percent,
        quota_secondary_used_percent,
        quota_primary_reset_after_seconds,
        quota_secondary_reset_after_seconds,
        quota_account_fingerprint,
    );
'''
    body = replace_once(body, anchor, quota_capture, "quota response header capture")
    save(rel, body)


# ---------------------------------------------------------------------------
# Health center: one compact account/quota layer + one non-card attribution
# result. No account-management UI and no active inference probes.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/handlers/chain_health.rs"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "//! CAS-R36-SAFE-RECOVERY\n",
        "//! CAS-R36-SAFE-RECOVERY\n//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        1,
    )
    body = replace_once(
        body,
        "const RECOVERY_COMMAND_TIMEOUT: Duration = Duration::from_secs(12);\n",
        "const RECOVERY_COMMAND_TIMEOUT: Duration = Duration::from_secs(12);\n"
        "const R37_EVIDENCE_WINDOW_SECS: u64 = 15 * 60;\n"
        "const R37_LARGE_CONTEXT_BYTES: u64 = 8 * 1024 * 1024;\n",
        "r37 constants",
    )
    body = replace_once(
        body,
        "    runtime: RuntimeHealth,\n    upstream: HealthLayer,\n    recommendations: Vec<String>,",
        "    runtime: RuntimeHealth,\n"
        "    account: HealthLayer,\n"
        "    upstream: HealthLayer,\n"
        "    diagnosis: HealthLayer,\n"
        "    recommendations: Vec<String>,",
        "snapshot fields",
    )

    # Recovery: quota/session failures must not cause a healthy Docker gateway restart.
    body = replace_once(
        body,
        '''        "upstream_rate_limited" => {
''',
        '''        "account_pool_exhausted" => {
            actions.push(RecoveryAction::skipped(
                "restart_gateway_container",
                "检测到账号池无可用账号/真实额度阻断；重启 healthy Sub2API、Docker 或 Transfer 不会补充额度，已跳过",
            ));
            actions.push(RecoveryAction::skipped(
                "retry_immediately",
                "等待账号额度/冷却恢复或在 Sub2API 中补充可用账号；恢复器不会自动制造额外模型请求",
            ));
            needs_real_request_verification = true;
        }
        "quota_warning" => {
            actions.push(RecoveryAction::skipped(
                "no_restart_for_quota_warning",
                "额度接近阈值但尚无权威阻断信号；保留当前链路，不执行重启",
            ));
        }
        "session_or_context_failure" => {
            actions.push(RecoveryAction::skipped(
                "no_infrastructure_restart",
                "同 provider 仍有成功会话或检测到大型上下文/compaction 证据；不重启健康网关，优先 fork/新建会话验证",
            ));
            actions.push(RecoveryAction::skipped(
                "preserve_thread_evidence",
                "保留旧会话现场，避免连续重试扩大上下文和上游消耗",
            ));
        }
        "upstream_rate_limited" => {
''',
        "recovery classifications",
    )
    body = replace_once(
        body,
        '''    if snapshot.upstream.code == "upstream_rate_limited" {
        return "upstream_rate_limited";
    }
''',
        '''    if snapshot.account.code == "account_pool_exhausted" {
        return "account_pool_exhausted";
    }
    if matches!(
        snapshot.account.code.as_str(),
        "account_quota_elevated" | "account_quota_near_exhaustion"
    ) {
        return "quota_warning";
    }
    if matches!(
        snapshot.diagnosis.code.as_str(),
        "fault_session_scoped" | "fault_session_state" | "fault_compaction_context"
    ) {
        return "session_or_context_failure";
    }
    if snapshot.upstream.code == "upstream_rate_limited" {
        return "upstream_rate_limited";
    }
''',
        "recovery priority",
    )

    body = replace_once(
        body,
        '''    let upstream = passive_upstream_layer();
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
''',
        '''    let upstream = passive_upstream_layer();
    let account = account_pool_layer_r37(&upstream);
    let diagnosis = fault_attribution_layer_r37(&session, &account, &upstream);
    let recommendations = recommendations(
        &session,
        &mcp,
        &transfer,
        &gateway,
        &runtime,
        &account,
        &upstream,
        &diagnosis,
    );
    let overall = overall_status([
        &codex,
        &session,
        &mcp,
        &transfer,
        &gateway,
        &runtime.layer,
        &account,
        &upstream,
        &diagnosis,
    ]);
    let overall_summary = if !matches!(diagnosis.code.as_str(), "fault_none" | "fault_no_evidence") {
        format!("最可能故障归因：{}", diagnosis.summary)
    } else {
        match overall.as_str() {
            "error" => "链路存在明确故障，展开建议可查看最可能的阻断层".to_owned(),
            "degraded" => "链路可用性下降或有请求等待，需要继续观察".to_owned(),
            "ok" => "轻量诊断未发现明确故障".to_owned(),
            _ => "当前证据不足，等待一次真实请求后可获得更多被动证据".to_owned(),
        }
    };
''',
        "snapshot diagnosis composition",
    )
    body = replace_once(
        body,
        "        runtime,\n        upstream,\n        recommendations,",
        "        runtime,\n        account,\n        upstream,\n        diagnosis,\n        recommendations,",
        "snapshot assignment",
    )
    body = replace_once(
        body,
        '''            "MCP 探针只检查当前 Codex 进程树中的候选 helper 名称与数量".into(),
''',
        '''            "MCP 探针只检查当前 Codex 进程树中的候选 helper 名称与数量".into(),
            "额度预警只读取真实响应中已有的 x-codex 百分比/重置时间；不额外发送模型请求".into(),
            "若上游提供用户标识，仅保存不可逆 8 字符指纹，不保存账号邮箱或原始 user id".into(),
''',
        "privacy quota facts",
    )

    helpers = r'''
// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD
fn recent_log_age_r37(needle: &str, max_age_seconds: u64) -> Option<u64> {
    let needle = needle.to_ascii_lowercase();
    proxy_telemetry()
        .logs
        .get_all()
        .iter()
        .rev()
        .take(320)
        .filter_map(|entry| {
            if !entry.message.to_ascii_lowercase().contains(&needle) {
                return None;
            }
            let age = age_seconds(&entry.time)?;
            (age <= max_age_seconds).then_some(age)
        })
        .min()
}

fn account_pool_layer_r37(upstream: &HealthLayer) -> HealthLayer {
    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let no_accounts_age = recent_log_age_r37("no available accounts", R37_EVIDENCE_WINDOW_SECS);

    // A later successful real request means an earlier no-account event recovered.
    let latest_success_age = records
        .iter()
        .rev()
        .find(|record| {
            record.raw_upstream_status.is_some_and(|status| status < 400)
                && record.terminal.as_deref() == Some("completed")
        })
        .map(|record| now_ms.saturating_sub(record.accepted_at_ms).max(0) as u64 / 1000);

    if let Some(error_age) = no_accounts_age {
        let recovered = latest_success_age.is_some_and(|success_age| success_age < error_age);
        let mut layer = if recovered {
            HealthLayer::new(
                "degraded",
                "account_pool_recently_recovered",
                "最近出现过无可用账号，但之后已有真实请求恢复成功",
            )
        } else {
            HealthLayer::new(
                "error",
                "account_pool_exhausted",
                "Sub2API 明确报告当前账号池没有可调度账号",
            )
        };
        layer = layer
            .fact(format!("no_available_accounts_age_s={error_age}"))
            .fact("evidence=passive-upstream-error")
            .fact("restart_fix=false");
        return layer;
    }

    if upstream.code == "upstream_rate_limited" {
        return HealthLayer::new(
            "error",
            "account_pool_rate_limited",
            "真实请求已收到 429，账号额度/速率限制或冷却正在阻断请求",
        )
        .fact("evidence=raw-http-429")
        .fact("restart_fix=false");
    }

    let quota = records.iter().rev().find(|record| {
        record.quota_primary_used_percent.is_some()
            || record.quota_secondary_used_percent.is_some()
    });
    if let Some(record) = quota {
        let used = match (
            record.quota_primary_used_percent,
            record.quota_secondary_used_percent,
        ) {
            (Some(a), Some(b)) => Some(a.max(b)),
            (Some(a), None) | (None, Some(a)) => Some(a),
            _ => None,
        };
        let (status, code, summary) = match used {
            Some(value) if value >= 95.0 => (
                "degraded",
                "account_quota_near_exhaustion",
                "账号额度已接近用尽；used_percent 仅作预警，真实 429/无账号才是权威阻断信号",
            ),
            Some(value) if value >= 70.0 => (
                "degraded",
                "account_quota_elevated",
                "账号额度消耗已进入预警区间",
            ),
            Some(_) => ("ok", "account_quota_healthy", "最近真实响应携带的账号额度仍在安全区间"),
            None => ("idle", "account_quota_unobserved", "当前响应未携带可读取的账号额度百分比"),
        };
        let mut layer = HealthLayer::new(status, code, summary)
            .fact(format!(
                "primary_used_percent={}",
                record
                    .quota_primary_used_percent
                    .map(|v| format!("{v:.1}"))
                    .unwrap_or_else(|| "-".into())
            ))
            .fact(format!(
                "secondary_used_percent={}",
                record
                    .quota_secondary_used_percent
                    .map(|v| format!("{v:.1}"))
                    .unwrap_or_else(|| "-".into())
            ))
            .fact(format!(
                "primary_reset_after_s={}",
                record
                    .quota_primary_reset_after_seconds
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "-".into())
            ))
            .fact(format!(
                "secondary_reset_after_s={}",
                record
                    .quota_secondary_reset_after_seconds
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "-".into())
            ))
            .fact("source=x-codex-response-headers");
        if let Some(fp) = record.quota_account_fingerprint.as_deref() {
            layer = layer.fact(format!("account_fp={fp}"));
        }
        return layer;
    }

    HealthLayer::new(
        "idle",
        "account_quota_unobserved",
        "尚未从真实响应读取到额度元数据；仍会被动识别 429/无可用账号",
    )
    .fact("probe=zero-extra-inference")
    .fact("fallback=429|no-available-accounts")
}

fn fault_attribution_layer_r37(
    session: &HealthLayer,
    account: &HealthLayer,
    upstream: &HealthLayer,
) -> HealthLayer {
    if matches!(
        account.code.as_str(),
        "account_pool_exhausted" | "account_pool_rate_limited"
    ) {
        return HealthLayer::new(
            "error",
            "fault_account_pool",
            "账号池 / 配额是当前最强故障证据",
        )
        .fact(format!("account_code={}", account.code))
        .fact("infra_restart_not_recommended=true");
    }

    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let cutoff = now_ms.saturating_sub(30 * 60 * 1000);
    let failed = records.iter().rev().find(|record| {
        record.accepted_at_ms >= cutoff
            && (record.raw_upstream_status.is_some_and(|status| status >= 400)
                || record
                    .terminal
                    .as_deref()
                    .is_some_and(|value| value == "upstream_error" || value.starts_with("failed:")))
    });

    if let Some(record) = failed {
        let compact_signal = recent_log_age_r37("\"request_kind\":\"compaction\"", R37_EVIDENCE_WINDOW_SECS)
            .or_else(|| recent_log_age_r37("compact-v2", R37_EVIDENCE_WINDOW_SECS));
        let generic_upstream_400 = record.raw_upstream_status == Some(400)
            && recent_log_age_r37("upstream request failed", R37_EVIDENCE_WINDOW_SECS).is_some();
        if record.request_bytes >= R37_LARGE_CONTEXT_BYTES
            && (compact_signal.is_some() || generic_upstream_400)
        {
            return HealthLayer::new(
                "error",
                "fault_compaction_context",
                "大型旧会话的 context / compaction 路径比账号池或 Docker 更可疑",
            )
            .fact(format!("model={} provider={}", record.model, record.provider))
            .fact(format!("request_bytes={}", record.request_bytes))
            .fact(format!(
                "raw_status={}",
                record
                    .raw_upstream_status
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "-".into())
            ))
            .fact("threshold_bytes=8388608");
        }

        let other_success = records.iter().rev().any(|candidate| {
            candidate.accepted_at_ms >= cutoff
                && candidate.provider == record.provider
                && candidate.model == record.model
                && candidate.correlation != record.correlation
                && candidate.raw_upstream_status.is_some_and(|status| status < 400)
                && candidate.terminal.as_deref() == Some("completed")
        });
        let start_failed = recent_log_age_r37("failed_to_start_turn", 5 * 60).is_some()
            || recent_log_age_r37("agent loop died unexpectedly", 5 * 60).is_some();
        if other_success {
            return HealthLayer::new(
                "error",
                "fault_session_scoped",
                "同模型、同 provider 的其他会话近期成功，故障更像当前 thread/session 局部状态",
            )
            .fact(format!("model={} provider={}", record.model, record.provider))
            .fact(format!("failed_correlation={}", record.correlation))
            .fact(format!("local_start_error={start_failed}"));
        }
        if start_failed {
            return HealthLayer::new(
                "error",
                "fault_session_state",
                "Codex 本地 Turn/agent loop 状态异常是当前最强证据",
            )
            .fact(format!("session_code={}", session.code));
        }

        let failed_correlations: HashSet<&str> = records
            .iter()
            .filter(|candidate| {
                candidate.accepted_at_ms >= cutoff
                    && candidate.provider == record.provider
                    && candidate.model == record.model
                    && candidate.raw_upstream_status.is_some_and(|status| status >= 400)
            })
            .map(|candidate| candidate.correlation.as_str())
            .collect();
        if failed_correlations.len() >= 2 {
            return HealthLayer::new(
                "error",
                "fault_shared_upstream",
                "同模型 / provider 的多个独立会话均失败，更像账号调度或共享上游故障",
            )
            .fact(format!("failed_threads={}", failed_correlations.len()))
            .fact(format!("upstream_code={}", upstream.code));
        }
    }

    if session.code == "session_turn_stalled" {
        return HealthLayer::new(
            "degraded",
            "fault_session_state",
            "当前只看到会话 Turn 停滞，尚无共享上游故障证据",
        );
    }
    if upstream.status == "error" {
        return HealthLayer::new(
            "error",
            "fault_upstream",
            "当前最强证据仍位于账号调度 / 共享上游层",
        )
        .fact(format!("upstream_code={}", upstream.code));
    }
    if upstream.status == "ok" || upstream.status == "idle" {
        return HealthLayer::new("ok", "fault_none", "当前没有足够证据指向明确故障层");
    }
    HealthLayer::new("unknown", "fault_no_evidence", "故障归因证据仍不足")
}

'''
    body = replace_once(body, "fn parse_upstream_status(message: &str) -> Option<u16> {\n", helpers + "fn parse_upstream_status(message: &str) -> Option<u16> {\n", "r37 helpers")

    body = replace_once(
        body,
        '''fn recommendations(
    session: &HealthLayer,
    mcp: &HealthLayer,
    transfer: &HealthLayer,
    gateway: &HealthLayer,
    runtime: &RuntimeHealth,
    upstream: &HealthLayer,
) -> Vec<String> {
    let mut out = Vec::new();
''',
        '''fn recommendations(
    session: &HealthLayer,
    mcp: &HealthLayer,
    transfer: &HealthLayer,
    gateway: &HealthLayer,
    runtime: &RuntimeHealth,
    account: &HealthLayer,
    upstream: &HealthLayer,
    diagnosis: &HealthLayer,
) -> Vec<String> {
    let mut out = Vec::new();
    match diagnosis.code.as_str() {
        "fault_account_pool" => out.push(
            "账号池已成为最强故障证据：不要继续换 Transfer 端口或重启 healthy Docker；先等待额度/冷却恢复或补充可用账号。".into(),
        ),
        "fault_compaction_context" => out.push(
            "大型旧会话的 context/compaction 路径异常：先 fork/新建会话做同模型对照；不要在坏会话里连续重复发送超大请求。".into(),
        ),
        "fault_session_scoped" => out.push(
            "同模型同 provider 的其他会话仍成功：优先把当前问题视为 thread/session 局部异常，建议 fork/新会话继续并保留旧会话诊断现场。".into(),
        ),
        "fault_session_state" => out.push(
            "检测到 failed_to_start_turn/agent-loop 类本地状态异常：基础设施重启不是首选，优先新建或 fork 会话验证。".into(),
        ),
        "fault_shared_upstream" => out.push(
            "多个独立会话在同一模型/provider 上失败：优先检查账号池调度、共享上游和供应商状态。".into(),
        ),
        _ => {}
    }
    match account.code.as_str() {
        "account_quota_near_exhaustion" => out.push(
            "额度已接近阈值：减少无意义重试；used_percent 仅用于预警，真正 429/No available accounts 才判定为耗尽。".into(),
        ),
        "account_quota_elevated" => out.push(
            "额度消耗进入预警区间，可提前准备备用账号/模型，避免长任务中途耗尽。".into(),
        ),
        "account_pool_recently_recovered" => out.push(
            "账号池刚从无可用账号状态恢复；先用一次小请求确认稳定，再继续大型任务。".into(),
        ),
        _ => {}
    }
''',
        "recommendations signature",
    )
    save(rel, body)


# ---------------------------------------------------------------------------
# Frontend: add ONE compact account/quota card; attribution is a single summary
# line, not another dashboard card/page.
# ---------------------------------------------------------------------------
rel = "frontend/src/api/chainHealth.ts"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R36-SAFE-RECOVERY\n",
        "// CAS-R36-SAFE-RECOVERY\n// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        1,
    )
    body = replace_once(
        body,
        "  runtime: ChainRuntimeHealth\n  upstream: ChainHealthLayer\n  recommendations: string[]",
        "  runtime: ChainRuntimeHealth\n  account: ChainHealthLayer\n  upstream: ChainHealthLayer\n  diagnosis: ChainHealthLayer\n  recommendations: string[]",
        "frontend snapshot fields",
    )
    save(rel, body)

rel = "frontend/src/pages/ProxyPage.vue"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R36-SAFE-RECOVERY\n",
        "// CAS-R36-SAFE-RECOVERY\n// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        1,
    )
    body = replace_once(
        body,
        "    { key: 'runtime', label: t('chainHealth.layer.runtime'), data: h.runtime.layer },\n    { key: 'upstream', label: t('chainHealth.layer.upstream'), data: h.upstream },",
        "    { key: 'runtime', label: t('chainHealth.layer.runtime'), data: h.runtime.layer },\n"
        "    { key: 'account', label: t('chainHealth.layer.account'), data: h.account },\n"
        "    { key: 'upstream', label: t('chainHealth.layer.upstream'), data: h.upstream },",
        "account layer card",
    )
    body = replace_once(
        body,
        '''          <p v-if="chainHealth?.provider" class="chain-health__provider">
            {{ chainHealth.provider.name }} · {{ chainHealth.provider.displayUrl }}
          </p>
''',
        '''          <p v-if="chainHealth?.provider" class="chain-health__provider">
            {{ chainHealth.provider.name }} · {{ chainHealth.provider.displayUrl }}
          </p>
          <p v-if="chainHealth?.diagnosis" class="chain-health__provider">
            {{ t('chainHealth.attribution') }}：{{ chainHealth.diagnosis.summary }}
          </p>
''',
        "attribution summary line",
    )
    body = replace_once(
        body,
        '''        <div class="chain-health__facts">
          <div v-for="layer in chainLayers" :key="`${layer.key}-facts`">
''',
        '''        <div class="chain-health__facts">
          <div>
            <strong>{{ t('chainHealth.attribution') }}</strong>
            <code>code={{ chainHealth.diagnosis.code }}</code>
            <code v-for="fact in chainHealth.diagnosis.facts" :key="`diagnosis-${fact}`">{{ fact }}</code>
          </div>
          <div v-for="layer in chainLayers" :key="`${layer.key}-facts`">
''',
        "attribution details",
    )
    save(rel, body)

# i18n: only three visible additions + version badge.
for rel, old_badge, new_badge, account_label, attribution_label in [
    (
        "frontend/src/i18n/zh.ts",
        '"compat.buildBadge": "Sub2API Grok Compat r36 · v2.4.5+36",',
        '"compat.buildBadge": "Sub2API Grok Compat r37 · v2.4.5+37",',
        "账号 / 配额",
        "故障归因",
    ),
    (
        "frontend/src/i18n/en.ts",
        '"compat.buildBadge": "Sub2API Grok Compat r36 · v2.4.5+36",',
        '"compat.buildBadge": "Sub2API Grok Compat r37 · v2.4.5+37",',
        "Account / quota",
        "Fault attribution",
    ),
]:
    body = load(rel)
    if MARKER in body:
        continue
    body = body.replace("// CAS-R36-SAFE-RECOVERY\n", "// CAS-R36-SAFE-RECOVERY\n// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n", 1)
    body = replace_once(body, old_badge, new_badge, f"{rel} badge")
    body = replace_once(
        body,
        '  "chainHealth.layer.upstream":',
        f'  "chainHealth.layer.account": "{account_label}",\n  "chainHealth.attribution": "{attribution_label}",\n  "chainHealth.layer.upstream":',
        f"{rel} quota labels",
    )
    save(rel, body)

print("r37 lightweight fault attribution + quota guard overlay: APPLIED")
