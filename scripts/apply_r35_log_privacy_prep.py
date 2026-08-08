from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r35_real_upstream_health.py"
body = TARGET.read_text(encoding="utf-8")

MARKER = "diag_replacement = r'''fn log_upstream_error_diag("
if MARKER in body:
    print("r35 log privacy prep: already patched")
    raise SystemExit(0)

start = body.find("    old_diag = \"\"\"")
if start < 0:
    raise SystemExit("r35 log privacy prep: old_diag block not found")
end_marker = '    forward = replace_once(forward, old_diag, new_diag, "routine upstream error log privacy")\n'
end = body.find(end_marker, start)
if end < 0:
    raise SystemExit("r35 log privacy prep: old replace call not found")
end += len(end_marker)

replacement = r"""    diag_replacement = r'''fn log_upstream_error_diag(
    telemetry: &crate::telemetry::ProxyTelemetry,
    status: StatusCode,
    upstream_url: &str,
    outbound_headers: &reqwest::header::HeaderMap,
    request_body: &Bytes,
    response_body: &Bytes,
) {
    // CAS-R35-REAL-UPSTREAM-HEALTH-LOG-PRIVACY
    // Error diagnostics often happen on the most sensitive requests. Keep only
    // request size; never persist prompt/tool/SSH contents in the routine log.
    const RESP_MAX: usize = 2048;
    let resp_snippet = bytes_preview(response_body, RESP_MAX);
    let headers_dump = format_headers_redacted(outbound_headers);
    telemetry.logs.add(
        "ERROR",
        format!(
            "upstream error diag {} {}\\
  → outbound headers: [{}]\\
  → request body: <redacted> ({} bytes)\\
  ← response body ({} bytes): {}",
            status.as_u16(),
            upstream_url,
            headers_dump,
            request_body.len(),
            response_body.len(),
            resp_snippet,
        ),
    );
}'''
    forward = replace_function(
        forward,
        "fn log_upstream_error_diag(",
        diag_replacement,
        "routine upstream error log privacy",
    )
"""

TARGET.write_text(body[:start] + replacement + body[end:], encoding="utf-8")
print("r35 log privacy prep: PATCHED")
