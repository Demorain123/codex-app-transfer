//! [MOC-234/R70] responses passthrough 的 400 error-path 降级修复。
//!
//! ## 原始问题
//! Codex 工具续轮用 `previous_response_id` + **只发增量 input**(`function_call_output`),
//! 依赖上游按 prev_id 回查上一轮产生的 `function_call`。部分第三方 Responses 反代(如
//! new-api)在 `store:false` 下**不持久化自己的响应** → 续轮找不到 function_call → 400。
//!
//! ## r70 补充问题
//! Sub2API 某些历史会话失败时会把真实上游 400 折叠成固定 envelope:
//! `{"error":{"message":"Upstream request failed","type":"upstream_error"}}`。
//! 这会遮住 `invalid_encrypted_content` / 历史 provenance 等真实原因，使原先只看明确
//! orphan 文案的 one-shot recovery 永远不触发。r70 因此把这个**精确 envelope**也视为
//! “可尝试一次历史状态恢复”的候选，但仍要求 request 本身存在可安全改写的历史状态；
//! 普通 400 / 任意 upstream_error 不会触发。
//!
//! ## 降级原则
//! - 成功路径一律不改；只在上游已经明确返回 400 后进入。
//! - 优先使用 always-on 观测镜像沿 `previous_response_id` 拼完整历史。
//! - 镜像断链时，仅当当前请求本身看起来已携带足够历史状态(opaque encrypted state、
//!   大型 self-contained replay)才做 portable fallback：drop `previous_response_id` +
//!   去掉 opaque `encrypted_content`，保留普通 message / tool / plaintext summary。
//! - 调用方只会透明重发一次，绝不形成 retry loop。

use bytes::Bytes;
use serde_json::Value;

use crate::responses::global_passthrough_observe_store;

const ORPHAN_MARKER: &str = "No tool call found for function call output";
const MASKED_UPSTREAM_MESSAGE: &str = "Upstream request failed";
const MASKED_UPSTREAM_TYPE: &str = "upstream_error";
const PORTABLE_FALLBACK_MIN_BYTES: usize = 64 * 1024;

fn is_masked_sub2api_upstream_error(v: &Value) -> bool {
    let Some(error) = v.get("error") else {
        return false;
    };
    error.get("message").and_then(Value::as_str) == Some(MASKED_UPSTREAM_MESSAGE)
        && error.get("type").and_then(Value::as_str) == Some(MASKED_UPSTREAM_TYPE)
}

/// forward 层用：判断 400 是否值得进入**一次**历史状态 recovery。
///
/// 函数名为兼容 MOC-234 保留。现在只接受两类无歧义候选：
/// 1. 明确的 orphan function_call 文案；
/// 2. Sub2API 折叠后的精确 generic upstream_error envelope。
///
/// 第二类并不代表一定可修复；真正是否重发仍由 `rebuild_orphan_context_bytes` 对
/// request body 做严格 gate。没有可安全改写状态时返回 `None`，原 400 正常 surface。
pub fn is_orphan_function_call_error(error_body: &[u8]) -> bool {
    if let Ok(v) = serde_json::from_slice::<Value>(error_body) {
        let msg = v
            .get("error")
            .and_then(|e| e.get("message"))
            .and_then(Value::as_str)
            .or_else(|| v.get("message").and_then(Value::as_str))
            .unwrap_or("");
        if msg.contains(ORPHAN_MARKER) || is_masked_sub2api_upstream_error(&v) {
            return true;
        }
    }
    std::str::from_utf8(error_body)
        .map(|s| s.contains(ORPHAN_MARKER))
        .unwrap_or(false)
}

fn contains_encrypted_content(value: &Value) -> bool {
    match value {
        Value::Object(map) => {
            if map
                .get("encrypted_content")
                .is_some_and(|v| !v.is_null())
            {
                return true;
            }
            map.values().any(contains_encrypted_content)
        }
        Value::Array(items) => items.iter().any(contains_encrypted_content),
        _ => false,
    }
}

fn strip_encrypted_content(value: &mut Value) -> usize {
    match value {
        Value::Object(map) => {
            let mut removed = usize::from(map.remove("encrypted_content").is_some());
            for child in map.values_mut() {
                removed += strip_encrypted_content(child);
            }
            removed
        }
        Value::Array(items) => items.iter_mut().map(strip_encrypted_content).sum(),
        _ => 0,
    }
}

fn input_item_count(value: &Value) -> usize {
    value
        .get("input")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0)
}

fn previous_response_id(value: &Value) -> Option<String> {
    value
        .get("previous_response_id")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToOwned::to_owned)
}

/// forward 层用：400 后的一次性 portable recovery。
///
/// 先尝试 MOC-234 的完整链重建；如果镜像因为 proxy 重启/旧会话而断链，则只有在
/// request 本身具有“历史 replay”证据时才 fallback：
/// - 含 opaque `encrypted_content`；或
/// - body >= 64 KiB 且存在 `previous_response_id` 且 input 非空。
///
/// fallback 只做两件事：drop `previous_response_id`、递归去除 `encrypted_content`。
/// 普通 messages/tools/plaintext summaries 原样保留。没有发生任何实际改写则返回 None。
pub fn rebuild_orphan_context_bytes(body: &[u8]) -> Option<Bytes> {
    let mut v: Value = serde_json::from_slice(body).ok()?;
    let prev_id = previous_response_id(&v);
    let had_encrypted = contains_encrypted_content(&v);

    // 首选：观测镜像能拼出**完整链**，就 inline 完整历史；这是语义最完整的恢复。
    if let Some(prev_id) = prev_id.as_deref() {
        if let Some(mut history) = global_passthrough_observe_store().assemble_chain_complete(prev_id)
        {
            let current_input = v
                .get("input")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            history.extend(current_input);

            let obj = v.as_object_mut()?;
            obj.insert("input".to_owned(), Value::Array(history));
            obj.remove("previous_response_id");
            // 这是 400 recovery 路径。即使链里混有旧 auth/provider generation 的 opaque
            // reasoning，也只去掉不可移植 encrypted blob；plaintext summary / message 保留。
            strip_encrypted_content(&mut v);
            return serde_json::to_vec(&v).ok().map(Bytes::from);
        }
    }

    // 镜像断链：不允许对普通小增量 turn 猜测性重写。只有请求自己已经带有足够历史
    // 证据时才进入 portable fallback。19 MiB Goal old-session replay 会命中 size gate；
    // 较小但包含 encrypted_content 的旧 auth/provider replay 也会命中 encrypted gate。
    let self_contained_large_replay = prev_id.is_some()
        && input_item_count(&v) > 0
        && body.len() >= PORTABLE_FALLBACK_MIN_BYTES;
    if !had_encrypted && !self_contained_large_replay {
        return None;
    }

    let mut changed = false;
    if prev_id.is_some() {
        if let Some(obj) = v.as_object_mut() {
            changed |= obj.remove("previous_response_id").is_some();
        }
    }
    changed |= strip_encrypted_content(&mut v) > 0;

    if !changed {
        return None;
    }
    serde_json::to_vec(&v).ok().map(Bytes::from)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::responses::global_passthrough_observe_store;
    use serde_json::json;

    #[test]
    fn detects_orphan_and_exact_masked_upstream_error_only() {
        assert!(is_orphan_function_call_error(
            br#"{"error":{"message":"No tool call found for function call output with call_id call_X."}}"#
        ));
        assert!(is_orphan_function_call_error(
            b"data: No tool call found for function call output with call_id call_Y."
        ));
        assert!(is_orphan_function_call_error(
            br#"{"error":{"message":"Upstream request failed","type":"upstream_error"}}"#
        ));
        assert!(!is_orphan_function_call_error(
            br#"{"error":{"message":"Upstream request failed","type":"bad_request"}}"#
        ));
        assert!(!is_orphan_function_call_error(
            br#"{"error":{"message":"Invalid API key"}}"#
        ));
        assert!(!is_orphan_function_call_error(b"rate limited"));
    }

    #[test]
    fn rebuilds_full_context_from_observe_chain_and_drops_prev_id() {
        let store = global_passthrough_observe_store();
        store.record_turn(
            "rebuild_r1",
            None,
            vec![
                json!({"type":"message","role":"user","content":[{"type":"input_text","text":"do X"}]}),
                json!({"type":"function_call","name":"shell","arguments":"{}","call_id":"call_R1"}),
            ],
        );
        let body = json!({
            "model":"gpt-5.5","stream":true,"store":false,
            "previous_response_id":"rebuild_r1",
            "input":[{"type":"function_call_output","call_id":"call_R1","output":"done"}]
        });
        let out =
            rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap()).expect("应能重建");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        let input = rebuilt["input"].as_array().unwrap();
        assert_eq!(input.len(), 3, "应拼出完整历史 + 当前轮:{rebuilt}");
        assert_eq!(input[0]["role"], "user");
        assert_eq!(input[1]["type"], "function_call");
        assert_eq!(input[1]["call_id"], "call_R1");
        assert_eq!(input[2]["type"], "function_call_output");
        assert_eq!(input[2]["call_id"], "call_R1");
        assert!(rebuilt.get("previous_response_id").is_none());
    }

    #[test]
    fn old_encrypted_replay_falls_back_without_observe_chain() {
        let body = json!({
            "model":"gpt-5.6-luna",
            "previous_response_id":"old_missing_generation",
            "input":[
                {"type":"reasoning","encrypted_content":"opaque-old-account","summary":[{"type":"summary_text","text":"portable summary"}]},
                {"type":"message","role":"user","content":[{"type":"input_text","text":"continue"}]}
            ]
        });
        let out = rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap())
            .expect("encrypted old replay should have portable fallback");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        assert!(rebuilt.get("previous_response_id").is_none());
        assert!(rebuilt["input"][0].get("encrypted_content").is_none());
        assert_eq!(rebuilt["input"][0]["summary"][0]["text"], "portable summary");
        assert_eq!(rebuilt["input"][1]["role"], "user");
    }

    #[test]
    fn large_self_contained_replay_can_drop_missing_prev_id() {
        let big = "x".repeat(PORTABLE_FALLBACK_MIN_BYTES + 1024);
        let body = json!({
            "previous_response_id":"old_missing_large",
            "input":[{"type":"message","role":"user","content":[{"type":"input_text","text":big}]}]
        });
        let out = rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap())
            .expect("large replay should recover even when observe chain is gone");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        assert!(rebuilt.get("previous_response_id").is_none());
        assert_eq!(rebuilt["input"][0]["role"], "user");
    }

    #[test]
    fn small_unknown_missing_chain_still_refuses_guessy_rewrite() {
        let body = json!({
            "previous_response_id":"never_recorded_xyz",
            "input":[{"type":"function_call_output","call_id":"c","output":"o"}]
        });
        assert!(rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap()).is_none());
    }

    #[test]
    fn no_rebuild_without_prev_id_or_portable_risk() {
        let body = json!({"input":[{"type":"message","role":"user","content":"hi"}]});
        assert!(rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap()).is_none());
    }
}
