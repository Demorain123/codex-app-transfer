from pathlib import Path

PATH = Path("crates/proxy/src/forward.rs")
MARKER = "CAS-SUB2API-OPENAI-CODEX-IDENTITY-HOOK"


def read() -> str:
    return PATH.read_text(encoding="utf-8")


def write(text: str) -> None:
    PATH.write_text(text, encoding="utf-8")
    print(f"[ok] patched {PATH}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


text = read()
if MARKER in text:
    print("[ok] Sub2API OpenAI Codex identity overlay already present; no-op")
    raise SystemExit(0)

helper_anchor = '''/// grok.com Web 后端反代必需 / 我们要独占注入的 header 名集合(见
/// `crates/adapters/src/grok_web/auth.rs::apply_grok_headers`)。
'''
helper_block = '''/// CAS-SUB2API-OPENAI-CODEX-IDENTITY-HOOK
///
/// Sub2API 的 OpenAI OAuth/Codex 账号可以启用 `codex_cli_only`。该门会检查真实
/// Codex 客户端的 User-Agent / originator，并且默认还会要求 x-codex-* 引擎指纹。
/// 上游 Transfer 的通用第三方-provider 策略会把这些身份头全部 strip，这对 Kimi 等
/// provider 是正确的，但对「Codex -> Transfer -> Sub2API -> OpenAI OAuth」会把一个
/// 真实 Codex 请求变成“非官方客户端”，Sub2API 因而返回 403:
/// `This account only allows Codex official clients`。
///
/// 只在用户显式开启 Sub2API Grok compat 的 Responses provider 上、且本次模型不是
/// grok-* 时保留最小官方身份集。Grok 请求继续沿用原 strip 策略，避免把 Codex 指纹
/// 泄漏到 xAI/Grok 路由；Authorization 永远不在保留集内，仍由 provider api_key 重写。
fn should_preserve_sub2api_codex_identity(
    provider: &codex_app_transfer_registry::Provider,
    body: &[u8],
) -> bool {
    if !provider.api_format.trim().eq_ignore_ascii_case("responses") {
        return false;
    }
    let enabled = provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false);
    if !enabled {
        return false;
    }
    let Some(model) = body_model(body) else {
        return false;
    };
    let model = model.trim().to_ascii_lowercase();
    !model.is_empty() && !model.starts_with("grok-")
}

fn is_sub2api_codex_identity_header(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    lower == "user-agent" || lower == "originator" || lower.starts_with("x-codex-")
}

#[cfg(test)]
mod sub2api_codex_identity_tests {
    use super::*;

    fn provider(compat: bool) -> codex_app_transfer_registry::Provider {
        serde_json::from_value(serde_json::json!({
            "id": "sub2api-test",
            "name": "sub2api",
            "baseUrl": "http://127.0.0.1:8089/v1",
            "authScheme": "bearer",
            "apiFormat": "responses",
            "apiKey": "sk-test",
            "models": {},
            "sub2apiGrokCompat": compat
        }))
        .unwrap()
    }

    #[test]
    fn preserves_official_codex_identity_for_sub2api_openai_models_only() {
        let p = provider(true);
        assert!(should_preserve_sub2api_codex_identity(
            &p,
            br#"{"model":"gpt-5.6-luna","input":[]}"#,
        ));
        assert!(should_preserve_sub2api_codex_identity(
            &p,
            br#"{"model":"o4-mini","input":[]}"#,
        ));
        assert!(!should_preserve_sub2api_codex_identity(
            &p,
            br#"{"model":"grok-4.5","input":[]}"#,
        ));
        assert!(!should_preserve_sub2api_codex_identity(
            &provider(false),
            br#"{"model":"gpt-5.6-luna","input":[]}"#,
        ));
    }

    #[test]
    fn only_minimal_codex_identity_headers_bypass_generic_strip() {
        assert!(is_sub2api_codex_identity_header("User-Agent"));
        assert!(is_sub2api_codex_identity_header("originator"));
        assert!(is_sub2api_codex_identity_header("x-codex-installation-id"));
        assert!(!is_sub2api_codex_identity_header("authorization"));
        assert!(!is_sub2api_codex_identity_header("chatgpt-account-id"));
        assert!(!is_sub2api_codex_identity_header("x-openai-foo"));
    }
}

'''
if helper_anchor not in text:
    raise SystemExit("anchor not found: insert Sub2API OpenAI identity helpers")
text = text.replace(helper_anchor, helper_block + helper_anchor, 1)
print("[ok] inserted Sub2API OpenAI identity helpers/tests")

flag_anchor = '''    let injects_grok_build_headers = matches!(resolved.auth_scheme, AuthScheme::GrokBuildOauth);
    for (name, value) in inbound_headers.iter() {
'''
flag_replacement = '''    let injects_grok_build_headers = matches!(resolved.auth_scheme, AuthScheme::GrokBuildOauth);
    // CAS-SUB2API-OPENAI-CODEX-IDENTITY-HOOK: for OpenAI-family requests routed through
    // the explicit Sub2API compat provider, preserve the real Codex client fingerprint so
    // Sub2API `codex_cli_only` accounts still recognize this as an official Codex request.
    let preserve_sub2api_codex_identity =
        should_preserve_sub2api_codex_identity(&resolved.provider, plan_body);
    for (name, value) in inbound_headers.iter() {
'''
text = replace_once(
    text,
    flag_anchor,
    flag_replacement,
    "derive per-request Sub2API Codex identity passthrough",
)

loop_anchor = '''        if is_hop_header(name.as_str()) || is_strip_on_forward(name.as_str()) {
            continue;
        }
'''
loop_replacement = '''        if is_hop_header(name.as_str()) {
            continue;
        }
        if is_strip_on_forward(name.as_str())
            && !(preserve_sub2api_codex_identity
                && is_sub2api_codex_identity_header(name.as_str()))
        {
            continue;
        }
'''
text = replace_once(
    text,
    loop_anchor,
    loop_replacement,
    "conditionally preserve official Codex identity headers",
)

write(text)
