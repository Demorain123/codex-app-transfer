from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R35-REAL-UPSTREAM-HEALTH"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r35 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r35 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


def replace_function(body: str, signature: str, replacement: str, label: str) -> str:
    start = body.find(signature)
    if start < 0:
        raise SystemExit(f"r35 function anchor missing: {label}")
    brace = body.find("{", start)
    if brace < 0:
        raise SystemExit(f"r35 opening brace missing: {label}")
    depth = 0
    end = None
    in_string = False
    escape = False
    for idx in range(brace, len(body)):
        ch = body[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        raise SystemExit(f"r35 closing brace missing: {label}")
    return body[:start] + replacement.rstrip() + body[end:]


# ---------------------------------------------------------------------------
# Lifecycle telemetry: preserve raw upstream status separately from the
# client-facing status produced by an adapter. Never let protocol conversion
# erase a real 4xx/5xx result.
# ---------------------------------------------------------------------------
telemetry_rel = "crates/proxy/src/telemetry.rs"
telemetry = load(telemetry_rel)
if MARKER not in telemetry:
    telemetry = replace_once(
        telemetry,
        "    pub status: Option<u16>,\n    pub bytes: u64,",
        "    // CAS-R35-REAL-UPSTREAM-HEALTH\n"
        "    // `raw_upstream_status` is the final HTTP status returned by the actual\n"
        "    // provider/gateway before adapter conversion. `client_status` is what\n"
        "    // Codex receives after conversion (which may legitimately be 200 for a\n"
        "    // response.failed SSE). Keeping both prevents 503 -> 200 diagnostic loss.\n"
        "    pub raw_upstream_status: Option<u16>,\n"
        "    pub client_status: Option<u16>,\n"
        "    pub request_bytes: u64,\n"
        "    pub status: Option<u16>,\n"
        "    pub bytes: u64,",
        "lifecycle outcome fields",
    )
    telemetry = replace_once(
        telemetry,
        "        model: impl Into<String>,\n    ) -> u64 {",
        "        model: impl Into<String>,\n        request_bytes: u64,\n    ) -> u64 {",
        "lifecycle start request size",
    )
    telemetry = replace_once(
        telemetry,
        "            completed_at_ms: None,\n            status: None,\n            bytes: 0,",
        "            completed_at_ms: None,\n"
        "            raw_upstream_status: None,\n"
        "            client_status: None,\n"
        "            request_bytes,\n"
        "            status: None,\n"
        "            bytes: 0,",
        "lifecycle initialization",
    )
    telemetry = replace_once(
        telemetry,
        "    pub fn mark_headers(&self, id: u64, status: u16) {\n"
        "        self.update(id, |record| {\n"
        "            record.headers_at_ms.get_or_insert_with(Self::now_ms);\n"
        "            record.status = Some(status);\n"
        "        });\n"
        "    }",
        "    pub fn mark_headers(&self, id: u64, status: u16) {\n"
        "        self.update(id, |record| {\n"
        "            record.headers_at_ms.get_or_insert_with(Self::now_ms);\n"
        "            record.raw_upstream_status = Some(status);\n"
        "        });\n"
        "    }\n\n"
        "    pub fn mark_client_status(&self, id: u64, status: u16) {\n"
        "        self.update(id, |record| {\n"
        "            record.client_status = Some(status);\n"
        "            // Keep legacy `status` as the client-facing value for old\n"
        "            // diagnostic consumers; r35 health uses raw_upstream_status.\n"
        "            record.status = Some(status);\n"
        "        });\n"
        "    }",
        "raw/client status methods",
    )
    telemetry = replace_once(
        telemetry,
        "                record.status = Some(status);\n"
        "                record.bytes = bytes;\n"
        "                record.terminal = Some(\"completed\".to_owned());",
        "                record.client_status = Some(status);\n"
        "                record.status = Some(status);\n"
        "                record.bytes = bytes;\n"
        "                record.terminal = Some(\n"
        "                    if record.raw_upstream_status.is_some_and(|raw| raw >= 400) {\n"
        "                        \"upstream_error\"\n"
        "                    } else {\n"
        "                        \"completed\"\n"
        "                    }\n"
        "                    .to_owned(),\n"
        "                );",
        "terminal outcome uses raw status",
    )
    save(telemetry_rel, telemetry)

# ---------------------------------------------------------------------------
# Forwarder: mark raw status after all transparent retries, count top-level
# success/failure using that raw result, and separately record client status.
# ---------------------------------------------------------------------------
forward_rel = "crates/proxy/src/forward.rs"
forward = load(forward_rel)
if MARKER not in forward:
    forward = replace_once(
        forward,
        "        retry_runtime_diag_model.unwrap_or(\"<unknown>\").to_owned(),\n    );",
        "        retry_runtime_diag_model.unwrap_or(\"<unknown>\").to_owned(),\n"
        "        plan.body.len() as u64,\n"
        "    );",
        "lifecycle request size call",
    )

    raw_anchor = """    // QoderCosy:上游 SSE 每帧是 `{headers, body, statusCodeValue, statusCode}` 信封,body 是
"""
    raw_block = """    // CAS-R35-REAL-UPSTREAM-HEALTH: this is the FINAL raw provider result
    // after any transparent retry. Record it before adapters can translate a JSON
    // error into a client-facing HTTP 200 response.failed SSE.
    telemetry.lifecycles.mark_headers(lifecycle_id, status.as_u16());
    telemetry.stats.record(status.is_success());
    telemetry.logs.add(
        if status.is_success() { "SUCCESS" } else { "ERROR" },
        format!("upstream status {}", status.as_u16()),
    );

"""
    if raw_anchor not in forward:
        raise SystemExit("r35 anchor missing: final raw upstream status")
    forward = forward.replace(raw_anchor, raw_block + raw_anchor, 1)

    old_client = """    let success = response_plan.status.is_success();
    telemetry
        .lifecycles
        .mark_headers(lifecycle_id, response_plan.status.as_u16());
    telemetry.stats.record(success);
    telemetry.logs.add(
        if success { "SUCCESS" } else { "ERROR" },
        format!("upstream status {}", response_plan.status.as_u16()),
    );
    // CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT
    record_subagent_failure_chain_result_r26(
        subagent_failure_chain_ctx_r26.as_ref(),
        response_plan.status.as_u16(),
    );
"""
    new_client = """    let success = response_plan.status.is_success();
    telemetry
        .lifecycles
        .mark_client_status(lifecycle_id, response_plan.status.as_u16());
    telemetry.logs.add(
        if success { "INFO" } else { "ERROR" },
        format!("client response status {}", response_plan.status.as_u16()),
    );
    // CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT
    // The failure-chain diagnostic must use the real provider result, not an
    // adapter-generated HTTP 200 envelope.
    record_subagent_failure_chain_result_r26(
        subagent_failure_chain_ctx_r26.as_ref(),
        status.as_u16(),
    );
"""
    forward = replace_once(forward, old_client, new_client, "client/raw status split")

    # Transport failure has no HTTP response, but it is still an upstream failure
    # for the top cards. ForwardError::into_response will count the generic failure;
    # do not double-count here. Lifecycle keeps the stage.

    # Privacy hardening for routine proxy logs: preserve sizes and the upstream
    # error response preview, but never include a request-body/prompt preview.
    diag_replacement = r'''fn log_upstream_error_diag(
    telemetry: &crate::telemetry::ProxyTelemetry,
    status: StatusCode,
    upstream_url: &str,
    outbound_headers: &reqwest::header::HeaderMap,
    request_body: &Bytes,
    response_body: &Bytes,
) {
    // CAS-R35-REAL-UPSTREAM-HEALTH-LOG-PRIVACY
    // Error diagnostics often happen on the most sensitive requests. Keep only
    // request size; never persist prompt/tool/SSH contents in the routine log.
    const RESP_MAX: usize = 2048;
    let resp_snippet = bytes_preview(response_body, RESP_MAX);
    let headers_dump = format_headers_redacted(outbound_headers);
    telemetry.logs.add(
        "ERROR",
        format!(
            "upstream error diag {} {}\\
  → outbound headers: [{}]\\
  → request body: <redacted> ({} bytes)\\
  ← response body ({} bytes): {}",
            status.as_u16(),
            upstream_url,
            headers_dump,
            request_body.len(),
            response_body.len(),
            resp_snippet,
        ),
    );
}'''
    forward = replace_function(
        forward,
        "fn log_upstream_error_diag(",
        diag_replacement,
        "routine upstream error log privacy",
    )

    # Put a stable marker close to the forward handler changes.
    forward = forward.replace(
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH: start only after local diagnostic",
        "// CAS-R35-REAL-UPSTREAM-HEALTH\n"
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH: start only after local diagnostic",
        1,
    )
    save(forward_rel, forward)

# ---------------------------------------------------------------------------
# Health center: use structured lifecycle evidence instead of log ordering.
# This fixes the r34 early-return bug where a client-facing 200 masked a raw 503.
# ---------------------------------------------------------------------------
health_rel = "src-tauri/src/admin/handlers/chain_health.rs"
health = load(health_rel)
if MARKER not in health:
    health = health.replace(
        "//! CAS-R33-CHAIN-HEALTH",
        "//! CAS-R33-CHAIN-HEALTH\n//! CAS-R35-REAL-UPSTREAM-HEALTH",
        1,
    )

    # Session failures include a fully delivered response.failed error stream.
    health = replace_once(
        health,
        "            record\n                .terminal\n                .as_deref()\n                .is_some_and(|value| value.starts_with(\"failed:\"))",
        "            record\n"
        "                .terminal\n"
        "                .as_deref()\n"
        "                .is_some_and(|value| value.starts_with(\"failed:\") || value == \"upstream_error\")",
        "session raw upstream failure count",
    )

    # Add final outcome facts to Session / Turn without reading content.
    health = replace_once(
        health,
        "        .fact(format!(\"retry_recoveries={retry_recoveries}\"))\n"
        "        .fact(\"correlation=fingerprinted-no-prompt\")",
        "        .fact(format!(\"retry_recoveries={retry_recoveries}\"))\n"
        "        .fact(\n"
        "            recent.last().map(|record| {\n"
        "                format!(\n"
        "                    \"last_raw_status={} last_client_status={} request_bytes={}\",\n"
        "                    record.raw_upstream_status.map(|v| v.to_string()).unwrap_or_else(|| \"-\".into()),\n"
        "                    record.client_status.map(|v| v.to_string()).unwrap_or_else(|| \"-\".into()),\n"
        "                    record.request_bytes\n"
        "                )\n"
        "            }).unwrap_or_else(|| \"last_raw_status=- last_client_status=- request_bytes=0\".into())\n"
        "        )\n"
        "        .fact(\"correlation=fingerprinted-no-prompt\")",
        "session raw/client facts",
    )

    upstream_fn = r'''fn passive_upstream_layer() -> HealthLayer {
    let records = proxy_telemetry().lifecycles.snapshot();
    let Some(latest) = records.last() else {
        return HealthLayer::new(
            "idle",
            "upstream_no_requests",
            "尚无可用于判断账号池 / 上游的真实请求证据",
        )
        .fact("mode=passive-no-inference");
    };

    let now_ms = Local::now().timestamp_millis();
    let age_ms = now_ms.saturating_sub(latest.accepted_at_ms).max(0) as u64;
    let raw = latest.raw_upstream_status;
    let client = latest.client_status;

    // Correlate reconnect/retry attempts by the existing non-reversible request
    // fingerprint. Do not inspect prompt text or raw thread/session identifiers.
    let window_start = latest.accepted_at_ms.saturating_sub(15 * 60 * 1000);
    let mut failure_streak = 0usize;
    let mut cumulative_request_bytes = 0u64;
    let mut failure_sequence = Vec::new();
    for record in records.iter().rev() {
        if record.accepted_at_ms < window_start
            || record.correlation != latest.correlation
            || record.provider != latest.provider
            || record.model != latest.model
        {
            continue;
        }
        match record.raw_upstream_status {
            Some(status) if status >= 400 => {
                failure_streak += 1;
                cumulative_request_bytes = cumulative_request_bytes.saturating_add(record.request_bytes);
                failure_sequence.push(status.to_string());
            }
            Some(_) if failure_streak > 0 => break,
            _ => {}
        }
        if failure_streak >= 12 {
            break;
        }
    }
    failure_sequence.reverse();

    let base_facts = |mut layer: HealthLayer| {
        layer = layer
            .fact(format!("provider={} model={}", latest.provider, latest.model))
            .fact(format!(
                "raw_status={} client_status={}",
                raw.map(|v| v.to_string()).unwrap_or_else(|| "-".into()),
                client.map(|v| v.to_string()).unwrap_or_else(|| "-".into())
            ))
            .fact(format!("request_bytes={}", latest.request_bytes))
            .fact(format!("failure_streak={failure_streak}"))
            .fact(format!("retry_upload_bytes={cumulative_request_bytes}"))
            .fact(format!(
                "failure_sequence={}",
                if failure_sequence.is_empty() { "-".into() } else { failure_sequence.join(">") }
            ))
            .fact("evidence=structured-request-lifecycle");
        layer
    };

    if let Some(status) = raw {
        if status >= 400 {
            let (level, code, summary) = match status {
                401 | 403 => (
                    "error",
                    "upstream_auth_error",
                    "最近真实请求到达账号池 / 上游，但鉴权或权限失败",
                ),
                429 => (
                    "error",
                    "upstream_rate_limited",
                    "最近真实请求被账号池 / 上游限流或无可用额度",
                ),
                502 => (
                    "error",
                    "upstream_bad_gateway",
                    "Sub2API 已接收请求，但其后端账号 / 上游返回 502",
                ),
                503 => (
                    "error",
                    "upstream_service_unavailable",
                    "Sub2API 已接收请求，但账号池 / 最终上游暂时不可用（503）",
                ),
                504 => (
                    "error",
                    "upstream_gateway_timeout",
                    "Sub2API 已接收请求，但等待账号 / 最终上游超时（504）",
                ),
                500..=599 => (
                    "error",
                    "upstream_5xx",
                    "最近真实请求在网关后端 / 最终上游阶段失败",
                ),
                _ => (
                    "degraded",
                    "upstream_http_error",
                    "最近真实请求收到非成功 HTTP 状态",
                ),
            };
            return base_facts(HealthLayer::new(level, code, summary).latency(Some(age_ms)));
        }
    }

    if latest.terminal.is_none() {
        if latest.raw_upstream_status.is_none() {
            let since_forward = latest
                .forwarded_at_ms
                .map(|value| now_ms.saturating_sub(value).max(0) as u64)
                .unwrap_or(age_ms);
            let level = if since_forward >= 90_000 {
                "error"
            } else if since_forward >= 20_000 {
                "degraded"
            } else {
                "ok"
            };
            let code = if since_forward >= 90_000 {
                "upstream_headers_stalled"
            } else {
                "upstream_waiting_headers"
            };
            return base_facts(
                HealthLayer::new(level, code, "请求已转发，但尚未收到真实上游响应头")
                    .latency(Some(since_forward)),
            );
        }
        if latest.first_event_at_ms.is_none() {
            return base_facts(
                HealthLayer::new(
                    "degraded",
                    "upstream_waiting_first_event",
                    "真实上游已返回成功响应头，但尚未向 Codex 输出首个流事件",
                )
                .latency(Some(age_ms)),
            );
        }
        return base_facts(
            HealthLayer::new(
                "ok",
                "upstream_streaming",
                "真实上游已成功响应，当前流仍在进行",
            )
            .latency(Some(age_ms)),
        );
    }

    match latest.terminal.as_deref() {
        Some("completed") => base_facts(
            HealthLayer::new(
                "ok",
                "upstream_recent_complete",
                "最近真实请求已从账号池 / 上游成功完成",
            )
            .latency(Some(age_ms)),
        ),
        Some("cancelled") => base_facts(
            HealthLayer::new(
                "degraded",
                "upstream_client_cancelled",
                "最近请求在客户端消费完成前被取消",
            )
            .latency(Some(age_ms)),
        ),
        Some(value) if value.starts_with("failed:") => base_facts(
            HealthLayer::new(
                "error",
                "upstream_transport_failed",
                "最近请求在 Transfer 到上游的传输 / 转换阶段失败",
            )
            .fact(format!("terminal={value}"))
            .latency(Some(age_ms)),
        ),
        _ => base_facts(HealthLayer::new(
            "unknown",
            "upstream_evidence_incomplete",
            "真实请求已有结构化证据，但终止状态尚不能分类",
        )),
    }
}'''
    health = replace_function(
        health,
        "fn passive_upstream_layer() -> HealthLayer {",
        upstream_fn,
        "structured passive upstream layer",
    )

    # r34 MCP root attribution was too broad: every Electron ChatGPT child was a
    # root. Prefer the app-server codex.exe generation; only fall back to top-level
    # ChatGPT processes when no codex.exe exists.
    old_roots = r'''        let roots: HashSet<u32> = rows
            .iter()
            .filter(|row| {
                row.name.eq_ignore_ascii_case("chatgpt.exe")
                    || row.name.eq_ignore_ascii_case("codex.exe")
            })
            .map(|row| row.pid)
            .collect();
'''
    new_roots = r'''        let codex_roots: HashSet<u32> = rows
            .iter()
            .filter(|row| row.name.eq_ignore_ascii_case("codex.exe"))
            .map(|row| row.pid)
            .collect();
        let roots: HashSet<u32> = if !codex_roots.is_empty() {
            codex_roots
        } else {
            let chatgpt_ids: HashSet<u32> = rows
                .iter()
                .filter(|row| row.name.eq_ignore_ascii_case("chatgpt.exe"))
                .map(|row| row.pid)
                .collect();
            rows.iter()
                .filter(|row| {
                    row.name.eq_ignore_ascii_case("chatgpt.exe")
                        && !chatgpt_ids.contains(&row.parent_pid)
                })
                .map(|row| row.pid)
                .collect()
        };
'''
    health = replace_once(health, old_roots, new_roots, "MCP root attribution")

    # Recommendations for specific real upstream outcomes.
    health = replace_once(
        health,
        '        "upstream_rate_limited" => out.push("最近真实请求被限流，检查账号配额与网关调度策略。".into()),\n'
        '        "upstream_5xx" => out.push("最近真实请求收到 5xx，可结合网关日志确认是网关还是最终上游。".into()),',
        '        "upstream_rate_limited" => out.push(\n'
        '            "最近真实请求收到 429：先检查 Sub2API 当前分组的可用账号、额度/冷却和账号池重试策略；不要让 Codex 高频连续重试。".into(),\n'
        '        ),\n'
        '        "upstream_bad_gateway" | "upstream_service_unavailable" | "upstream_gateway_timeout" | "upstream_5xx" => out.push(\n'
        '            "本机 Transfer、8113 和 Docker 可正常时，5xx 表示故障已在 Sub2API 后端账号池/真正上游；优先检查账号可用数、冷却/封禁、上游错误和 Sub2API 版本。".into(),\n'
        '        ),',
        "upstream recommendations",
    )
    save(health_rel, health)

# ---------------------------------------------------------------------------
# UI wording: make it explicit that the last card covers the scheduler/account
# pool and real upstream, not merely endpoint reachability.
# ---------------------------------------------------------------------------
for rel, old, new in [
    (
        "frontend/src/i18n/zh.ts",
        '"chainHealth.layer.upstream": \'上游(被动)\'',
        '"chainHealth.layer.upstream": \'账号池 / 上游（被动）\'',
    ),
    (
        "frontend/src/i18n/en.ts",
        '"chainHealth.layer.upstream": \'Upstream (passive)\'',
        '"chainHealth.layer.upstream": \'Account pool / Upstream (passive)\'',
    ),
]:
    body = load(rel)
    if MARKER not in body:
        if old not in body:
            raise SystemExit(f"r35 i18n anchor missing: {rel}")
        body = body.replace(old, new, 1)
        body = body.replace("// Auto-extracted", f"// {MARKER}\n// Auto-extracted", 1)
        save(rel, body)

print("r35 real upstream health overlay: APPLIED")
