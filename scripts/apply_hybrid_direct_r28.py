from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"r28 patched {rel}")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r28 {label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1. Dedicated safety helper. Keep the policy in one small module so future
# upstream rebases have a narrow, reviewable boundary.
# ---------------------------------------------------------------------------
helper_template = read("scripts/hybrid_direct_r28.rs")
write("src-tauri/src/admin/services/desktop/hybrid_direct.rs", helper_template)

path = "src-tauri/src/admin/services/desktop/mod.rs"
text = read(path)
module_line = "pub mod hybrid_direct; // CAS-HYBRID-DIRECT-R28\n"
if module_line not in text:
    anchor = "pub mod no_micro;\n"
    text = replace_once(text, anchor, module_line + anchor, label="desktop module registration")
write(path, text)

# ---------------------------------------------------------------------------
# 2. Proxy lifecycle: r27 correctly reuses a same-port listener, but the resolver
# snapshot also contains activeProvider. In Hybrid Direct, changing Transfer's
# active provider must restart the proxy even on the same port, otherwise requests
# keep hitting the old upstream. Reuse requires BOTH port and provider identity.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/handlers/proxy.rs"
text = read(path)
if "CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH" not in text:
    start = text.find("pub(crate) async fn start_proxy_if_needed(\n")
    end_marker = "\n#[cfg(test)]\nmod proxy_lifecycle_r27_tests"
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("r28 proxy provider-refresh: r27 lifecycle function/test anchor missing")
    replacement = r'''// CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH
async fn start_proxy_r28_inner(
    manager: &ProxyManager,
    port: u16,
    expected_provider: Option<&str>,
) -> Result<bool, String> {
    let _lifecycle = PROXY_LIFECYCLE_R27.lock().await;
    let status = manager.status();
    let current_port = proxy_status_port(status.addr.as_deref());
    let provider_matches = expected_provider
        .map(|expected| status.active_provider.as_deref() == Some(expected))
        .unwrap_or(true);

    if status.running {
        // r27 same-port reuse remains valid only when the resolver snapshot also
        // belongs to the requested provider. Port 0 still means any bound port.
        if (port == 0 || current_port == Some(port)) && provider_matches {
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[proxy-lifecycle-r28] reuse listener requested_port={port} actual_port={} provider={}",
                    current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned()),
                    status.active_provider.as_deref().unwrap_or("none")
                ),
            );
            return Ok(false);
        }
        proxy_telemetry().logs.add(
            "INFO",
            format!(
                "[proxy-lifecycle-r28] reload listener old_port={} new_port={port} old_provider={} new_provider={}",
                current_port.map(|p| p.to_string()).unwrap_or_else(|| "unknown".to_owned()),
                status.active_provider.as_deref().unwrap_or("none"),
                expected_provider.unwrap_or("unchanged")
            ),
        );
        manager.stop_silent();
    }

    const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];
    for attempt in 0..=RETRY_MS.len() {
        match manager.start(port).await {
            Ok(_) => return Ok(true),
            Err(message) if proxy_bind_address_in_use(&message) && attempt < RETRY_MS.len() => {
                let delay = RETRY_MS[attempt];
                proxy_telemetry().logs.add(
                    "WARN",
                    format!(
                        "[proxy-lifecycle-r28] bind busy requested_port={port} retry={} delay_ms={delay}",
                        attempt + 1
                    ),
                );
                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
            }
            Err(message) => {
                return Err(if proxy_bind_address_in_use(&message) {
                    format!(
                        "{message}; r28 已避免同端口自重启并按 provider 刷新 resolver，若端口 {port} 仍失败说明此刻确有 listener/Windows socket 占用"
                    )
                } else {
                    message
                });
            }
        }
    }
    unreachable!("bounded proxy start retry loop always returns")
}

pub(crate) async fn start_proxy_if_needed(
    manager: &ProxyManager,
    port: u16,
) -> Result<bool, String> {
    start_proxy_r28_inner(manager, port, None).await
}

pub(crate) async fn start_proxy_for_provider_if_needed(
    manager: &ProxyManager,
    port: u16,
    expected_provider: &str,
) -> Result<bool, String> {
    start_proxy_r28_inner(manager, port, Some(expected_provider)).await
}
'''
    text = text[:start] + replacement + text[end:]
write(path, text)

# ---------------------------------------------------------------------------
# 3. Desktop routing boundary. Hybrid Direct never calls apply_provider and never
# rewrites Codex auth/config. It only ensures the Transfer gateway is ready.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/services/desktop/snapshot.rs"
text = read(path)
text = text.replace(
    "use crate::admin::handlers::proxy::{ensure_gateway_key, read_proxy_port, start_proxy_if_needed};",
    "use crate::admin::handlers::proxy::{\n    ensure_gateway_key, read_proxy_port, start_proxy_for_provider_if_needed, start_proxy_if_needed,\n};",
    1,
)
if "start_proxy_for_provider_if_needed" not in text:
    raise SystemExit("r28 snapshot import patch failed")

if "CAS-HYBRID-DIRECT-R28-RELAY-GATE" not in text:
    old = '''pub fn active_provider_supports_relay() -> bool {
    crate::admin::registry_io::load()
'''
    new = '''pub fn active_provider_supports_relay() -> bool {
    // CAS-HYBRID-DIRECT-R28-RELAY-GATE: official OAuth is never a Transfer relay.
    if super::hybrid_direct::enabled() {
        return false;
    }
    crate::admin::registry_io::load()
'''
    text = replace_once(text, old, new, label="active provider relay gate")

if "CAS-HYBRID-DIRECT-R28-APPLY-BLOCK" not in text:
    old = '''    let paths = CodexPaths::from_home_env().map_err(|e| e.to_string())?;
    // [MOC-104] relay 模式 gate:'''
    new = '''    let paths = CodexPaths::from_home_env().map_err(|e| e.to_string())?;
    // CAS-HYBRID-DIRECT-R28-APPLY-BLOCK: fail before apply_provider can touch
    // config.toml/auth.json. CC Switch is the Codex provider/auth owner in this mode.
    if super::hybrid_direct::enabled() {
        return Err(super::hybrid_direct::mutation_blocked(
            "改写 Codex provider/base URL/auth.json",
        ));
    }
    // [MOC-104] relay 模式 gate:'''
    text = replace_once(text, old, new, label="apply provider mutation block")

if "CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK" not in text:
    old = '''    use crate::codex_real_account as ra;
    use crate::codex_real_account::PluginUnlockMode as M;
    // [MOC-257 P1 review]'''
    new = '''    use crate::codex_real_account as ra;
    use crate::codex_real_account::PluginUnlockMode as M;
    // CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK: plugin unlock stashes/rewrites auth.json and
    // installs chatgpt_base_url relay, which is incompatible with zero-proxy OAuth.
    if super::hybrid_direct::enabled() {
        return Err(super::hybrid_direct::mutation_blocked(
            "切换 Plugin Unlock / ChatGPT relay",
        ));
    }
    // [MOC-257 P1 review]'''
    text = replace_once(text, old, new, label="plugin unlock mutation block")

if "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC" not in text:
    old = '''async fn sync_desktop_for_active_provider_impl(state: &AdminState, force_apikey: bool) -> Value {
    let target_result = with_config_write(|cfg| {
'''
    new = '''async fn sync_desktop_for_active_provider_impl(state: &AdminState, force_apikey: bool) -> Value {
    // CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC: gateway-only mode. Do not create a
    // DesktopConfigTarget and do not call apply_provider; only refresh/reuse the local
    // proxy resolver for Transfer's own active provider. Official GPT never reaches it.
    if super::hybrid_direct::enabled() {
        if force_apikey {
            return json!({
                "attempted": true,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "codexMutated": false,
                "message": super::hybrid_direct::mutation_blocked("清除/改写 Codex auth.json"),
            });
        }
        let cfg = match load_registry() {
            Ok(cfg) => cfg,
            Err(e) => return json!({"attempted": false, "success": false, "mode": "hybrid_direct_gateway", "codexMutated": false, "message": e}),
        };
        let Some(provider) = active_provider(&cfg) else {
            return json!({
                "attempted": false,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": false,
                "codexMutated": false,
                "message": "no default provider",
            });
        };
        let Some(provider_id) = provider.get("id").and_then(Value::as_str) else {
            return json!({
                "attempted": false,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": false,
                "codexMutated": false,
                "message": "active provider has no id",
            });
        };
        let port = read_proxy_port(&cfg);
        crate::codex_real_account::reset_applied_mode();
        codex_app_transfer_proxy::set_fake_account_mode(false);
        return match start_proxy_for_provider_if_needed(&state.proxy_manager, port, provider_id).await {
            Ok(started) => json!({
                "attempted": false,
                "success": true,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": started,
                "codexMutated": false,
                "provider": provider_id,
                "message": "Hybrid Direct gateway ready; CC Switch owns Codex provider/auth and official OAuth stays outside Transfer",
            }),
            Err(e) => json!({
                "attempted": false,
                "success": false,
                "mode": "hybrid_direct_gateway",
                "requiresProxy": true,
                "proxyStarted": false,
                "codexMutated": false,
                "provider": provider_id,
                "message": e,
            }),
        };
    }

    let target_result = with_config_write(|cfg| {
'''
    text = replace_once(text, old, new, label="gateway-only desktop sync")

if "CAS-HYBRID-DIRECT-R28-AUTO-APPLY" not in text:
    old = '''    if !read_setting_bool(&cfg, "autoApplyOnStart", true) {
        // [MOC-257 review] autoApplyOnStart=false'''
    new = '''    // CAS-HYBRID-DIRECT-R28-AUTO-APPLY: in Hybrid Direct this setting means
    // "auto-start Transfer gateway", never "apply provider into Codex".
    if super::hybrid_direct::enabled_from_config(&cfg) {
        codex_app_transfer_proxy::set_fake_account_mode(false);
        if !read_setting_bool(&cfg, "autoApplyOnStart", true) {
            return json!({"applied": false, "gatewayReady": false, "requiresProxy": false, "proxyStarted": false, "message": "Hybrid Direct: gateway auto-start disabled"});
        }
        if active_provider(&cfg).is_none() {
            return json!({"applied": false, "gatewayReady": false, "requiresProxy": false, "proxyStarted": false, "message": "Hybrid Direct: no active Transfer provider"});
        }
        let state = AdminState {
            proxy_manager,
            trace_viewer_manager: Arc::new(crate::trace_viewer::TraceViewerManager::new()),
        };
        let synced = sync_desktop_for_active_provider(&state).await;
        return json!({
            "applied": false,
            "gatewayReady": synced.get("success").and_then(Value::as_bool).unwrap_or(false),
            "requiresProxy": synced.get("requiresProxy").and_then(Value::as_bool).unwrap_or(false),
            "proxyStarted": synced.get("proxyStarted").and_then(Value::as_bool).unwrap_or(false),
            "codexMutated": false,
            "message": synced.get("message").cloned().unwrap_or_else(|| json!("Hybrid Direct gateway sync finished")),
        });
    }

    if !read_setting_bool(&cfg, "autoApplyOnStart", true) {
        // [MOC-257 review] autoApplyOnStart=false'''
    text = replace_once(text, old, new, label="hybrid auto-apply gateway semantics")

if "CAS-HYBRID-DIRECT-R28-RESTORE-BLOCK" not in text:
    old = '''    if !read_setting_bool(&cfg, "restoreCodexOnExit", true) {
        return json!({"attempted": false, "restored": false, "success": true, "reason": reason, "message": "disabled by settings"});
    }
'''
    new = '''    // CAS-HYBRID-DIRECT-R28-RESTORE-BLOCK: CC Switch may have changed config/auth
    // after Transfer started. Replaying an old Transfer snapshot would overwrite that owner.
    if super::hybrid_direct::enabled_from_config(&cfg) {
        return json!({"attempted": false, "restored": false, "success": true, "reason": reason, "message": "Hybrid Direct: restore skipped; CC Switch owns Codex provider/auth"});
    }
    if !read_setting_bool(&cfg, "restoreCodexOnExit", true) {
        return json!({"attempted": false, "restored": false, "success": true, "reason": reason, "message": "disabled by settings"});
    }
'''
    text = replace_once(text, old, new, label="snapshot restore block")

# Add focused integration tests before the existing test module's final known test area.
if "hybrid_direct_gateway_sync_preserves_codex_config_and_auth_bytes" not in text:
    anchor = '''    #[test]
    fn startup_auto_apply_respects_disabled_setting() {'''
    tests = r'''    #[test]
    fn hybrid_direct_gateway_sync_preserves_codex_config_and_auth_bytes() {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .unwrap();
        with_isolated_home(|home| {
            runtime.block_on(async {
                let mut cfg = config_with_secret();
                cfg["settings"]["hybridDirectMode"] = json!(true);
                cfg["settings"]["proxyPort"] = json!(0);
                save_registry(&cfg).unwrap();
                let codex = home.join(".codex");
                fs::create_dir_all(&codex).unwrap();
                let config_before = b"model_provider = \"openai\"\n# cc-switch-owned\n".to_vec();
                let auth_before = br#"{"auth_mode":"chatgpt","tokens":{"access_token":"official-oauth"}}"#.to_vec();
                fs::write(codex.join("config.toml"), &config_before).unwrap();
                fs::write(codex.join("auth.json"), &auth_before).unwrap();

                let manager = Arc::new(ProxyManager::new());
                let state = AdminState {
                    proxy_manager: Arc::clone(&manager),
                    trace_viewer_manager: Arc::new(crate::trace_viewer::TraceViewerManager::new()),
                };
                let result = sync_desktop_for_active_provider(&state).await;
                assert_eq!(result["success"], json!(true));
                assert_eq!(result["mode"], json!("hybrid_direct_gateway"));
                assert_eq!(result["codexMutated"], json!(false));
                assert!(manager.status().running);
                assert_eq!(fs::read(codex.join("config.toml")).unwrap(), config_before);
                assert_eq!(fs::read(codex.join("auth.json")).unwrap(), auth_before);
                manager.stop_silent();
            });
        });
    }

    #[test]
    fn hybrid_direct_provider_switch_refreshes_resolver_without_touching_codex() {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .unwrap();
        with_isolated_home(|home| {
            runtime.block_on(async {
                let mut cfg = config_with_secret();
                cfg["settings"]["hybridDirectMode"] = json!(true);
                cfg["settings"]["proxyPort"] = json!(0);
                cfg["providers"] = json!([
                    cfg["providers"][0].clone(),
                    {
                        "id": "p2",
                        "name": "Provider Two",
                        "baseUrl": "https://two.example.com/v1",
                        "authScheme": "bearer",
                        "apiFormat": "openai_chat",
                        "apiKey": "sk-two",
                        "models": {"default": "model-two"},
                        "sortIndex": 1
                    }
                ]);
                save_registry(&cfg).unwrap();
                let codex = home.join(".codex");
                fs::create_dir_all(&codex).unwrap();
                let config_before = b"model_provider = \"custom\"\n# cc-switch-owned\n".to_vec();
                let auth_before = br#"{"auth_mode":"chatgpt","tokens":{"access_token":"official-oauth"}}"#.to_vec();
                fs::write(codex.join("config.toml"), &config_before).unwrap();
                fs::write(codex.join("auth.json"), &auth_before).unwrap();

                let manager = Arc::new(ProxyManager::new());
                let state = AdminState {
                    proxy_manager: Arc::clone(&manager),
                    trace_viewer_manager: Arc::new(crate::trace_viewer::TraceViewerManager::new()),
                };
                let first = sync_desktop_for_active_provider(&state).await;
                assert_eq!(first["success"], json!(true));
                assert_eq!(manager.status().active_provider.as_deref(), Some("p1"));

                let switched = switch_provider_and_sync(Arc::clone(&manager), "p2".to_owned()).await;
                assert_eq!(switched["success"], json!(true));
                assert_eq!(switched["desktopSync"]["mode"], json!("hybrid_direct_gateway"));
                assert_eq!(manager.status().active_provider.as_deref(), Some("p2"));
                assert_eq!(fs::read(codex.join("config.toml")).unwrap(), config_before);
                assert_eq!(fs::read(codex.join("auth.json")).unwrap(), auth_before);
                manager.stop_silent();
            });
        });
    }

'''
    text = replace_once(text, anchor, tests + anchor, label="hybrid integration tests")
write(path, text)

# ---------------------------------------------------------------------------
# 4. Settings transition: enabling the mode is blocked while Transfer still owns
# an active/stale snapshot. This prevents a later restore from clobbering CC Switch.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/handlers/settings.rs"
text = read(path)
if '"hybridDirectMode": false' not in text:
    text = replace_once(
        text,
        '           "autoApplyOnStart": true,\n',
        '           "autoApplyOnStart": true,\n           "hybridDirectMode": false,\n',
        label="default hybrid setting",
    )

if "CAS-HYBRID-DIRECT-R28-ENABLE-PREFLIGHT" not in text:
    old = '''pub async fn save_settings(Json(input): Json<Value>) -> impl IntoResponse {
    let result = with_config_write(|cfg| {
'''
    new = '''pub async fn save_settings(Json(input): Json<Value>) -> impl IntoResponse {
    // CAS-HYBRID-DIRECT-R28-ENABLE-PREFLIGHT: transition only from a clean
    // Transfer state. Do not auto-restore here because CC Switch may already own a newer config.
    let requested_hybrid = input.get("hybridDirectMode").and_then(Value::as_bool);
    if requested_hybrid == Some(true) {
        let already_enabled = load_registry()
            .ok()
            .as_ref()
            .is_some_and(crate::admin::services::desktop::hybrid_direct::enabled_from_config);
        if !already_enabled {
            if let Err(e) = crate::admin::services::desktop::hybrid_direct::enable_preflight() {
                return err(StatusCode::CONFLICT, e).into_response();
            }
        }
    }
    let result = with_config_write(|cfg| {
'''
    text = replace_once(text, old, new, label="hybrid enable preflight")

if "CAS-HYBRID-DIRECT-R28-SETTING-ACTIVE" not in text:
    old = '''        Ok((settings, portable_changed, auto_unlock_changed, web_fetch_changed)) => {
            // #262:settings.language 改动后 hot reload 到 adapters 全局,
'''
    new = '''        Ok((settings, portable_changed, auto_unlock_changed, web_fetch_changed)) => {
            // CAS-HYBRID-DIRECT-R28-SETTING-ACTIVE: immediately disable any in-memory
            // synthetic ChatGPT fabrication. The setting itself never rewrites Codex files.
            if requested_hybrid == Some(true) {
                codex_app_transfer_proxy::set_fake_account_mode(false);
                crate::codex_real_account::reset_applied_mode();
                tracing::info!("[hybrid-direct-r28] enabled: Transfer is gateway-only; Codex provider/auth remain externally owned");
            }
            // #262:settings.language 改动后 hot reload 到 adapters 全局,
'''
    text = replace_once(text, old, new, label="hybrid setting activation")
write(path, text)

# ---------------------------------------------------------------------------
# 5. Process/startup/exit safety. Never inject CODEX_API_BASE_URL, cancel official
# login, restore Transfer snapshots, or re-apply plugin relay in Hybrid Direct.
# ---------------------------------------------------------------------------
path = "src-tauri/src/admin/services/desktop/process.rs"
text = read(path)
if "CAS-HYBRID-DIRECT-R28-CHAT-ENV-BLOCK" not in text:
    old = '''fn chat_launch_env(platform: &str) -> Vec<(String, String)> {
    if platform != "macos" {
'''
    new = '''fn chat_launch_env(platform: &str) -> Vec<(String, String)> {
    // CAS-HYBRID-DIRECT-R28-CHAT-ENV-BLOCK: CODEX_API_BASE_URL would proxy official
    // ChatGPT traffic even if config.toml is pristine, so Hybrid Direct forbids it.
    if crate::admin::services::desktop::hybrid_direct::enabled() {
        return Vec::new();
    }
    if platform != "macos" {
'''
    text = replace_once(text, old, new, label="chat launch env block")
write(path, text)

path = "src-tauri/src/main.rs"
text = read(path)
if "CAS-HYBRID-DIRECT-R28-RESTORE-OWNER" not in text:
    old = '''fn restore_codex_on_exit_enabled() -> bool {
    handlers::settings::load_registry_for_startup_language_sync()
'''
    new = '''fn restore_codex_on_exit_enabled() -> bool {
    // CAS-HYBRID-DIRECT-R28-RESTORE-OWNER: Hybrid Direct never replays Transfer
    // snapshots or unstashes auth over CC Switch-owned live files.
    if admin::services::desktop::hybrid_direct::enabled() {
        return false;
    }
    handlers::settings::load_registry_for_startup_language_sync()
'''
    text = replace_once(text, old, new, label="main restore ownership gate")

if "CAS-HYBRID-DIRECT-R28-FAKE-OFF" not in text:
    old = '''            codex_app_transfer_proxy::set_fake_account_mode(
                will_apply_synthetic || crate::codex_real_account::active_is_synthetic(),
            );
'''
    new = '''            // CAS-HYBRID-DIRECT-R28-FAKE-OFF: no /backend-api fabrication in
            // zero-proxy OAuth mode, even if an old synthetic auth marker survived externally.
            if admin::services::desktop::hybrid_direct::enabled() {
                codex_app_transfer_proxy::set_fake_account_mode(false);
            } else {
                codex_app_transfer_proxy::set_fake_account_mode(
                    will_apply_synthetic || crate::codex_real_account::active_is_synthetic(),
                );
            }
'''
    text = replace_once(text, old, new, label="startup fake account off")

if "CAS-HYBRID-DIRECT-R28-STARTUP-PLUGIN-SKIP" not in text:
    start_anchor = '''                {
                    // [MOC-257 三态] 统一插件解锁:迁移旧三开关 → pluginUnlockMode;解析生效三态;apply。
'''
    start_new = '''                {
                    // CAS-HYBRID-DIRECT-R28-STARTUP-PLUGIN-SKIP: plugin account/relay
                    // management owns auth.json + chatgpt_base_url, so never run it here.
                    if admin::services::desktop::hybrid_direct::enabled() {
                        codex_app_transfer_proxy::set_fake_account_mode(false);
                        tracing::info!("[hybrid-direct-r28] startup: skipped Plugin Unlock/auth relay reconciliation");
                    } else {
                    // [MOC-257 三态] 统一插件解锁:迁移旧三开关 → pluginUnlockMode;解析生效三态;apply。
'''
    text = replace_once(text, start_anchor, start_new, label="startup plugin skip open")
    end_anchor = '''                }
                // [MOC-104] reconcile 已把活动账号 settle 完。relay 模式下真实 chatgpt
'''
    end_new = '''                    }
                }
                // [MOC-104] reconcile 已把活动账号 settle 完。relay 模式下真实 chatgpt
'''
    text = replace_once(text, end_anchor, end_new, label="startup plugin skip close")

if "CAS-HYBRID-DIRECT-R28-LOGIN-OWNER" not in text:
    old = '''            if crate::codex_real_account::cancel_login() {
                tracing::info!("app exit: 已取消 in-flight codex login,防孤儿进程退出后改写 auth.json");
            }
'''
    new = '''            // CAS-HYBRID-DIRECT-R28-LOGIN-OWNER: official Codex login belongs to
            // Codex/CC Switch; exiting Transfer must not cancel that OAuth flow.
            if !admin::services::desktop::hybrid_direct::enabled()
                && crate::codex_real_account::cancel_login()
            {
                tracing::info!("app exit: 已取消 in-flight codex login,防孤儿进程退出后改写 auth.json");
            }
'''
    text = replace_once(text, old, new, label="exit login ownership gate")

if "CAS-HYBRID-DIRECT-R28-TRAY-PLUGIN-SKIP" not in text:
    old = '''                if !matches!(mode, crate::codex_real_account::PluginUnlockMode::Off) {
'''
    new = '''                // CAS-HYBRID-DIRECT-R28-TRAY-PLUGIN-SKIP
                if !admin::services::desktop::hybrid_direct::enabled()
                    && !matches!(mode, crate::codex_real_account::PluginUnlockMode::Off)
                {
'''
    text = replace_once(text, old, new, label="tray plugin relay skip")
write(path, text)

# ---------------------------------------------------------------------------
# 6. Frontend: explicit mode, no automatic CC Switch session normalization, and a
# gateway-only status label. Do not pretend the stock picker is provider-aware yet.
# ---------------------------------------------------------------------------
path = "frontend/src/App.vue"
text = read(path)
if "CAS-HYBRID-DIRECT-R28-SESSION-OWNER" not in text:
    old = '''  const si = useSessionImport()
  const foreign = await si.detect()
  if (foreign > 0) await si.promptImport(foreign)
'''
    new = '''  // CAS-HYBRID-DIRECT-R28-SESSION-OWNER: CC Switch owns model_provider in
  // Hybrid Direct. Never auto-normalize its third-party threads back to openai.
  if (!settings.bool('hybridDirectMode', false)) {
    const si = useSessionImport()
    const foreign = await si.detect()
    if (foreign > 0) await si.promptImport(foreign)
  }
'''
    text = replace_once(text, old, new, label="frontend session ownership gate")
write(path, text)

path = "frontend/src/api/proxy.ts"
text = read(path)
if "hybridDirectMode?: boolean" not in text:
    text = text.replace(
        "api<{ running?: boolean; port?: number; stats?: ProxyStats }>('GET', '/api/proxy/status')",
        "api<{ running?: boolean; port?: number; stats?: ProxyStats; hybridDirectMode?: boolean }>('GET', '/api/proxy/status')",
        1,
    )
write(path, text)

path = "frontend/src/stores/proxy.ts"
text = read(path)
if "const hybridDirectMode" not in text:
    text = replace_once(
        text,
        "  const port = ref(0)\n",
        "  const port = ref(0)\n  const hybridDirectMode = ref(false)\n",
        label="proxy store hybrid ref",
    )
    text = replace_once(
        text,
        "    port.value = s.port || 18080\n",
        "    port.value = s.port || 18080\n    hybridDirectMode.value = !!s.hybridDirectMode\n",
        label="proxy store hybrid hydration",
    )
    text = replace_once(
        text,
        "  return { running, port, stats, logs, loadStatus, toggle, loadLogs, clearLogs, openLogDir }\n",
        "  return { running, port, hybridDirectMode, stats, logs, loadStatus, toggle, loadLogs, clearLogs, openLogDir }\n",
        label="proxy store hybrid export",
    )
write(path, text)

path = "frontend/src/pages/ProxyPage.vue"
text = read(path)
if "proxy.hybridDirectGateway" not in text:
    text = replace_once(
        text,
        '''        <span class="status-sub">{{ t('proxy.localhost') }}</span>
''',
        '''        <span class="status-sub">{{ store.hybridDirectMode ? t('proxy.hybridDirectGateway') : t('proxy.localhost') }}</span>
''',
        label="proxy hybrid status label",
    )
write(path, text)

path = "frontend/src/pages/SettingsPage.vue"
text = read(path)
if "const hybridDirectMode" not in text:
    text = replace_once(
        text,
        "const autoApplyOnStart = toggle('autoApplyOnStart', true)\n",
        "const hybridDirectMode = toggle('hybridDirectMode', false)\nconst autoApplyOnStart = toggle('autoApplyOnStart', true)\n",
        label="settings hybrid computed",
    )
if "settings.hybridDirect" not in text:
    old = '''    <SettingsGroup :title="t('settings.groupStartup')">
      <SettingsRow :title="t('settings.autoApplyOnStart')" :description="t('settings.autoApplyOnStartHint')">
        <AppSwitch v-model="autoApplyOnStart" />
      </SettingsRow>
      <SettingsRow :title="t('settings.restoreCodexOnExit')" :description="t('settings.restoreCodexOnExitHint')">
        <AppSwitch v-model="restoreCodexOnExit" />
      </SettingsRow>
      <SettingsRow :title="t('settings.pluginUnlock')" :description="t('settings.pluginUnlockHint')">
'''
    new = '''    <SettingsGroup :title="t('settings.groupStartup')">
      <SettingsRow :title="t('settings.hybridDirect')" :description="t('settings.hybridDirectHint')">
        <AppSwitch v-model="hybridDirectMode" />
      </SettingsRow>
      <SettingsRow
        :title="t('settings.autoApplyOnStart')"
        :description="hybridDirectMode ? t('settings.hybridDirectAutoApplyHint') : t('settings.autoApplyOnStartHint')"
      >
        <AppSwitch v-model="autoApplyOnStart" />
      </SettingsRow>
      <SettingsRow
        v-if="!hybridDirectMode"
        :title="t('settings.restoreCodexOnExit')"
        :description="t('settings.restoreCodexOnExitHint')"
      >
        <AppSwitch v-model="restoreCodexOnExit" />
      </SettingsRow>
      <SettingsRow v-if="!hybridDirectMode" :title="t('settings.pluginUnlock')" :description="t('settings.pluginUnlockHint')">
'''
    text = replace_once(text, old, new, label="settings hybrid controls")
    text = text.replace(
        '''      <SettingsRow :title="t('settings.codexNetworkAccess')" :description="t('settings.codexNetworkAccessHint')">
''',
        '''      <SettingsRow v-if="!hybridDirectMode" :title="t('settings.codexNetworkAccess')" :description="t('settings.codexNetworkAccessHint')">
''',
        1,
    )
    # Session import/restore rewrites model_provider and must stay disabled while CC Switch owns it.
    text = text.replace(
        '''        <AppButton
          size="sm"
          variant="secondary"
          :label="t('settings.sessionRestoreBtn')"
''',
        '''        <AppButton
          v-if="!hybridDirectMode"
          size="sm"
          variant="secondary"
          :label="t('settings.sessionRestoreBtn')"
''',
        1,
    )
    text = text.replace(
        '''        <AppButton
          size="sm"
          variant="secondary"
          :label="t('settings.sessionImportBtn')"
''',
        '''        <AppButton
          v-if="!hybridDirectMode"
          size="sm"
          variant="secondary"
          :label="t('settings.sessionImportBtn')"
''',
        1,
    )
write(path, text)

for rel, entries in {
    "frontend/src/i18n/zh.ts": '''  "settings.hybridDirect": "Hybrid Direct（CC Switch）",
  "settings.hybridDirectHint": "安全模式：Transfer 只作为 Grok/第三方本地网关，不改 Codex provider、openai/chatgpt base URL 或 auth.json。启用前必须先还原 Transfer 管理的 Codex 快照；官方 OAuth 请在 CC Switch 选择 OpenAI Official，并保持 Codex 本地路由关闭。",
  "settings.hybridDirectAutoApplyHint": "Hybrid Direct 下仅自动启动 Transfer 的 Grok/第三方网关，不会把 provider 或 OAuth 路由写入 Codex。",
  "proxy.hybridDirectGateway": "Hybrid Direct · 仅第三方网关",
''',
    "frontend/src/i18n/en.ts": '''  "settings.hybridDirect": "Hybrid Direct (CC Switch)",
  "settings.hybridDirectHint": "Safety mode: Transfer is only the local gateway for Grok/third-party traffic and will not rewrite Codex provider, openai/chatgpt base URLs, or auth.json. Restore any Transfer-managed Codex snapshot before enabling. For official OAuth, select OpenAI Official in CC Switch and keep Codex Local Routing off.",
  "settings.hybridDirectAutoApplyHint": "In Hybrid Direct, auto-apply only starts the Transfer Grok/third-party gateway; it never writes provider or OAuth routing into Codex.",
  "proxy.hybridDirectGateway": "Hybrid Direct · third-party gateway only",
''',
}.items():
    text = read(rel)
    if '"settings.hybridDirect"' not in text:
        anchor = "} as Record<string, string>;"
        text = replace_once(text, anchor, entries + anchor, label=f"{rel} hybrid i18n")
    write(rel, text)

# Backend status used by the proxy page; intentionally does not expose the gateway secret.
path = "src-tauri/src/admin/handlers/proxy.rs"
text = read(path)
if '"hybridDirectMode"' not in text:
    old = '''        "stats": proxy_telemetry().stats.snapshot(),
    }))
'''
    new = '''        "stats": proxy_telemetry().stats.snapshot(),
        "hybridDirectMode": crate::admin::services::desktop::hybrid_direct::enabled_from_config(&cfg),
    }))
'''
    text = replace_once(text, old, new, label="proxy status hybrid flag")
write(path, text)

# ---------------------------------------------------------------------------
# Materialization gate: exact safety markers and order-sensitive boundaries.
# ---------------------------------------------------------------------------
checks = {
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs": [
        "CAS-HYBRID-DIRECT-R28",
        "enable_preflight",
        "mutation_blocked",
    ],
    "src-tauri/src/admin/handlers/proxy.rs": [
        "CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH",
        "start_proxy_for_provider_if_needed",
        '"hybridDirectMode"',
    ],
    "src-tauri/src/admin/services/desktop/snapshot.rs": [
        "CAS-HYBRID-DIRECT-R28-RELAY-GATE",
        "CAS-HYBRID-DIRECT-R28-APPLY-BLOCK",
        "CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK",
        "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
        "CAS-HYBRID-DIRECT-R28-AUTO-APPLY",
        "CAS-HYBRID-DIRECT-R28-RESTORE-BLOCK",
        "hybrid_direct_gateway_sync_preserves_codex_config_and_auth_bytes",
        "hybrid_direct_provider_switch_refreshes_resolver_without_touching_codex",
    ],
    "src-tauri/src/admin/handlers/settings.rs": [
        "CAS-HYBRID-DIRECT-R28-ENABLE-PREFLIGHT",
        "CAS-HYBRID-DIRECT-R28-SETTING-ACTIVE",
        '"hybridDirectMode": false',
    ],
    "src-tauri/src/admin/services/desktop/process.rs": ["CAS-HYBRID-DIRECT-R28-CHAT-ENV-BLOCK"],
    "src-tauri/src/main.rs": [
        "CAS-HYBRID-DIRECT-R28-RESTORE-OWNER",
        "CAS-HYBRID-DIRECT-R28-FAKE-OFF",
        "CAS-HYBRID-DIRECT-R28-STARTUP-PLUGIN-SKIP",
        "CAS-HYBRID-DIRECT-R28-LOGIN-OWNER",
        "CAS-HYBRID-DIRECT-R28-TRAY-PLUGIN-SKIP",
    ],
    "frontend/src/App.vue": ["CAS-HYBRID-DIRECT-R28-SESSION-OWNER"],
    "frontend/src/pages/SettingsPage.vue": ["settings.hybridDirect", "hybridDirectMode"],
    "frontend/src/pages/ProxyPage.vue": ["proxy.hybridDirectGateway"],
}
for rel, markers in checks.items():
    body = read(rel)
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r28 materialization missing marker in {rel}: {marker}")

# Order gates: the block must happen before the first dangerous mutation call.
snapshot = read("src-tauri/src/admin/services/desktop/snapshot.rs")
if snapshot.index("CAS-HYBRID-DIRECT-R28-APPLY-BLOCK") > snapshot.index("let result = apply_provider("):
    raise SystemExit("r28 apply block appears after apply_provider")
plugin_start = snapshot.index("pub async fn apply_plugin_unlock_mode(")
plugin_block = snapshot.index("CAS-HYBRID-DIRECT-R28-PLUGIN-BLOCK", plugin_start)
plugin_snapshot = snapshot.index("snapshot_codex_state(", plugin_start)
if plugin_block > plugin_snapshot:
    raise SystemExit("r28 plugin block appears after snapshot/auth mutation boundary")
sync_start = snapshot.index("async fn sync_desktop_for_active_provider_impl")
sync_gate = snapshot.index("CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC", sync_start)
sync_target = snapshot.index("desktop_config_target_for_provider", sync_start)
if sync_gate > sync_target:
    raise SystemExit("r28 gateway sync gate appears after desktop target/apply path")

print("r28 Hybrid Direct materialization gate: PASS")
