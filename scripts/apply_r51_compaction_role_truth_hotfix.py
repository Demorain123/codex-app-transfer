from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"
MARKER = "CAS-R51-COMPACTION-ROLE-TRUTH"

text = FORWARD.read_text(encoding="utf-8")
if MARKER in text:
    print("r51 compaction-role truth hotfix already applied")
    raise SystemExit(0)

old = r'''fn is_compaction_helper_request_r45(headers: &HeaderMap, body: &[u8]) -> bool {
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
new = r'''// CAS-R51-COMPACTION-ROLE-TRUTH
// `x-codex-turn-metadata.request_kind`, when present, is authoritative in BOTH
// directions. r45 previously returned true for request_kind=compaction, but for
// request_kind=turn it fell through to a body scan. A normal turn that replayed an old
// `type=compaction` history item was therefore misclassified as a helper and rebound
// back to the previous effective model (for example Luna -> Grok), silently defeating
// an explicit model switch. Only fall back to body-shape detection when metadata is
// genuinely absent/unparseable (older Codex builds).
fn is_compaction_helper_request_r45(headers: &HeaderMap, body: &[u8]) -> bool {
    if let Some(kind) = turn_metadata_request_kind_r45(headers) {
        return kind == "compaction";
    }
    serde_json::from_slice::<serde_json::Value>(body)
        .ok()
        .is_some_and(|value| value_has_compaction_marker_r45(&value))
}
'''
if old not in text:
    raise SystemExit("r51 role-truth: final r45 classifier anchor missing")
text = text.replace(old, new, 1)

test_anchor = '''    #[test]
    fn r46_metadata_truth_keeps_feature_flag_out_of_request_role() {
'''
test = r'''    #[test]
    fn r51_explicit_turn_metadata_overrides_historical_compaction_items() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"turn","workspace_kind":"project"}"#
                .parse()
                .unwrap(),
        );
        // Exact regression from the r50 real-session test: after a successful compact,
        // the next ordinary turn legitimately replays a historical compaction item.
        // That history item must NOT turn the whole request into a compaction helper.
        assert!(!is_compaction_helper_request_r45(
            &headers,
            br#"{"model":"gpt-5.6-luna","input":[
                {"type":"compaction","encrypted_content":"old portable summary"},
                {"type":"message","role":"user","content":"continue on Luna"}
            ]}"#,
        ));

        headers.insert(
            "x-codex-turn-metadata",
            r#"{"request_kind":"compaction","compaction":{"trigger":"auto"}}"#
                .parse()
                .unwrap(),
        );
        assert!(is_compaction_helper_request_r45(
            &headers,
            br#"{"model":"gpt-5.6-luna","input":[]}"#,
        ));
    }

'''
if test_anchor not in text:
    raise SystemExit("r51 role-truth: r46 focused-test anchor missing")
text = text.replace(test_anchor, test + test_anchor, 1)

for marker in (
    "CAS-R51-COMPACTION-ROLE-TRUTH",
    "return kind == \"compaction\";",
    "r51_explicit_turn_metadata_overrides_historical_compaction_items",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
):
    if marker not in text:
        raise SystemExit(f"r51 role-truth invariant missing: {marker}")

FORWARD.write_text(text, encoding="utf-8")
print("R51 COMPACTION ROLE TRUTH HOTFIX PASS")
