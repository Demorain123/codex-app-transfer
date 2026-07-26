from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
forward = (ROOT / "crates/proxy/src/forward.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-REDIRECT-REVIEW
# Fail closed if a later upstream/replay change weakens the custom identity-header
# redirect boundary introduced by r25.
required = [
    "CAS-APPS-MCP-AUTH-R25-REDIRECT-HELPER",
    "CAS-APPS-MCP-AUTH-R25-REDIRECT",
    'origin.scheme() == "https"',
    'origin.host_str() == Some("chatgpt.com")',
    'next.scheme() == "https"',
    'next.host_str() == Some("chatgpt.com")',
    "next.port_or_known_default() == origin.port_or_known_default()",
    "Apps MCP cross-origin redirect blocked",
    "authorization.set_sensitive(true); // CAS-APPS-MCP-AUTH-R25-BEARER-SENSITIVE",
    "value.set_sensitive(true); // CAS-APPS-MCP-AUTH-R25-ACCOUNT-SENSITIVE",
    "CAS-APPS-MCP-AUTH-R25-SENSITIVITY-TEST",
    "synthesized_identity_never_crosses_origin_but_other_paths_keep_old_policy",
]
for marker in required:
    if marker not in forward:
        raise SystemExit(f"r25 redirect review: missing security invariant: {marker}")

# The redirect restriction must remain scoped to the Apps MCP origin. A global
# same-origin-only policy would be an unrelated behavioural regression for third-party
# providers and other ChatGPT backend traffic.
if 'origin.path() == "/backend-api/ps/mcp"' not in forward or 'origin.path().starts_with("/backend-api/ps/mcp/")' not in forward:
    raise SystemExit("r25 redirect review: Apps MCP origin path scope missing")
if "if !origin_is_apps_mcp" not in forward or "return true;" not in forward:
    raise SystemExit("r25 redirect review: non-MCP redirect behaviour is no longer explicitly preserved")

print("r25 Apps MCP redirect/privacy review: PASS")
