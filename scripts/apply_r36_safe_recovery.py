from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R36-SAFE-RECOVERY"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r36 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r36 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Backend: explicit, rate-limited, non-destructive recovery endpoint.
# ---------------------------------------------------------------------------
rel = "src-tauri/src/admin/handlers/chain_health.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "//! CAS-R35-REAL-UPSTREAM-HEALTH\n",
        "//! CAS-R35-REAL-UPSTREAM-HEALTH\n//! CAS-R36-SAFE-RECOVERY\n",
        "module marker",
    )
    body = replace_once(
        body,
        "const MAX_CONTAINERS: usize = 12;\n",
        "const MAX_CONTAINERS: usize = 12;\n"
        "const RECOVERY_COOLDOWN: Duration = Duration::from_secs(45);\n"
        "const RECOVERY_COMMAND_TIMEOUT: Duration = Duration::from_secs(12);\n",
        "recovery constants",
    )

    insert_after = '''static CACHE: OnceLock<Mutex<Option<CachedSnapshot>>> = OnceLock::new();

fn cache() -> &'static Mutex<Option<CachedSnapshot>> {
    CACHE.get_or_init(|| Mutex::new(None))
}
'''
    recovery_state = '''static CACHE: OnceLock<Mutex<Option<CachedSnapshot>>> = OnceLock::new();

fn cache() -> &'static Mutex<Option<CachedSnapshot>> {
    CACHE.get_or_init(|| Mutex::new(None))
}

// CAS-R36-SAFE-RECOVERY: explicit user-triggered recovery only. The cooldown
// prevents repeated clicks or UI retries from turning a transient upstream fault
// into a restart loop.
static RECOVERY_LAST: OnceLock<Mutex<Option<Instant>>> = OnceLock::new();

fn recovery_last() -> &'static Mutex<Option<Instant>> {
    RECOVERY_LAST.get_or_init(|| Mutex::new(None))
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoveryAction {
    action: String,
    status: String,
    detail: String,
}

impl RecoveryAction {
    fn performed(action: &str, detail: impl Into<String>) -> Self {
        Self { action: action.into(), status: "performed".into(), detail: detail.into() }
    }

    fn skipped(action: &str, detail: impl Into<String>) -> Self {
        Self { action: action.into(), status: "skipped".into(), detail: detail.into() }
    }

    fn failed(action: &str, detail: impl Into<String>) -> Self {
        Self { action: action.into(), status: "failed".into(), detail: detail.into() }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ChainRecoveryReport {
    attempted_at: String,
    classification: String,
    actions: Vec<RecoveryAction>,
    needs_real_request_verification: bool,
    before_overall: String,
    after_overall: String,
    after_summary: String,
}
'''
    body = replace_once(body, insert_after, recovery_state, "recovery state")

    handler_anchor = '''pub async fn chain_health(
    State(state): State<AdminState>,
    Query(query): Query<ChainHealthQuery>,
) -> impl IntoResponse {
'''
    recovery_handler = r'''// CAS-R36-SAFE-RECOVERY-HANDLER
pub async fn recover_chain(State(state): State<AdminState>) -> impl IntoResponse {
    {
        let mut gate = recovery_last().lock().await;
        if let Some(previous) = *gate {
            let elapsed = previous.elapsed();
            if elapsed < RECOVERY_COOLDOWN {
                let retry_after_ms = (RECOVERY_COOLDOWN - elapsed).as_millis() as u64;
                return Json(json!({
                    "success": false,
                    "error": "recovery_cooldown",
                    "retryAfterMs": retry_after_ms,
                }));
            }
        }
        *gate = Some(Instant::now());
    }

    let before = build_snapshot(&state).await;
    let classification = recovery_classification(&before).to_owned();
    let mut actions = Vec::new();
    let mut needs_real_request_verification = false;

    match classification.as_str() {
        "transfer_stopped" => {
            actions.push(recover_transfer(&state, &before, false).await);
        }
        "gateway_unreachable" | "docker_target_failed" => {
            if let Some(target) = before.runtime.containers.iter().find(|item| item.target) {
                // Restart only when there is concrete local evidence that the target
                // container is not serving correctly. Healthy containers are never
                // restarted merely because the model upstream returned 5xx.
                let should_restart = !target.running
                    || target.restarting
                    || target.health.as_deref() == Some("unhealthy")
                    || matches!(before.gateway.code.as_str(), "gateway_tcp_refused" | "gateway_http_connect_error" | "gateway_http_timeout");
                if should_restart {
                    let result = run_command(
                        "docker",
                        &["restart".into(), target.id.clone()],
                        RECOVERY_COMMAND_TIMEOUT,
                    )
                    .await;
                    if matches!(result.kind, CommandKind::Ok) {
                        actions.push(RecoveryAction::performed(
                            "restart_gateway_container",
                            format!("已重启目标容器 {}；未修改卷、数据库或账号配置", target.name),
                        ));
                        tokio::time::sleep(Duration::from_secs(2)).await;
                    } else {
                        actions.push(RecoveryAction::failed(
                            "restart_gateway_container",
                            format!("Docker restart 失败: {}", result.stderr),
                        ));
                    }
                } else {
                    actions.push(RecoveryAction::skipped(
                        "restart_gateway_container",
                        "目标容器仍为 healthy/running，没有证据支持自动重启",
                    ));
                }
            } else {
                actions.push(RecoveryAction::skipped(
                    "restart_gateway_container",
                    "未识别到承载活动端口的本地容器",
                ));
            }
            actions.push(recover_transfer(&state, &before, true).await);
        }
        "upstream_rate_limited" => {
            actions.push(RecoveryAction::skipped(
                "restart_gateway_container",
                "429 属于上游/账号额度或冷却；重启健康容器通常无效，已避免制造重启循环",
            ));
            actions.push(RecoveryAction::skipped(
                "retry_immediately",
                "建议等待账号池冷却后再发真实请求；恢复器不会自动制造额外模型请求",
            ));
            needs_real_request_verification = true;
        }
        "upstream_backend_failure" => {
            actions.push(recover_transfer(&state, &before, true).await);
            actions.push(RecoveryAction::skipped(
                "restart_healthy_sub2api",
                "网关/容器健康且真实请求已到达上游；不自动重启 healthy Sub2API，避免版本/容器抖动。下一步应检查账号池、模型冷却和真实上游错误",
            ));
            needs_real_request_verification = true;
        }
        "healthy_or_no_evidence" => {
            actions.push(RecoveryAction::skipped(
                "no_mutation",
                "当前没有足够故障证据，未执行重启或配置修改",
            ));
        }
        _ => {
            actions.push(RecoveryAction::skipped(
                "no_safe_automatic_action",
                "检测到异常，但没有足够证据支持安全自动修复；已保留现场等待日志分析",
            ));
        }
    }

    *cache().lock().await = None;
    let after = build_snapshot(&state).await;
    Json(json!({
        "success": true,
        "recovery": ChainRecoveryReport {
            attempted_at: Local::now().to_rfc3339(),
            classification,
            actions,
            needs_real_request_verification,
            before_overall: before.overall,
            after_overall: after.overall.clone(),
            after_summary: after.overall_summary.clone(),
        },
        "health": after,
    }))
}

fn recovery_classification(snapshot: &ChainHealthSnapshot) -> &'static str {
    if snapshot.transfer.code == "transfer_stopped" {
        return "transfer_stopped";
    }
    if snapshot.runtime.layer.code == "docker_stack_failed" {
        return "docker_target_failed";
    }
    if matches!(
        snapshot.gateway.code.as_str(),
        "gateway_dns_failed"
            | "gateway_dns_timeout"
            | "gateway_dns_empty"
            | "gateway_tcp_timeout"
            | "gateway_tcp_refused"
            | "gateway_http_timeout"
            | "gateway_http_connect_error"
            | "gateway_http_5xx"
    ) {
        return "gateway_unreachable";
    }
    if snapshot.upstream.code == "upstream_rate_limited" {
        return "upstream_rate_limited";
    }
    if matches!(
        snapshot.upstream.code.as_str(),
        "upstream_bad_gateway"
            | "upstream_service_unavailable"
            | "upstream_gateway_timeout"
            | "upstream_5xx"
            | "upstream_transport_failed"
    ) {
        return "upstream_backend_failure";
    }
    if snapshot.overall == "ok" || snapshot.overall == "idle" || snapshot.overall == "unknown" {
        return "healthy_or_no_evidence";
    }
    "no_safe_automatic_action"
}

async fn recover_transfer(
    state: &AdminState,
    snapshot: &ChainHealthSnapshot,
    force_refresh: bool,
) -> RecoveryAction {
    let cfg = load_registry().unwrap_or_else(|_| json!({}));
    let port = super::proxy::read_proxy_port(&cfg);
    if force_refresh && state.proxy_manager.status().running {
        state.proxy_manager.stop_silent();
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
    let result = if let Some(provider) = snapshot.provider.as_ref() {
        super::proxy::start_proxy_for_provider_if_needed(&state.proxy_manager, port, &provider.id).await
    } else {
        super::proxy::start_proxy_if_needed(&state.proxy_manager, port).await
    };
    match result {
        Ok(changed) => RecoveryAction::performed(
            if force_refresh { "refresh_transfer" } else { "start_transfer" },
            if changed {
                format!("Transfer 已在端口 {port} 重新建立监听/解析器快照")
            } else {
                format!("Transfer 已在端口 {port} 正常运行，无需重复启动")
            },
        ),
        Err(error) => RecoveryAction::failed(
            if force_refresh { "refresh_transfer" } else { "start_transfer" },
            compact_error(&error),
        ),
    }
}

'''
    body = replace_once(body, handler_anchor, recovery_handler + handler_anchor, "recovery handler")
    save(rel, body)

# Route registration.
rel = "src-tauri/src/admin/mod.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        '''        .route(
            "/api/chain-health",
            get(handlers::chain_health::chain_health),
        )
''',
        '''        .route(
            "/api/chain-health",
            get(handlers::chain_health::chain_health),
        )
        // CAS-R36-SAFE-RECOVERY: explicit, rate-limited and non-destructive recovery.
        .route(
            "/api/chain-health/recover",
            post(handlers::chain_health::recover_chain),
        )
''',
        "recovery route",
    )
    save(rel, body)

# Frontend API types and call.
rel = "frontend/src/api/chainHealth.ts"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH\n",
        "// CAS-R34-RUNTIME-BEHAVIOR-HEALTH\n// CAS-R36-SAFE-RECOVERY\n",
        "frontend marker",
    )
    body += '''\n\nexport interface ChainRecoveryAction {\n  action: string\n  status: 'performed' | 'skipped' | 'failed'\n  detail: string\n}\n\nexport interface ChainRecoveryReport {\n  attemptedAt: string\n  classification: string\n  actions: ChainRecoveryAction[]\n  needsRealRequestVerification: boolean\n  beforeOverall: ChainHealthStatus\n  afterOverall: ChainHealthStatus\n  afterSummary: string\n}\n\nexport async function recoverChainHealth(): Promise<{ recovery: ChainRecoveryReport; health: ChainHealthSnapshot }> {\n  const result = await api<{ success: boolean; recovery: ChainRecoveryReport; health: ChainHealthSnapshot; error?: string; retryAfterMs?: number }>(\n    'POST',\n    '/api/chain-health/recover',\n  )\n  return { recovery: result.recovery, health: result.health }\n}\n'''
    save(rel, body)

# UI button + report.
rel = "frontend/src/pages/ProxyPage.vue"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "import { getChainHealth, type ChainHealthSnapshot, type ChainHealthStatus } from '@/api/chainHealth'\n",
        "import {\n  getChainHealth,\n  recoverChainHealth,\n  type ChainHealthSnapshot,\n  type ChainHealthStatus,\n  type ChainRecoveryReport,\n} from '@/api/chainHealth'\n",
        "frontend recovery import",
    )
    body = replace_once(
        body,
        "import IconChevronDown from '~icons/lucide/chevron-down'\n",
        "import IconChevronDown from '~icons/lucide/chevron-down'\nimport IconWrench from '~icons/lucide/wrench'\n",
        "recovery icon",
    )
    body = replace_once(
        body,
        "const chainExpanded = ref(false)\n",
        "const chainExpanded = ref(false)\nconst chainRecovering = ref(false)\nconst chainRecovery = ref<ChainRecoveryReport | null>(null)\n",
        "recovery refs",
    )
    body = replace_once(
        body,
        '''async function loadChainHealth(force = false) {
  if (chainLoading.value) return
  chainLoading.value = true
  try {
    chainHealth.value = await getChainHealth(force)
  } catch (e) {
    if (force) toast((e as Error).message || t('chainHealth.loadFailed'), 'error')
  } finally {
    chainLoading.value = false
  }
}
''',
        '''async function loadChainHealth(force = false) {
  if (chainLoading.value) return
  chainLoading.value = true
  try {
    chainHealth.value = await getChainHealth(force)
  } catch (e) {
    if (force) toast((e as Error).message || t('chainHealth.loadFailed'), 'error')
  } finally {
    chainLoading.value = false
  }
}

// CAS-R36-SAFE-RECOVERY: only runs after an explicit click. No model inference
// request is generated by the recovery path.
async function onRecoverChain() {
  if (chainRecovering.value) return
  chainRecovering.value = true
  try {
    const result = await recoverChainHealth()
    chainRecovery.value = result.recovery
    chainHealth.value = result.health
    toast(t('chainHealth.recoveryComplete'), 'info')
  } catch (e) {
    toast((e as Error).message || t('chainHealth.recoveryFailed'), 'error')
  } finally {
    chainRecovering.value = false
  }
}
''',
        "recovery action",
    )
    body = replace_once(
        body,
        '''        <div class="chain-health__actions">
          <button class="chain-health__button" :disabled="chainLoading" @click="loadChainHealth(true)">
''',
        '''        <div class="chain-health__actions">
          <button
            class="chain-health__button chain-health__button--repair"
            :disabled="chainRecovering"
            @click="onRecoverChain"
          >
            <IconWrench :class="{ 'is-spinning': chainRecovering }" />
            {{ t('chainHealth.recover') }}
          </button>
          <button class="chain-health__button" :disabled="chainLoading" @click="loadChainHealth(true)">
''',
        "recovery button",
    )
    body = replace_once(
        body,
        '''      <div v-if="chainHealth?.recommendations?.length" class="chain-health__recommendations">
''',
        '''      <div v-if="chainRecovery" class="chain-health__recovery-report">
        <strong>{{ t('chainHealth.recoveryReport') }}</strong>
        <span>{{ chainRecovery.classification }}</span>
        <ul>
          <li v-for="action in chainRecovery.actions" :key="`${action.action}-${action.detail}`">
            <code>{{ action.status }}</code>
            <span>{{ action.detail }}</span>
          </li>
        </ul>
        <small v-if="chainRecovery.needsRealRequestVerification">
          {{ t('chainHealth.recoveryNeedsRequest') }}
        </small>
      </div>

      <div v-if="chainHealth?.recommendations?.length" class="chain-health__recommendations">
''',
        "recovery report",
    )
    # Reuse existing visual language; minimal scoped CSS appended before style close.
    body = replace_once(
        body,
        "</style>\n",
        '''\n.chain-health__recovery-report {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-soft, rgba(127, 127, 127, 0.06));
  font-size: var(--fs-sm);
}
.chain-health__recovery-report ul {
  margin: 0;
  padding-left: 18px;
}
.chain-health__recovery-report li {
  margin: 4px 0;
}
.chain-health__recovery-report code {
  margin-right: 8px;
}
</style>\n''',
        "recovery CSS",
    )
    # Stable marker in source.
    body = body.replace("// CAS-R33-CHAIN-HEALTH\n", "// CAS-R33-CHAIN-HEALTH\n// CAS-R36-SAFE-RECOVERY\n", 1)
    save(rel, body)

# i18n.
for rel, anchor, insertion in [
    (
        "frontend/src/i18n/zh.ts",
        "\"chainHealth.refresh\": '立即检查',",
        "'chainHealth.refresh': '立即检查',\n  'chainHealth.recover': '尝试恢复',\n  'chainHealth.recoveryComplete': '安全恢复动作已执行',\n  'chainHealth.recoveryFailed': '恢复动作失败',\n  'chainHealth.recoveryReport': '恢复结果',\n  'chainHealth.recoveryNeedsRequest': '需要下一次真实请求验证账号池 / 上游是否已经恢复。',",
    ),
    (
        "frontend/src/i18n/en.ts",
        "\"chainHealth.refresh\": 'Check now',",
        "'chainHealth.refresh': 'Check now',\n  'chainHealth.recover': 'Try recovery',\n  'chainHealth.recoveryComplete': 'Safe recovery actions completed',\n  'chainHealth.recoveryFailed': 'Recovery action failed',\n  'chainHealth.recoveryReport': 'Recovery result',\n  'chainHealth.recoveryNeedsRequest': 'The next real request is required to verify account-pool/upstream recovery.',",
    ),
]:
    text = load(rel)
    if MARKER not in text:
        if anchor not in text:
            raise SystemExit(f"r36 i18n anchor missing: {rel}")
        text = text.replace(anchor, insertion, 1)
        text = "// CAS-R36-SAFE-RECOVERY\n" + text
        save(rel, text)

print("r36 safe recovery overlay: APPLIED")
