from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
diag = (ROOT / "crates/proxy/src/diagnostics.rs").read_text(encoding="utf-8")

# CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-REVIEW
# The account identifier is user identity metadata. Because r25 can synthesize it,
# all local diagnostic serializers that can see the resulting headers must mask it.
required = [
    '"chatgpt-account-id" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-GENERIC',
    'norm == "chatgptaccountid" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-MCP',
    '"chatgpt-account-id" // CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-PASSTHROUGH',
    "CAS-APPS-MCP-AUTH-R25-TRACE-PRIVACY-TEST",
    "apps_mcp_auth_r25_chatgpt_account_id_is_redacted_in_all_diagnostic_header_paths",
    'assert_eq!(mcp["req_headers"]["ChatGPT-Account-ID"], "***")',
]
for marker in required:
    if marker not in diag:
        raise SystemExit(f"r25 trace privacy review: missing invariant: {marker}")

# Avoid a deceptive marker-only patch: require the three actual scrub functions to
# still exist and the test to call each public/private serializer used by the paths.
for fn in (
    "pub fn headers_to_json_redacted",
    "fn is_wide_extra_credential_header",
    "pub fn headers_to_json_passthrough",
):
    if fn not in diag:
        raise SystemExit(f"r25 trace privacy review: diagnostic scrub function missing: {fn}")
for call in (
    "headers_to_json_redacted(&h)",
    "headers_to_json_passthrough(&h)",
    "redact_mcp_value(&mut mcp)",
):
    if call not in diag:
        raise SystemExit(f"r25 trace privacy review: behavior test no longer exercises: {call}")

print("r25 Apps MCP diagnostic trace privacy review: PASS")
