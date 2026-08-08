from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R38-MODEL-ROUTE-OBSERVABILITY"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r38 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


rel = "src-tauri/src/admin/handlers/chain_health.rs"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        "//! CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n//! CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "struct ChainHealthSnapshot {\n",
        r'''// CAS-R38-MODEL-ROUTE-OBSERVABILITY
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ModelRouteHealth {
    provider: String,
    model: String,
    status: String,
    code: String,
    summary: String,
    age_ms: u64,
    raw_status: Option<u16>,
    request_bytes: u64,
    request_kind: Option<String>,
    tool_count: u32,
    duplicate_tool_names: Vec<String>,
    input_image_count: u32,
    successes: usize,
    failures: usize,
}

struct ChainHealthSnapshot {
''',
        "model route struct",
    )
    body = replace_once(
        body,
        "    diagnosis: HealthLayer,\n    recommendations: Vec<String>,",
        "    diagnosis: HealthLayer,\n"
        "    model_routes: Vec<ModelRouteHealth>,\n"
        "    recommendations: Vec<String>,",
        "snapshot model routes field",
    )
    body = replace_once(
        body,
        "    let upstream = passive_upstream_layer();\n    let account = account_pool_layer_r37(&upstream);\n    let diagnosis = fault_attribution_layer_r37(&session, &account, &upstream);",
        "    let upstream = passive_upstream_layer();\n"
        "    let account = account_pool_layer_r37(&upstream);\n"
        "    let model_routes = model_routes_r38();\n"
        "    let diagnosis = fault_attribution_layer_r38(&session, &account, &upstream, &model_routes);",
        "snapshot model route composition",
    )
    old_overall = '''    let overall = overall_status([
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
    let overall_summary = if !matches!(diagnosis.code.as_str(), "fault_none" | "fault_no_evidence")
    {
        format!("最可能故障归因：{}", diagnosis.summary)
    } else {
        match overall.as_str() {
            "error" => "链路存在明确故障，展开建议可查看最可能的阻断层".to_owned(),
            "degraded" => "链路可用性下降或有请求等待，需要继续观察".to_owned(),
            "ok" => "轻量诊断未发现明确故障".to_owned(),
            _ => "当前证据不足，等待一次真实请求后可获得更多被动证据".to_owned(),
        }
    };
'''
    new_overall = '''    // CAS-R38-MODEL-ROUTE-OBSERVABILITY: MCP process hygiene is important but
    // is not itself proof that the inference route is down. Compute core availability
    // without MCP, then surface MCP explosion as degraded maintenance state.
    let core_overall = overall_status([
        &codex,
        &session,
        &transfer,
        &gateway,
        &runtime.layer,
        &account,
        &upstream,
        &diagnosis,
    ]);
    let latest_route_ok = model_routes.first().is_some_and(|route| route.status == "ok");
    let overall = if latest_route_ok && core_overall == "error" && matches!(diagnosis.code.as_str(), "fault_none" | "fault_recovered_session") {
        "degraded".to_owned()
    } else if latest_route_ok && core_overall == "ok" && mcp.status == "error" {
        "degraded".to_owned()
    } else {
        core_overall
    };
    let overall_summary = if diagnosis.code == "fault_recovered_session" {
        "最新真实模型请求已恢复成功；历史失败仍保留为会话级证据".to_owned()
    } else if !matches!(diagnosis.code.as_str(), "fault_none" | "fault_no_evidence") {
        format!("最可能故障归因：{}", diagnosis.summary)
    } else if latest_route_ok && mcp.status == "error" {
        "核心模型链路当前可用；MCP/helper 进程异常作为维护告警单独处理".to_owned()
    } else {
        match overall.as_str() {
            "error" => "链路存在明确故障，展开建议可查看最可能的阻断层".to_owned(),
            "degraded" => "链路可用性下降或有请求等待，需要继续观察".to_owned(),
            "ok" => "轻量诊断未发现明确故障".to_owned(),
            _ => "当前证据不足，等待一次真实请求后可获得更多被动证据".to_owned(),
        }
    };
'''
    body = replace_once(body, old_overall, new_overall, "overall route/mcp separation")
    body = replace_once(
        body,
        "        diagnosis,\n        recommendations,",
        "        diagnosis,\n        model_routes,\n        recommendations,",
        "snapshot model routes assignment",
    )
    body = replace_once(
        body,
        '            "会话关联只保存不可逆短指纹与阶段时间，不读取消息正文".into(),\n',
        '            "会话关联只保存不可逆短指纹与阶段时间，不读取消息正文".into(),\n'
        '            "请求形态诊断只保留 request kind、大小、tool 名称/数量与图片项数量；不保存 prompt、tool 参数/schema 或图片内容".into(),\n',
        "privacy request shape fact",
    )

    anchor = "fn fault_attribution_layer_r37(\n"
    helper = r'''// CAS-R38-MODEL-ROUTE-OBSERVABILITY
fn model_routes_r38() -> Vec<ModelRouteHealth> {
    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let cutoff = now_ms.saturating_sub(30 * 60 * 1000);
    let mut keys = Vec::<(String, String)>::new();
    for record in records.iter().rev() {
        if record.accepted_at_ms < cutoff {
            continue;
        }
        let key = (record.provider.clone(), record.model.clone());
        if !keys.contains(&key) {
            keys.push(key);
        }
        if keys.len() >= 6 {
            break;
        }
    }
    keys.into_iter()
        .filter_map(|(provider, model)| {
            let relevant: Vec<_> = records
                .iter()
                .filter(|record| {
                    record.accepted_at_ms >= cutoff
                        && record.provider == provider
                        && record.model == model
                })
                .collect();
            let latest = relevant.last().copied()?;
            let successes = relevant
                .iter()
                .filter(|record| {
                    record.raw_upstream_status.is_some_and(|status| status < 400)
                        && record.terminal.as_deref() == Some("completed")
                })
                .count();
            let failures = relevant
                .iter()
                .filter(|record| {
                    record.raw_upstream_status.is_some_and(|status| status >= 400)
                        || record
                            .terminal
                            .as_deref()
                            .is_some_and(|value| value == "upstream_error" || value.starts_with("failed:"))
                })
                .count();
            let had_earlier_failure = relevant.iter().any(|record| {
                record.accepted_at_ms < latest.accepted_at_ms
                    && (record.raw_upstream_status.is_some_and(|status| status >= 400)
                        || record
                            .terminal
                            .as_deref()
                            .is_some_and(|value| value == "upstream_error" || value.starts_with("failed:")))
            });
            let latest_success = latest.raw_upstream_status.is_some_and(|status| status < 400)
                && latest.terminal.as_deref() == Some("completed");
            let (status, code, summary) = if latest_success && had_earlier_failure {
                ("ok", "model_recovered", "最新真实请求已成功，较早失败已恢复")
            } else if latest_success {
                ("ok", "model_healthy", "最新真实请求已成功完成")
            } else if !latest.duplicate_tool_names.is_empty() && latest.raw_upstream_status.is_some_and(|status| status >= 400) {
                ("error", "model_duplicate_tool_schema", "失败请求包含重复工具名称")
            } else if latest.request_bytes >= R37_LARGE_CONTEXT_BYTES && latest.raw_upstream_status.is_some_and(|status| status >= 400) {
                ("error", "model_large_context", "失败请求处于大型上下文/历史负载区间")
            } else if latest.raw_upstream_status.is_some_and(|status| status >= 400) {
                ("error", "model_upstream_failed", "最新真实请求收到上游失败状态")
            } else if latest.terminal.is_none() {
                ("degraded", "model_in_flight", "最新真实请求仍在进行")
            } else if latest.terminal.as_deref() == Some("cancelled") {
                ("degraded", "model_cancelled", "最新真实请求被客户端取消")
            } else {
                ("unknown", "model_unknown", "当前模型路径证据不足")
            };
            Some(ModelRouteHealth {
                provider,
                model,
                status: status.into(),
                code: code.into(),
                summary: summary.into(),
                age_ms: now_ms.saturating_sub(latest.accepted_at_ms).max(0) as u64,
                raw_status: latest.raw_upstream_status,
                request_bytes: latest.request_bytes,
                request_kind: latest.request_kind.clone(),
                tool_count: latest.tool_count,
                duplicate_tool_names: latest.duplicate_tool_names.clone(),
                input_image_count: latest.input_image_count,
                successes,
                failures,
            })
        })
        .collect()
}

fn fault_attribution_layer_r38(
    session: &HealthLayer,
    account: &HealthLayer,
    upstream: &HealthLayer,
    model_routes: &[ModelRouteHealth],
) -> HealthLayer {
    if let Some(route) = model_routes.first() {
        if route.code == "model_duplicate_tool_schema" {
            return HealthLayer::new(
                "error",
                "fault_duplicate_tool_schema",
                "请求工具定义存在同名冲突，优先修复 tool schema 而不是重启基础设施",
            )
            .fact(format!("model={} provider={}", route.model, route.provider))
            .fact(format!("duplicate_tools={}", route.duplicate_tool_names.join(",")))
            .fact(format!("request_bytes={}", route.request_bytes));
        }
        if route.code == "model_large_context" {
            return HealthLayer::new(
                "error",
                "fault_large_context",
                "当前模型失败与大型旧会话/历史负载高度相关，优先新建或 fork 会话验证",
            )
            .fact(format!("model={} provider={}", route.model, route.provider))
            .fact(format!("request_bytes={}", route.request_bytes))
            .fact(format!("input_image_count={}", route.input_image_count));
        }
        if route.code == "model_recovered" {
            return HealthLayer::new(
                "degraded",
                "fault_recovered_session",
                "最新真实请求已恢复；先前故障更像旧 thread/session 或大型历史上下文",
            )
            .fact(format!("model={} provider={}", route.model, route.provider))
            .fact(format!("successes={} failures={}", route.successes, route.failures));
        }
    }
    fault_attribution_layer_r37(session, account, upstream)
}

'''
    body = replace_once(body, anchor, helper + anchor, "r38 model routes helpers")

    body = body.replace(
        '"fault_session_scoped" | "fault_session_state" | "fault_compaction_context"',
        '"fault_session_scoped" | "fault_session_state" | "fault_compaction_context" | "fault_large_context" | "fault_duplicate_tool_schema" | "fault_recovered_session"',
        1,
    )
    body = replace_once(
        body,
        '''        "upstream_backend_failure" => {
            actions.push(recover_transfer(&state, &before, true).await);
            actions.push(RecoveryAction::skipped(
                "restart_healthy_sub2api",
                "网关/容器健康且真实请求已到达上游；不自动重启 healthy Sub2API，避免版本/容器抖动。下一步应检查账号池、模型冷却和真实上游错误",
            ));
            needs_real_request_verification = true;
        }
''',
        '''        "upstream_backend_failure" => {
            // CAS-R38-MODEL-ROUTE-OBSERVABILITY: an upstream 4xx/5xx with a healthy
            // listener/gateway is not evidence that Transfer needs recycling.
            if before.transfer.status != "ok" {
                actions.push(recover_transfer(&state, &before, false).await);
            } else {
                actions.push(RecoveryAction::skipped(
                    "refresh_healthy_transfer",
                    "Transfer 正常监听且请求已到达网关；本次不再盲目刷新 180xx listener",
                ));
            }
            actions.push(RecoveryAction::skipped(
                "restart_healthy_sub2api",
                "网关/容器健康且真实请求已到达上游；不自动重启 healthy Sub2API。优先依据模型路径/请求形态继续定位",
            ));
            needs_real_request_verification = true;
        }
''',
        "upstream recovery no blind transfer refresh",
    )
    save(rel, body)

print("r38 health model routes: COMPLETE")
