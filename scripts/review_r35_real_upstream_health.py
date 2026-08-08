from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r35 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


telemetry = body("crates/proxy/src/telemetry.rs")
forward = body("crates/proxy/src/forward.rs")
health = body("src-tauri/src/admin/handlers/chain_health.rs")
zh = body("frontend/src/i18n/zh.ts")
en = body("frontend/src/i18n/en.ts")
version = body("SUB2API_GROK_COMPAT_VERSION.txt")

required = {
    "telemetry": [
        "raw_upstream_status",
        "client_status",
        "request_bytes",
        '"upstream_error"',
        "mark_client_status",
    ],
    "forward": [
        "telemetry.stats.record(status.is_success())",
        'format!("upstream status {}", status.as_u16())',
        'format!("client response status {}", response_plan.status.as_u16())',
        "record_subagent_failure_chain_result_r26(\n        subagent_failure_chain_ctx_r26.as_ref(),\n        status.as_u16(),",
        "request body: <redacted>",
    ],
    "health": [
        "structured-request-lifecycle",
        "raw_status={} client_status={}",
        "failure_streak",
        "retry_upload_bytes",
        "upstream_bad_gateway",
        "upstream_service_unavailable",
        "upstream_rate_limited",
        'row.name.eq_ignore_ascii_case("codex.exe")',
    ],
    "zh": ["账号池 / 上游（被动）"],
    "en": ["Account pool / Upstream (passive)"],
    "version": ["compat_revision=35", "app_version=2.4.5+35"],
}
for name, markers in required.items():
    source = {
        "telemetry": telemetry,
        "forward": forward,
        "health": health,
        "zh": zh,
        "en": en,
        "version": version,
    }[name]
    for marker in markers:
        if marker not in source:
            raise SystemExit(f"r35 review missing {name} marker: {marker}")

for forbidden in [
    'format!("upstream status {}", response_plan.status.as_u16())',
    "telemetry.stats.record(success);",
    "let req_snippet = bytes_preview(request_body",
    "evidence=proxy-log-order-best-effort",
]:
    if forbidden in forward or forbidden in health:
        raise SystemExit(f"r35 semantic/privacy regression: {forbidden}")

# r34 used all Electron ChatGPT processes as MCP roots. r35 must prefer codex.exe.
if 'row.name.eq_ignore_ascii_case("chatgpt.exe")\n                    || row.name.eq_ignore_ascii_case("codex.exe")' in health:
    raise SystemExit("r35 MCP root over-attribution regression")

print("r35 real upstream health review: PASS")
