from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
R43_MARKER = "CAS-R43-REWRITE-HEALTH-MCP"
PREP_MARKER = "CAS-R43-REPLAY-PREFLIGHT-LATEST-LINEAGE"

text = CHAIN.read_text(encoding="utf-8")
if R43_MARKER in text:
    print("r43 replay preflight: r43 health already materialized")
    raise SystemExit(0)

# apply_r43_rewrite_health.py intentionally replaces the r42 failure-selection block
# with latest-lineage-wins semantics. Older r42 replay stacks can differ only in
# whitespace / intermediate formatting here, making an exact whole-block anchor brittle.
# Canonicalize ONLY that block by semantic boundaries immediately before r43 applies.
fn_start = text.find("fn fault_attribution_layer_r37(")
if fn_start < 0:
    raise SystemExit("r43 replay preflight: fault_attribution_layer_r37 missing")
records_start = text.find(
    "    let records = proxy_telemetry().lifecycles.snapshot();",
    fn_start,
)
if records_start < 0:
    raise SystemExit("r43 replay preflight: lifecycle records anchor missing")
if_record = text.find("    if let Some(record) = failed {", records_start)
if if_record < 0:
    raise SystemExit("r43 replay preflight: failed-record boundary missing")

canonical = '''    let records = proxy_telemetry().lifecycles.snapshot();
    let now_ms = Local::now().timestamp_millis();
    let cutoff = now_ms.saturating_sub(30 * 60 * 1000);
    let failed = records.iter().rev().find(|record| {
        record.accepted_at_ms >= cutoff
            && (record
                .raw_upstream_status
                .is_some_and(|status| status >= 400)
                || record
                    .terminal
                    .as_deref()
                    .is_some_and(|value| value == "upstream_error" || value.starts_with("failed:")))
    });
'''

current = text[records_start:if_record]
if current == canonical:
    print("r43 replay preflight: latest-lineage source anchor already canonical")
    raise SystemExit(0)

# Refuse to normalize a block that already appears to contain newer semantics. This
# preflight exists only to bridge r42 source-shape drift, not to erase real behavior.
for forbidden in (
    "CAS-R43-REWRITE-LATEST-LINEAGE-WINS",
    "latest_by_lineage",
    "lifecycle_failed_r43",
):
    if forbidden in current:
        raise SystemExit(
            f"r43 replay preflight: refusing to overwrite newer lineage logic: {forbidden}"
        )

text = text[:records_start] + canonical + text[if_record:]
# A source comment outside the exact replacement block makes the preflight auditable
# without changing the anchor expected by apply_r43_rewrite_health.py.
marker_anchor = "fn fault_attribution_layer_r37(\n"
if PREP_MARKER not in text:
    text = text.replace(
        marker_anchor,
        f"// {PREP_MARKER}\n" + marker_anchor,
        1,
    )

CHAIN.write_text(text, encoding="utf-8")
print("R43 REPLAY PREFLIGHT LATEST-LINEAGE PASS")
