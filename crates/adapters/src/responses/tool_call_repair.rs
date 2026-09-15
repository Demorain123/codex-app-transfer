//! [MOC-234/R70] Responses passthrough 的 400 error-path 历史兼容修复。
//!
//! ## 原始问题
//! Codex 工具续轮可用 `previous_response_id` + 增量 `input`，依赖上游按 prev_id
//! 回查上一轮状态。部分第三方 Responses 反代在 `store:false` 下不持久化自己的响应，
//! 会让续轮找不到先前 tool call 而 400。
//!
//! ## r70 进一步覆盖的旧历史问题
//! Sub2API 会把若干真实上游 400 折叠成很短的 envelope，例如：
//! `{"error":{"message":"Upstream request failed","type":"upstream_error"}}`，以及部分
//! `{"error":{"message":"Upstream rejected the request","type":"invalid_request_error"}}`。
//! 这会遮住 `invalid_encrypted_content`、旧 compaction / reasoning、旧 tool-call schema
//! 等真实原因。
//!
//! OpenAI/Codex 的公开故障报告还表明：
//! - reasoning / compaction 的 `encrypted_content` 不是跨模型/跨密钥代际可移植状态；
//! - `compaction` item 没有 encrypted payload 后本身不再是合法可重放 item，不能只删字段；
//! - 旧 `function_call` / `function_call_output` 在序列化时可能带入非空 `content`，触发
//!   Responses schema 的 `array_above_max_length`。
//!
//! 因此这里仍坚持“成功路径零改写”，只在已经拿到 400 后做一次 portable repair：
//! 1. 优先用 always-on 会话镜像补齐 `previous_response_id` 历史；
//! 2. drop prev_id；
//! 3. drop 不可移植 compaction；reasoning 保留 summary，但去掉 opaque encrypted/content；
//! 4. 对旧 function-call item 只去掉 schema-invalid 的非空 `content`，不盲目删 tool call；
//! 5. 调用方最多透明重发一次，绝不形成 retry loop。

use bytes::Bytes;
use serde_json::Value;

use crate::responses::global_passthrough_observe_store;

const ORPHAN_MARKER: &str = "No tool call found for function call output";
const MASKED_UPSTREAM_MESSAGE: &str = "Upstream request failed";
const MASKED_UPSTREAM_TYPE: &str = "upstream_error";
const MASKED_INVALID_MESSAGE: &str = "Upstream rejected the request";
const MASKED_INVALID_TYPE: &str = "invalid_request_error";
const PORTABLE_FALLBACK_MIN_BYTES: usize = 64 * 1024;

fn error_pair(v: &Value) -> (Option<&str>, Option<&str>) {
    let error = v.get("error");
    let message = error
        .and_then(|e| e.get("message"))
        .and_then(Value::as_str)
        .or_else(|| v.get("message").and_then(Value::as_str));
    let kind = error
        .and_then(|e| e.get("type"))
        .and_then(Value::as_str)
        .or_else(|| v.get("type").and_then(Value::as_str));
    (message, kind)
}

fn is_masked_historical_400(v: &Value) -> bool {
    let (message, kind) = error_pair(v);
    matches!(
        (message, kind),
        (Some(MASKED_UPSTREAM_MESSAGE), Some(MASKED_UPSTREAM_TYPE))
            | (Some(MASKED_INVALID_MESSAGE), Some(MASKED_INVALID_TYPE))
    )
}

/// forward 层用：判断 400 是否值得进入**一次**历史状态 recovery。
///
/// 函数名为兼容 MOC-234 保留。这里只认：
/// 1. 明确的 orphan function_call 文案；
/// 2. Sub2API 已知的两个精确 masked envelope。
///
/// 命中 envelope 不代表一定重发；真正是否有可安全改写的历史状态仍由
/// `rebuild_orphan_context_bytes` 严格 gate。普通 400 不会被泛化重试。
pub fn is_orphan_function_call_error(error_body: &[u8]) -> bool {
    if let Ok(v) = serde_json::from_slice::<Value>(error_body) {
        let (message, _) = error_pair(&v);
        if message.is_some_and(|msg| msg.contains(ORPHAN_MARKER)) || is_masked_historical_400(&v) {
            return true;
        }
    }
    std::str::from_utf8(error_body)
        .map(|s| s.contains(ORPHAN_MARKER))
        .unwrap_or(false)
}

fn content_is_nonempty(value: Option<&Value>) -> bool {
    match value {
        Some(Value::Array(items)) => !items.is_empty(),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Null) | None => false,
        Some(_) => true,
    }
}

/// 只识别已经在公开 Codex/Responses 故障中证实的“历史不可移植 / schema 迁移”风险。
/// 这既是 fallback gate，也避免对任意 generic 400 猜测性改写。
fn has_portable_history_hazard(value: &Value) -> bool {
    match value {
        Value::Object(map) => {
            let item_type = map.get("type").and_then(Value::as_str);
            if map.contains_key("encrypted_content") {
                return true;
            }
            if item_type == Some("context_compaction") {
                return true;
            }
            if matches!(
                item_type,
                Some("reasoning") | Some("function_call") | Some("function_call_output")
            ) && content_is_nonempty(map.get("content"))
            {
                return true;
            }
            map.values().any(has_portable_history_hazard)
        }
        Value::Array(items) => items.iter().any(has_portable_history_hazard),
        _ => false,
    }
}

/// 把一次已经失败的历史 replay 降级成“可移植历史”。返回实际改写项数。
///
/// 重要：
/// - `compaction` 的 encrypted payload 是 item 本体，删字段后会留下无效 item，所以整项 drop；
/// - `reasoning` 尽量保留 `summary`，只删跨代 opaque state / 旧 reasoning content；
/// - `function_call` 仍是 Responses API 的合法类型，绝不能因为它“旧”就全删；这里只删
///   已知会触发 maxItems=0 的非空 `content` 字段。
fn sanitize_portable_history(value: &mut Value) -> usize {
    match value {
        Value::Array(items) => {
            let mut changed = 0usize;
            let mut i = 0usize;
            while i < items.len() {
                let item_type = items[i].get("type").and_then(Value::as_str);
                let drop_item = item_type == Some("context_compaction")
                    || (item_type == Some("compaction")
                        && items[i].get("encrypted_content").is_some());
                if drop_item {
                    items.remove(i);
                    changed += 1;
                    continue;
                }
                changed += sanitize_portable_history(&mut items[i]);
                i += 1;
            }
            changed
        }
        Value::Object(map) => {
            let mut changed = 0usize;
            let item_type = map
                .get("type")
                .and_then(Value::as_str)
                .map(ToOwned::to_owned);

            match item_type.as_deref() {
                Some("reasoning") => {
                    changed += usize::from(map.remove("encrypted_content").is_some());
                    if content_is_nonempty(map.get("content")) {
                        map.remove("content");
                        changed += 1;
                    }
                }
                Some("function_call") | Some("function_call_output") => {
                    // 当前 Responses schema 仍支持 function_call；只清除已知非法的旧 serializer
                    // 附加 content，保留 name/arguments/call_id/output。
                    if content_is_nonempty(map.get("content")) {
                        map.remove("content");
                        changed += 1;
                    }
                    // 某些旧历史还把 opaque 字段挂在 tool item 上，错误路径也一并剥离。
                    changed += usize::from(map.remove("encrypted_content").is_some());
                }
                _ => {
                    // 其他 item 若带 opaque encrypted state，也不能跨 provider/key generation。
                    changed += usize::from(map.remove("encrypted_content").is_some());
                }
            }

            for child in map.values_mut() {
                changed += sanitize_portable_history(child);
            }
            changed
        }
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
/// 首选从镜像补齐完整链；镜像断链时，仅在 request 自己包含已知 portability hazard，
/// 或明显是带 `previous_response_id` 的大型 self-contained replay 时才 fallback。
/// 没有发生任何实际改写则返回 None。
pub fn rebuild_orphan_context_bytes(body: &[u8]) -> Option<Bytes> {
    let mut v: Value = serde_json::from_slice(body).ok()?;
    let prev_id = previous_response_id(&v);
    let had_portability_hazard = has_portable_history_hazard(&v);

    // 首选：观测镜像能拼出完整链，就 inline 完整历史。
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
            sanitize_portable_history(&mut v);
            return serde_json::to_vec(&v).ok().map(Bytes::from);
        }
    }

    // 镜像断链：只认已知历史风险或“prev_id + >=64KiB + 非空 input”的大型 replay。
    let self_contained_large_replay = prev_id.is_some()
        && input_item_count(&v) > 0
        && body.len() >= PORTABLE_FALLBACK_MIN_BYTES;
    if !had_portability_hazard && !self_contained_large_replay {
        return None;
    }

    let mut changed = 0usize;
    if prev_id.is_some() {
        if let Some(obj) = v.as_object_mut() {
            changed += usize::from(obj.remove("previous_response_id").is_some());
        }
    }
    changed += sanitize_portable_history(&mut v);

    if changed == 0 {
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
    fn detects_only_known_historical_400_envelopes() {
        assert!(is_orphan_function_call_error(
            br#"{"error":{"message":"No tool call found for function call output with call_id call_X."}}"#
        ));
        assert!(is_orphan_function_call_error(
            b"data: No tool call found for function call output with call_id call_Y."
        ));
        assert!(is_orphan_function_call_error(
            br#"{"error":{"message":"Upstream request failed","type":"upstream_error"}}"#
        ));
        assert!(is_orphan_function_call_error(
            br#"{"error":{"message":"Upstream rejected the request","type":"invalid_request_error"}}"#
        ));
        assert!(!is_orphan_function_call_error(
            br#"{"error":{"message":"Upstream request failed","type":"bad_request"}}"#
        ));
        assert!(!is_orphan_function_call_error(
            br#"{"error":{"message":"Invalid API key","type":"invalid_request_error"}}"#
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
    fn old_encrypted_reasoning_keeps_summary_but_drops_opaque_state() {
        let body = json!({
            "model":"gpt-5.6-luna",
            "previous_response_id":"old_missing_generation",
            "input":[
                {"type":"reasoning","id":"rs_old","encrypted_content":"opaque-old-account","summary":[{"type":"summary_text","text":"portable summary"}]},
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
    fn stale_compaction_is_dropped_instead_of_left_invalid() {
        let body = json!({
            "input":[
                {"type":"compaction","id":"cmp_old","encrypted_content":"ocx1:old-key"},
                {"type":"message","role":"user","content":[{"type":"input_text","text":"continue"}]}
            ]
        });
        let out = rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap())
            .expect("stale compaction is a known portability hazard");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        let input = rebuilt["input"].as_array().unwrap();
        assert_eq!(input.len(), 1);
        assert_eq!(input[0]["type"], "message");
    }

    #[test]
    fn legacy_reasoning_null_encryption_and_content_are_sanitized() {
        let body = json!({
            "input":[
                {"type":"reasoning","id":"rs_old","encrypted_content":null,"content":[{"type":"reasoning_text","text":"old"}],"summary":[{"type":"summary_text","text":"keep me"}]},
                {"type":"message","role":"user","content":[{"type":"input_text","text":"continue"}]}
            ]
        });
        let out = rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap())
            .expect("legacy reasoning shape should be repairable");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        assert!(rebuilt["input"][0].get("encrypted_content").is_none());
        assert!(rebuilt["input"][0].get("content").is_none());
        assert_eq!(rebuilt["input"][0]["summary"][0]["text"], "keep me");
    }

    #[test]
    fn legacy_function_call_nonempty_content_is_removed_but_call_is_kept() {
        let body = json!({
            "input":[
                {"type":"function_call","name":"shell","arguments":"{}","call_id":"call_old","content":[{"type":"output_text","text":"serializer artifact"}]},
                {"type":"function_call_output","call_id":"call_old","output":"done","content":[{"type":"input_text","text":"serializer artifact"}]},
                {"type":"message","role":"user","content":[{"type":"input_text","text":"continue"}]}
            ]
        });
        let out = rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap())
            .expect("legacy function-call content is a known schema hazard");
        let rebuilt: Value = serde_json::from_slice(&out).unwrap();
        assert_eq!(rebuilt["input"][0]["type"], "function_call");
        assert_eq!(rebuilt["input"][0]["call_id"], "call_old");
        assert!(rebuilt["input"][0].get("content").is_none());
        assert_eq!(rebuilt["input"][1]["type"], "function_call_output");
        assert_eq!(rebuilt["input"][1]["output"], "done");
        assert!(rebuilt["input"][1].get("content").is_none());
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
    fn masked_invalid_request_without_history_hazard_does_not_force_retry() {
        let body = json!({"input":[{"type":"message","role":"user","content":"hi"}]});
        assert!(rebuild_orphan_context_bytes(&serde_json::to_vec(&body).unwrap()).is_none());
    }
}
