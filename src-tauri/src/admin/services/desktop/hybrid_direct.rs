//! CAS-HYBRID-DIRECT-R28: safety boundary for CC Switch + Transfer coexistence.
//!
//! Hard invariant:
//! - Codex's official ChatGPT/OAuth route is owned by Codex + CC Switch and must never
//!   be rewritten by Transfer while Hybrid Direct is enabled.
//! - Transfer may still run its authenticated localhost gateway for third-party/Grok
//!   traffic selected by a CC Switch custom provider.

use codex_app_transfer_codex_integration::{has_snapshot, has_stale_active_snapshot, CodexPaths};
use codex_app_transfer_registry::RawConfig;

pub const SETTING_KEY: &str = "hybridDirectMode";

pub fn enabled_from_config(cfg: &RawConfig) -> bool {
    cfg.get("settings")
        .and_then(|s| s.get(SETTING_KEY))
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

pub fn enabled() -> bool {
    crate::admin::registry_io::load()
        .ok()
        .as_ref()
        .is_some_and(enabled_from_config)
}

/// Enabling Hybrid Direct is intentionally fail-closed if Transfer still owns a
/// live/recovery snapshot. Restoring that snapshot *after* CC Switch has taken
/// ownership could overwrite a newer CC Switch provider config or OAuth state.
/// The user must first restore/clear the Transfer-managed state, then enable this
/// mode; afterwards Transfer never performs provider/auth restore/apply operations.
pub fn enable_preflight() -> Result<(), String> {
    let paths = CodexPaths::from_home_env().map_err(|e| e.to_string())?;
    if has_snapshot(&paths) || has_stale_active_snapshot(&paths) {
        return Err(
            "Hybrid Direct 启用被阻止：检测到 Transfer 仍持有 Codex 配置快照。请先在设置 → Codex 配置执行“还原 Codex 原配置”，再用 CC Switch 选择所需 provider（官方 OAuth 时关闭 CC Switch 本地路由），最后重新开启 Hybrid Direct。"
                .to_owned(),
        );
    }
    if crate::codex_real_account::active_is_synthetic() {
        return Err(
            "Hybrid Direct 启用被阻止：当前 auth.json 仍是 Transfer synthetic 账号。请先还原 Codex 原配置/真实账号，再开启 Hybrid Direct。"
                .to_owned(),
        );
    }
    Ok(())
}

pub fn mutation_blocked(action: &str) -> String {
    format!(
        "Hybrid Direct 已启用：拒绝 Transfer {action}，以保证官方 OAuth GPT 不经过 Transfer/反代。请用 CC Switch 管理 Codex provider/auth；官方 OpenAI 使用 Official 且保持 CC Switch Codex Local Routing 关闭。"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn setting_defaults_off_and_reads_explicit_true() {
        assert!(!enabled_from_config(&json!({})));
        assert!(!enabled_from_config(
            &json!({"settings": {SETTING_KEY: false}})
        ));
        assert!(enabled_from_config(
            &json!({"settings": {SETTING_KEY: true}})
        ));
    }

    #[test]
    fn block_message_states_zero_proxy_reason() {
        let message = mutation_blocked("改写 Codex 路由");
        assert!(message.contains("官方 OAuth GPT"));
        assert!(message.contains("CC Switch"));
        assert!(message.contains("Local Routing"));
    }
}
