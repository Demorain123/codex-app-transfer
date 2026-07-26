from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.write_text(text, encoding="utf-8")
    print(f"patched {rel}")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# crates/proxy/src/forward.rs
# ---------------------------------------------------------------------------
path = "crates/proxy/src/forward.rs"
text = read(path)

if "CAS-APPS-MCP-AUTH-R25-STATE" not in text:
    text = replace_once(
        text,
        "#[derive(Clone)]\npub struct ProxyState {",
        """// CAS-APPS-MCP-AUTH-R25-STATE\n// A deliberately tiny in-memory credential snapshot. It is created per request by\n// src-tauri from the currently-active *real* ChatGPT auth.json. The proxy never\n// persists or logs these values.\n#[derive(Clone)]\npub struct ChatgptMcpRelayAuth {\n    pub access_token: String,\n    pub account_id: Option<String>,\n}\n\n#[derive(Clone)]\npub struct ProxyState {""",
        label="forward: ProxyState declaration",
    )

    text = replace_once(
        text,
        """    on_chatgpt_unauthorized: Option<std::sync::Arc<dyn Fn(u64) + Send + Sync>>,\n}""",
        """    on_chatgpt_unauthorized: Option<std::sync::Arc<dyn Fn(u64) + Send + Sync>>,\n    /// CAS-APPS-MCP-AUTH-R25-STATE: lazy provider for the currently-active real\n    /// ChatGPT bearer. A callback (rather than a cached token) avoids stale-token\n    /// reuse when Codex refreshes/replaces auth.json while Transfer stays running.\n    chatgpt_mcp_auth_provider: Option<\n        std::sync::Arc<dyn Fn() -> Option<ChatgptMcpRelayAuth> + Send + Sync>,\n    >,\n}""",
        label="forward: ProxyState callback field",
    )

    needle = "            on_chatgpt_unauthorized: None,\n"
    if text.count(needle) != 2:
        raise SystemExit(
            f"forward: expected two ProxyState constructor relogin fields, found {text.count(needle)}"
        )
    text = text.replace(
        needle,
        needle + "            chatgpt_mcp_auth_provider: None,\n",
    )

    text = replace_once(
        text,
        """    pub fn with_relogin_notify(\n        mut self,\n        notify: std::sync::Arc<dyn Fn(u64) + Send + Sync>,\n    ) -> Self {\n        self.on_chatgpt_unauthorized = Some(notify);\n        self\n    }\n}""",
        """    pub fn with_relogin_notify(\n        mut self,\n        notify: std::sync::Arc<dyn Fn(u64) + Send + Sync>,\n    ) -> Self {\n        self.on_chatgpt_unauthorized = Some(notify);\n        self\n    }\n\n    /// CAS-APPS-MCP-AUTH-R25-STATE: inject a read-only callback that returns the\n    /// *current* real ChatGPT credential snapshot. The callback is evaluated only\n    /// for the strict hosted Apps MCP allowlist and only when Codex omitted auth.\n    pub fn with_chatgpt_mcp_auth_provider(\n        mut self,\n        provider: std::sync::Arc<\n            dyn Fn() -> Option<ChatgptMcpRelayAuth> + Send + Sync,\n        >,\n    ) -> Self {\n        self.chatgpt_mcp_auth_provider = Some(provider);\n        self\n    }\n}""",
        label="forward: with_relogin_notify impl",
    )

if "CAS-APPS-MCP-AUTH-R25-HELPERS" not in text:
    text = replace_once(
        text,
        """fn is_chatgpt_mcp_backend_path(path: &str) -> bool {\n    let p = diagnostic_path_only(path);\n    p == \"/backend-api/ps/mcp\" || p.starts_with(\"/backend-api/ps/mcp/\")\n}\n""",
        """fn is_chatgpt_mcp_backend_path(path: &str) -> bool {\n    let p = diagnostic_path_only(path);\n    p == \"/backend-api/ps/mcp\" || p.starts_with(\"/backend-api/ps/mcp/\")\n}\n\n// CAS-APPS-MCP-AUTH-R25-HELPERS\n// Rehydrate only the ChatGPT-hosted Apps MCP namespace and never overwrite an\n// Authorization header supplied by Codex. The allowlist is checked on the canonical\n// outbound ChatGPT URL so dot-segment normalization cannot escape the MCP namespace.\nfn should_rehydrate_chatgpt_mcp_auth(path: &str, headers: &HeaderMap) -> bool {\n    if headers.contains_key(http::header::AUTHORIZATION) {\n        return false;\n    }\n    let Ok(url) = reqwest::Url::parse(&format!(\"https://chatgpt.com{path}\")) else {\n        return false;\n    };\n    if url.scheme() != \"https\" || url.host_str() != Some(\"chatgpt.com\") {\n        return false;\n    }\n    let canonical = url.path();\n    canonical == \"/backend-api/ps/mcp\" || canonical.starts_with(\"/backend-api/ps/mcp/\")\n}\n\nstruct PreparedChatgptMcpRelayAuth {\n    authorization: reqwest::header::HeaderValue,\n    account_id: Option<reqwest::header::HeaderValue>,\n}\n\nfn prepare_chatgpt_mcp_relay_auth(\n    auth: ChatgptMcpRelayAuth,\n    inbound_headers: &HeaderMap,\n) -> Option<PreparedChatgptMcpRelayAuth> {\n    if auth.access_token.trim().is_empty() {\n        return None;\n    }\n    let authorization = reqwest::header::HeaderValue::from_bytes(\n        format!(\"Bearer {}\", auth.access_token).as_bytes(),\n    )\n    .ok()?;\n    let account_id = if inbound_headers.contains_key(\"chatgpt-account-id\") {\n        None\n    } else {\n        auth.account_id\n            .as_deref()\n            .filter(|value| !value.trim().is_empty())\n            .and_then(|value| reqwest::header::HeaderValue::from_bytes(value.as_bytes()).ok())\n    };\n    Some(PreparedChatgptMcpRelayAuth {\n        authorization,\n        account_id,\n    })\n}\n\n#[cfg(test)]\nmod apps_mcp_auth_r25_proxy_tests {\n    use super::*;\n\n    #[test]\n    fn allowlist_is_exact_canonical_and_never_overwrites_inbound_authorization() {\n        let headers = HeaderMap::new();\n        assert!(should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcp\",\n            &headers\n        ));\n        assert!(should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcp/.well-known/oauth-protected-resource?state=secret\",\n            &headers\n        ));\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcpish\",\n            &headers\n        ));\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcp/../plugins/installed\",\n            &headers\n        ));\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcp/%2e%2e/plugins/installed\",\n            &headers\n        ));\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/plugins/installed\",\n            &headers\n        ));\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\"/responses\", &headers));\n\n        let mut supplied = HeaderMap::new();\n        supplied.insert(http::header::AUTHORIZATION, \"Bearer inbound\".parse().unwrap());\n        assert!(!should_rehydrate_chatgpt_mcp_auth(\n            \"/backend-api/ps/mcp\",\n            &supplied\n        ));\n    }\n\n    #[test]\n    fn prepared_auth_preserves_inbound_account_and_rejects_malformed_token() {\n        let mut headers = HeaderMap::new();\n        headers.insert(\"chatgpt-account-id\", \"account-from-codex\".parse().unwrap());\n        let prepared = prepare_chatgpt_mcp_relay_auth(\n            ChatgptMcpRelayAuth {\n                access_token: \"token-from-auth-json\".to_string(),\n                account_id: Some(\"account-local\".to_string()),\n            },\n            &headers,\n        )\n        .expect(\"valid bearer\");\n        assert_eq!(prepared.authorization, \"Bearer token-from-auth-json\");\n        assert!(prepared.account_id.is_none());\n\n        let malformed = prepare_chatgpt_mcp_relay_auth(\n            ChatgptMcpRelayAuth {\n                access_token: \"bad\\ntoken\".to_string(),\n                account_id: None,\n            },\n            &HeaderMap::new(),\n        );\n        assert!(malformed.is_none());\n    }\n}\n""",
        label="forward: MCP path helper",
    )

if "CAS-APPS-MCP-AUTH-R25-REHYDRATE" not in text:
    text = replace_once(
        text,
        """    for (k, v) in headers.iter() {\n        let name = k.as_str();\n        // host 让 reqwest 按 upstream 重填;accept-encoding 去掉避免压缩 body 干扰 log\n        if name.eq_ignore_ascii_case(\"host\") || name.eq_ignore_ascii_case(\"accept-encoding\") {\n            continue;\n        }\n        rb = rb.header(name, v.as_bytes());\n    }\n    if !body.is_empty() {""",
        """    for (k, v) in headers.iter() {\n        let name = k.as_str();\n        // host 让 reqwest 按 upstream 重填;accept-encoding 去掉避免压缩 body 干扰 log\n        if name.eq_ignore_ascii_case(\"host\") || name.eq_ignore_ascii_case(\"accept-encoding\") {\n            continue;\n        }\n        rb = rb.header(name, v.as_bytes());\n    }\n\n    // CAS-APPS-MCP-AUTH-R25-REHYDRATE\n    // Codex Desktop can omit Authorization on the hosted Apps MCP relay even while\n    // the active ~/.codex/auth.json is a valid real ChatGPT login. Rehydrate only\n    // this allowlisted namespace, never overwrite inbound auth, and never consult\n    // provider/Sub2API credentials. Synthetic account mode is an explicit hard stop.\n    if is_chatgpt_mcp_backend_path(client_path) {\n        if headers.contains_key(http::header::AUTHORIZATION) {\n            telemetry.logs.add(\n                \"INFO\",\n                \"[apps-mcp-auth] action=passthrough reason=inbound_auth_present\".to_string(),\n            );\n        } else if crate::fake_account::fake_account_mode_enabled() {\n            telemetry.logs.add(\n                \"INFO\",\n                \"[apps-mcp-auth] action=skip reason=synthetic_account\".to_string(),\n            );\n        } else if should_rehydrate_chatgpt_mcp_auth(client_path, headers) {\n            let current_auth = state\n                .chatgpt_mcp_auth_provider\n                .as_ref()\n                .and_then(|provider| provider());\n            match current_auth.and_then(|auth| prepare_chatgpt_mcp_relay_auth(auth, headers)) {\n                Some(prepared) => {\n                    rb = rb.header(reqwest::header::AUTHORIZATION, prepared.authorization);\n                    let account_added = prepared.account_id.is_some();\n                    if let Some(account_id) = prepared.account_id {\n                        rb = rb.header(\"chatgpt-account-id\", account_id);\n                    }\n                    telemetry.logs.add(\n                        \"INFO\",\n                        format!(\n                            \"[apps-mcp-auth] action=rehydrate source=official_chatgpt_auth account_id_added={account_added}\"\n                        ),\n                    );\n                }\n                None => telemetry.logs.add(\n                    \"INFO\",\n                    \"[apps-mcp-auth] action=skip reason=no_real_chatgpt_auth\".to_string(),\n                ),\n            }\n        }\n    }\n\n    if !body.is_empty() {""",
        label="forward: outbound header copy loop",
    )

    text = replace_once(
        text,
        "notify(authorization_token_fingerprint(headers));",
        "notify(authorization_token_fingerprint(&outbound_headers_snapshot)); // CAS-APPS-MCP-AUTH-R25-401-FP",
        label="forward: 401 token fingerprint",
    )

write(path, text)


# ---------------------------------------------------------------------------
# crates/proxy/src/server.rs
# ---------------------------------------------------------------------------
path = "crates/proxy/src/server.rs"
text = read(path)
if "CAS-APPS-MCP-AUTH-R25-ROUTER" not in text:
    text = replace_once(
        text,
        "use crate::forward::{forward_handler, ProxyState};",
        "use crate::forward::{forward_handler, ChatgptMcpRelayAuth, ProxyState};",
        label="server: forward import",
    )
    anchor = """pub fn build_router_with_relogin(\n    resolver: SharedResolver,\n    on_chatgpt_unauthorized: std::sync::Arc<dyn Fn(u64) + Send + Sync>,\n) -> Router {\n    build_router_with_state(ProxyState::new(resolver).with_relogin_notify(on_chatgpt_unauthorized))\n}\n"""
    replacement = anchor + """\n/// CAS-APPS-MCP-AUTH-R25-ROUTER\n/// Same router as `build_router_with_relogin`, plus a lazy, read-only credential\n/// provider used exclusively by the ChatGPT hosted Apps MCP allowlist. Keeping\n/// this as a separate constructor preserves proxy crate/test callers that do not\n/// have access to desktop auth state.\npub fn build_router_with_relogin_and_mcp_auth(\n    resolver: SharedResolver,\n    on_chatgpt_unauthorized: std::sync::Arc<dyn Fn(u64) + Send + Sync>,\n    chatgpt_mcp_auth_provider: std::sync::Arc<\n        dyn Fn() -> Option<ChatgptMcpRelayAuth> + Send + Sync,\n    >,\n) -> Router {\n    build_router_with_state(\n        ProxyState::new(resolver)\n            .with_relogin_notify(on_chatgpt_unauthorized)\n            .with_chatgpt_mcp_auth_provider(chatgpt_mcp_auth_provider),\n    )\n}\n"""
    text = replace_once(text, anchor, replacement, label="server: router constructor")
write(path, text)


# ---------------------------------------------------------------------------
# crates/proxy/src/lib.rs
# ---------------------------------------------------------------------------
path = "crates/proxy/src/lib.rs"
text = read(path)
if "ChatgptMcpRelayAuth" not in text:
    text = replace_once(
        text,
        "pub use forward::{forward_handler, ProxyState};",
        "pub use forward::{forward_handler, ChatgptMcpRelayAuth, ProxyState}; // CAS-APPS-MCP-AUTH-R25-EXPORT",
        label="proxy lib: forward export",
    )
    text = replace_once(
        text,
        "pub use server::{build_router, build_router_with_relogin};",
        "pub use server::{build_router, build_router_with_relogin, build_router_with_relogin_and_mcp_auth};",
        label="proxy lib: server export",
    )
write(path, text)


# ---------------------------------------------------------------------------
# src-tauri/src/codex_real_account.rs
# ---------------------------------------------------------------------------
path = "src-tauri/src/codex_real_account.rs"
text = read(path)
if "CAS-APPS-MCP-AUTH-R25-SNAPSHOT" not in text:
    anchor = """pub fn active_is_real_chatgpt_now() -> bool {\n    CodexPaths::from_home_env()\n        .map(|p| active_is_real_chatgpt(&p))\n        .unwrap_or(false)\n}\n"""
    replacement = anchor + """\n// CAS-APPS-MCP-AUTH-R25-SNAPSHOT\n/// Return a credential snapshot for the hosted Apps MCP relay only when the\n/// *currently active* auth.json is a real, non-synthetic, unexpired ChatGPT login.\n/// Imported/pinned mirrors are intentionally not consulted: a dormant mirror must\n/// never be injected while the user deliberately runs an API-key/synthetic account.\n/// This function is read-only and never refreshes tokens (refresh ownership remains\n/// with Codex, avoiding single-use refresh_token races).\npub fn active_chatgpt_mcp_relay_auth() -> Option<(String, Option<String>)> {\n    let paths = CodexPaths::from_home_env().ok()?;\n    let value = read_auth(&paths.auth_json).ok()?;\n    chatgpt_mcp_relay_auth_from_value(&value, chrono::Utc::now().timestamp())\n}\n\nfn chatgpt_mcp_relay_auth_from_value(\n    value: &Value,\n    now_unix: i64,\n) -> Option<(String, Option<String>)> {\n    if value.get(\"cas_synthetic\").and_then(Value::as_bool) == Some(true) {\n        return None;\n    }\n    let parsed = parse_chatgpt_auth(value)?;\n    let access_token = value\n        .get(\"tokens\")\n        .and_then(|tokens| tokens.get(\"access_token\"))\n        .and_then(Value::as_str)?;\n    if access_token.trim().is_empty() || access_token_expired(access_token, now_unix) {\n        return None;\n    }\n    Some((access_token.to_owned(), parsed.account_id))\n}\n\n#[cfg(test)]\nmod apps_mcp_auth_r25_account_tests {\n    use super::*;\n    use base64::Engine as _;\n\n    fn jwt_with_exp(exp: i64) -> String {\n        let payload = serde_json::json!({ \"exp\": exp }).to_string();\n        let encoded = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(payload);\n        format!(\"x.{encoded}.y\")\n    }\n\n    fn auth(access_token: String) -> Value {\n        serde_json::json!({\n            \"auth_mode\": \"chatgpt\",\n            \"tokens\": {\n                \"access_token\": access_token,\n                \"refresh_token\": \"refresh\",\n                \"account_id\": \"acct-123\"\n            }\n        })\n    }\n\n    #[test]\n    fn snapshot_accepts_only_active_real_unexpired_chatgpt_auth() {\n        let now = 1_800_000_000i64;\n        let valid = auth(jwt_with_exp(now + 3600));\n        let snapshot = chatgpt_mcp_relay_auth_from_value(&valid, now).expect(\"valid auth\");\n        assert_eq!(snapshot.1.as_deref(), Some(\"acct-123\"));\n\n        let mut synthetic = valid.clone();\n        synthetic[\"cas_synthetic\"] = Value::Bool(true);\n        assert!(chatgpt_mcp_relay_auth_from_value(&synthetic, now).is_none());\n\n        let expired = auth(jwt_with_exp(now + EXPIRY_SKEW_SECONDS - 1));\n        assert!(chatgpt_mcp_relay_auth_from_value(&expired, now).is_none());\n\n        let mut api_key_mode = valid;\n        api_key_mode[\"auth_mode\"] = Value::String(\"apikey\".to_string());\n        assert!(chatgpt_mcp_relay_auth_from_value(&api_key_mode, now).is_none());\n    }\n}\n"""
    text = replace_once(text, anchor, replacement, label="real account: active helper")
write(path, text)


# ---------------------------------------------------------------------------
# src-tauri/src/proxy_runner.rs
# ---------------------------------------------------------------------------
path = "src-tauri/src/proxy_runner.rs"
text = read(path)
if "CAS-APPS-MCP-AUTH-R25-WIRE" not in text:
    text = replace_once(
        text,
        "use codex_app_transfer_proxy::{build_router_with_relogin, StaticResolver};",
        "use codex_app_transfer_proxy::{build_router_with_relogin_and_mcp_auth, ChatgptMcpRelayAuth, StaticResolver};",
        label="proxy runner: imports",
    )
    text = replace_once(
        text,
        """                    let router = build_router_with_relogin(\n                        resolver,\n                        Arc::new(crate::codex_real_account::mark_relogin_required_from_proxy),\n                    );""",
        """                    // CAS-APPS-MCP-AUTH-R25-WIRE\n                    // Resolve active ChatGPT auth lazily on every eligible MCP request so a\n                    // Codex-side token replacement is picked up without restarting Transfer.\n                    // The account helper itself rejects synthetic, API-key and expired states.\n                    let router = build_router_with_relogin_and_mcp_auth(\n                        resolver,\n                        Arc::new(crate::codex_real_account::mark_relogin_required_from_proxy),\n                        Arc::new(|| {\n                            crate::codex_real_account::active_chatgpt_mcp_relay_auth().map(\n                                |(access_token, account_id)| ChatgptMcpRelayAuth {\n                                    access_token,\n                                    account_id,\n                                },\n                            )\n                        }),\n                    );""",
        label="proxy runner: router wiring",
    )
write(path, text)


required = {
    "crates/proxy/src/forward.rs": [
        "CAS-APPS-MCP-AUTH-R25-STATE",
        "CAS-APPS-MCP-AUTH-R25-HELPERS",
        "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
        "CAS-APPS-MCP-AUTH-R25-401-FP",
    ],
    "crates/proxy/src/server.rs": ["CAS-APPS-MCP-AUTH-R25-ROUTER"],
    "crates/proxy/src/lib.rs": ["CAS-APPS-MCP-AUTH-R25-EXPORT"],
    "src-tauri/src/codex_real_account.rs": ["CAS-APPS-MCP-AUTH-R25-SNAPSHOT"],
    "src-tauri/src/proxy_runner.rs": ["CAS-APPS-MCP-AUTH-R25-WIRE"],
}
for rel, markers in required.items():
    content = read(rel)
    for marker in markers:
        if marker not in content:
            raise SystemExit(f"r25 materialization missing {marker} in {rel}")

print("r25 Apps MCP auth overlay: complete")
