from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
diag = (ROOT / "crates/proxy/src/diagnostics.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY-REVIEW
required = [
    "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY",
    "fn apps_mcp_safe_trace_route(raw: &str) -> String",
    'url.host_str() == Some("chatgpt.com")',
    "url.set_query(None)",
    "url.set_fragment(None)",
    "apps_mcp_safe_trace_route(input.client_path)",
    "apps_mcp_safe_trace_route(input.upstream_url)",
    "CAS-APPS-MCP-AUTH-R25-TRACE-QUERY-PRIVACY-TEST",
    "apps_mcp_auth_r25_trace_omits_mcp_oauth_query_state_without_changing_other_paths",
    'assert!(other.contains("state=diagnostic-state"))',
    'assert!(other.contains("code=***"))',
]
for marker in required:
    if marker not in diag:
        raise SystemExit(f"r25 trace query privacy review: missing invariant: {marker}")

# Scope must stay narrow: non-MCP values still flow through the pre-existing selective
# credential redactor rather than losing all query data globally.
if "redact_credential_params(raw).0" not in diag:
    raise SystemExit("r25 trace query privacy review: non-MCP fallback no longer uses existing redactor")

print("r25 Apps MCP trace OAuth query privacy review: PASS")
