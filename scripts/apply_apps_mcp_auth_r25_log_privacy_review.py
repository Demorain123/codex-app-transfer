from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
forward = (ROOT / "crates/proxy/src/forward.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-LOG-PRIVACY-REVIEW
required = [
    "CAS-APPS-MCP-AUTH-R25-LOG-QUERY-PRIVACY",
    "CAS-APPS-MCP-AUTH-R25-LOG-SAFE-PATH-WIRE",
    "CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY",
    "apps_mcp_safe_relay_log_path(client_path)",
    "apps_mcp_safe_reqwest_error(client_path, e)",
    "error.without_url()",
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

# All three reqwest failure entry points in the direct ChatGPT passthrough must pass
# through the path-scoped URL stripper before the common ForwardError logger sees them.
if forward.count("ForwardError::Upstream(apps_mcp_safe_reqwest_error(client_path, e))") < 3:
    raise SystemExit("r25 relay log privacy review: not all MCP reqwest error paths strip the URL")

print("r25 Apps MCP relay telemetry/error URL privacy review: PASS")
