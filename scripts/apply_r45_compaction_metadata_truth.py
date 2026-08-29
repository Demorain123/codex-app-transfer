from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R45-COMPACTION-METADATA-TRUTH"

text = FORWARD.read_text(encoding="utf-8")
if MARKER in text:
    print("r45 compaction metadata truth already applied")
    raise SystemExit(0)

start = text.find("fn value_has_compaction_marker_r45(value: &serde_json::Value) -> bool {")
end = text.find("fn model_equivalent_r45(left: &str, right: &str) -> bool {", start)
if start < 0 or end < 0:
    raise SystemExit("r45 metadata truth: compaction detector block anchors missing")

replacement = r'''// CAS-R45-COMPACTION-METADATA-TRUTH
// Real Codex Desktop traces carry the authoritative request role in
// x-codex-turn-metadata.request_kind. The beta feature remote_compaction_v2 is NOT a
// request-role signal: ordinary turns can carry that feature too. Therefore the proxy
// must never classify a request as compaction merely because a feature string exists.
fn turn_metadata_request_kind_r45(headers: &HeaderMap) -> Option<String> {
    let raw = headers
        .get("x-codex-turn-metadata")
        .and_then(|value| value.to_str().ok())?;
    let value = serde_json::from_str::<serde_json::Value>(raw).ok()?;
    value
        .get("request_kind")
        .and_then(|value| value.as_str())
        .map(str::to_owned)
}

fn value_has_compaction_marker_r45(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::Array(items) => items.iter().any(value_has_compaction_marker_r45),
        serde_json::Value::Object(map) => {
            let structural_type = map
                .get("type")
                .and_then(|value| value.as_str())
                .is_some_and(|kind| kind == "compaction");
            let structural_request_kind = map
                .get("request_kind")
                .and_then(|value| value.as_str())
                .is_some_and(|kind| kind == "compaction");
            structural_type
                || structural_request_kind
                || map.values().any(value_has_compaction_marker_r45)
        }
        // Strings such as remote_compaction_v2/local_compaction_v2 are feature names,
        // not proof that this specific request is the compaction request.
        _ => false,
    }
}

fn is_compaction_helper_request_r45(headers: &HeaderMap, body: &[u8]) -> bool {
    if turn_metadata_request_kind_r45(headers)
        .as_deref()
        .is_some_and(|kind| kind == "compaction")
    {
        return true;
    }
    serde_json::from_slice::<serde_json::Value>(body)
        .ok()
        .is_some_and(|value| value_has_compaction_marker_r45(&value))
}

'''
text = text[:start] + replacement + text[end:]

old_call = "let r45_compaction_helper = is_compaction_helper_request_r45(&body_bytes);"
new_call = "let r45_compaction_helper = is_compaction_helper_request_r45(&parts.headers, &body_bytes);"
if old_call not in text:
    raise SystemExit("r45 metadata truth: request classifier call anchor missing")
text = text.replace(old_call, new_call, 1)

old_test_start = text.find("    #[test]\n    fn r45_compaction_helper_detection_is_structural() {")
old_test_end = text.find("    #[test]\n    fn r45_semantic_terminal_detector_handles_chunk_boundaries() {", old_test_start)
if old_test_start < 0 or old_test_end < 0:
    raise SystemExit("r45 metadata truth: focused test anchors missing")

new_test = r'''    #[test]
    fn r45_compaction_helper_detection_is_structural() {
        let empty = HeaderMap::new();
        assert!(is_compaction_helper_request_r45(
            &empty,
            br#"{"model":"gpt-5.6-luna","input":[{"type":"compaction","encrypted_content":"x"}]}"#,
        ));
        assert!(!is_compaction_helper_request_r45(
            &empty,
            br#"{"model":"grok-4.6","input":[{"role":"user","content":"compaction"}]}"#,
        ));

        let mut compact_headers = HeaderMap::new();
        compact_headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"compaction","compaction":{"trigger":"auto","reason":"comp_hash_changed","implementation":"responses_compaction_v2","phase":"pre_turn","strategy":"memento"}}"#
                .parse()
                .unwrap(),
        );
        compact_headers.insert(
            "x-codex-beta-features",
            "remote_compaction_v2".parse().unwrap(),
        );
        assert!(is_compaction_helper_request_r45(
            &compact_headers,
            br#"{"model":"gpt-5.6-luna","input":[]}"#,
        ));

        let mut ordinary_turn_headers = HeaderMap::new();
        ordinary_turn_headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"turn","workspace_kind":"project"}"#
                .parse()
                .unwrap(),
        );
        // This reproduces the 2026-08-29 trace: normal Terra turns also advertise
        // remote_compaction_v2, so the feature flag alone must not classify the turn.
        ordinary_turn_headers.insert(
            "x-codex-beta-features",
            "remote_compaction_v2".parse().unwrap(),
        );
        assert!(!is_compaction_helper_request_r45(
            &ordinary_turn_headers,
            br#"{"model":"gpt-5.6-terra","input":[]}"#,
        ));
    }

'''
text = text[:old_test_start] + new_test + text[old_test_end:]

for invariant in (
    "CAS-R45-COMPACTION-METADATA-TRUTH",
    "x-codex-turn-metadata",
    "request_kind",
    "normal Terra turns also advertise",
    "is_compaction_helper_request_r45(&parts.headers, &body_bytes)",
):
    if invariant not in text:
        raise SystemExit(f"r45 metadata truth invariant missing: {invariant}")

FORWARD.write_text(text, encoding="utf-8")
print("R45 COMPACTION METADATA TRUTH PASS")
