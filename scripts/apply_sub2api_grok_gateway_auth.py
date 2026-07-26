from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
    print(f"[ok] patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[ok] {label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    print(f"[ok] {label}: applied")
    return text.replace(old, new, 1)


path = "crates/proxy/src/resolver.rs"
text = read(path)

old_helper = '''/// 判断 Bearer 是否是 OpenAI ChatGPT 的 access_token —— JWT(三段)且 payload 含
/// `https://api.openai.com/auth.chatgpt_account_id`。relay 模式(活动 auth.json 是真实
/// chatgpt)下 Codex 模型请求发此 token 到 proxy,`check_gateway` 据此放行(身份比静态
/// cas_ gateway key 更硬,且 `decide_provider` 不依赖 gateway key 即可按 active_provider
/// 转发)。验 claim 而非只看 JWT 格式,挡掉随机乱 token。
fn is_chatgpt_access_token(token: &str) -> bool {
    use base64::Engine;
    // JWT = header.payload.signature,正好三段且签名非空。
    let mut it = token.split('.');
    let payload = match (it.next(), it.next(), it.next(), it.next()) {
        (Some(_h), Some(p), Some(sig), None) if !sig.is_empty() && !p.is_empty() => p,
        _ => return false,
    };
    let Ok(raw) = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(payload) else {
        return false;
    };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else {
        return false;
    };
    v.get("https://api.openai.com/auth")
        .and_then(|a| a.get("chatgpt_account_id"))
        .and_then(serde_json::Value::as_str)
        .is_some_and(|s| !s.trim().is_empty())
}
'''

new_helper = '''/// 判断 Bearer 是否是 OpenAI ChatGPT 的 access_token。
///
/// CAS-SUB2API-GROK-COMPAT-HOOK: OpenAI 当前存在不携带
/// `chatgpt_account_id`、但仍是有效 ChatGPT 登录 token 的 JWT；例如
/// `https://api.openai.com/auth` 里只有 `user_id` + `organizations[].id`。
/// Real relay 模式会保留真实 ChatGPT auth.json，因此模型请求到本地 proxy 时可能
/// 带这种 JWT，而不是 cas_ gateway key。只认旧 claim 会把请求在到达 Sub2API 前
/// 错误拒绝成 `missing or invalid gateway api key`。
///
/// 这里仍要求三段 JWT + 可解码 JSON + OpenAI auth namespace 内存在账号/用户/组织
/// 身份字段；不退化成“任意三段 JWT 都放行”。proxy 只监听 127.0.0.1，gateway 本身
/// 也是防误调用而非远程安全边界（与现有 cas_ shape fallback 的设计一致）。
fn is_chatgpt_access_token(token: &str) -> bool {
    use base64::Engine;

    fn non_empty_str(v: Option<&serde_json::Value>) -> bool {
        v.and_then(serde_json::Value::as_str)
            .is_some_and(|s| !s.trim().is_empty())
    }

    // JWT = header.payload.signature,正好三段且签名非空。
    let mut it = token.split('.');
    let payload = match (it.next(), it.next(), it.next(), it.next()) {
        (Some(_h), Some(p), Some(sig), None) if !sig.is_empty() && !p.is_empty() => p,
        _ => return false,
    };
    let Ok(raw) = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(payload) else {
        return false;
    };
    let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else {
        return false;
    };
    let Some(auth) = v
        .get("https://api.openai.com/auth")
        .and_then(serde_json::Value::as_object)
    else {
        return false;
    };

    if non_empty_str(auth.get("chatgpt_account_id"))
        || non_empty_str(auth.get("chatgpt_user_id"))
        || non_empty_str(auth.get("user_id"))
    {
        return true;
    }

    auth.get("organizations")
        .and_then(serde_json::Value::as_array)
        .is_some_and(|orgs| {
            orgs.iter().any(|org| {
                org.as_object()
                    .is_some_and(|o| non_empty_str(o.get("id")))
            })
        })
}
'''

# rustfmt legitimately reformats the generated helper, so use semantic markers
# before falling back to exact first-install anchors. This makes repeated overlay
# application safe on generated branches and on Windows packaging runs.
helper_markers = (
    "CAS-SUB2API-GROK-COMPAT-HOOK: OpenAI 当前存在不携带",
    'non_empty_str(auth.get("user_id"))',
    'auth.get("organizations")',
)
if all(marker in text for marker in helper_markers):
    print("[ok] broaden valid ChatGPT JWT claim shapes: already applied (semantic)")
else:
    text = replace_once(text, old_helper, new_helper, "broaden valid ChatGPT JWT claim shapes")

old_test_tail = '''        // ⑤ 3 段 JWT 但 payload 无 chatgpt_account_id claim → 拒(pin 住 is_chatgpt_access_token
        //    的 claim 校验:gate 放宽后这是唯一剩下的判别逻辑,防未来回归成"任意 3 段 token 放行")
        let no_claim_payload =
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b"{\\\"sub\\\":\\\"x\\\"}");
        let no_claim = format!("Bearer eyJhbGciOiJub25lIn0.{no_claim_payload}.sig");
        let pnc = parts_with(&[("authorization", no_claim.as_str())]);
        assert!(
            matches!(
                r.resolve(&pnc, b"{}").unwrap_err(),
                ResolveError::Unauthorized
            ),
            "缺 chatgpt_account_id 的 3 段 JWT 不算 chatgpt token,应拒"
        );
'''

new_test_tail = '''        // ⑤ 当前 OpenAI 也会签发不含 chatgpt_account_id、仅含 user_id + organizations
        // 的有效 ChatGPT token。Real relay 必须放行，否则请求会在本地 resolver 就 401，
        // 根本到不了 Sub2API / Grok。
        let current_shape_payload = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(
            serde_json::to_vec(&serde_json::json!({
                "https://api.openai.com/auth": {
                    "groups": [],
                    "organizations": [{"id": "org-current", "is_default": true}],
                    "user_id": "user-current"
                }
            }))
            .unwrap(),
        );
        let current_shape =
            format!("Bearer eyJhbGciOiJub25lIn0.{current_shape_payload}.sig");
        let pcs = parts_with(&[("authorization", current_shape.as_str())]);
        assert!(
            r.resolve(&pcs, b"{}").is_ok(),
            "user_id/organizations 形态的有效 ChatGPT JWT 应被 Real relay 放行"
        );

        // ⑥ 3 段 JWT 但没有 OpenAI auth identity → 仍拒，防回归成“任意 JWT 放行”。
        let no_claim_payload =
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b"{\\\"sub\\\":\\\"x\\\"}");
        let no_claim = format!("Bearer eyJhbGciOiJub25lIn0.{no_claim_payload}.sig");
        let pnc = parts_with(&[("authorization", no_claim.as_str())]);
        assert!(
            matches!(
                r.resolve(&pnc, b"{}").unwrap_err(),
                ResolveError::Unauthorized
            ),
            "无 OpenAI auth identity 的 3 段 JWT 不算 ChatGPT token,应拒"
        );
'''

test_markers = (
    "current_shape_payload",
    "user_id/organizations 形态的有效 ChatGPT JWT 应被 Real relay 放行",
    "无 OpenAI auth identity 的 3 段 JWT 不算 ChatGPT token,应拒",
)
if all(marker in text for marker in test_markers):
    print("[ok] add current ChatGPT JWT regression test: already applied (semantic)")
else:
    text = replace_once(text, old_test_tail, new_test_tail, "add current ChatGPT JWT regression test")

write(path, text)
