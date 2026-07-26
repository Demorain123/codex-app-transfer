from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
forward = (ROOT / "crates/proxy/src/forward.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-LOG-PRIVACY-REVIEW
required = [
    "CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY",
    "CAS-APPS-MCP-AUTH-R25-LOG-SAFE-PATH-WIRE",
    "apps_mcp_safe_relay_log_path(client_path)",
    "[chatgpt-relay] {method} {relay_log_path} → {relay_log_upstream}",
    "[chatgpt-relay] resp {status} {relay_log_path}",
    "{relay_log_path}",
    "apps_mcp_auth_r25_relay_logs_strip_mcp_query_but_preserve_other_backend_paths",
    '"/backend-api/ps/mcp/.well-known"',
    '"/backend-api/ps/plugins/installed?view=all"',
]
for marker in required:
    if marker not in forward:
        raise SystemExit(f"r25 relay log privacy review: missing invariant: {marker}")

# The actual upstream request must still use the full original path/query. The patch
# is telemetry-only; changing the request URL would be a functional OAuth regression.
if 'let upstream = format!("https://chatgpt.com{client_path}");' not in forward:
    raise SystemExit("r25 relay log privacy review: real upstream URL no longer uses original client_path")

print("r25 Apps MCP relay telemetry query privacy review: PASS")
