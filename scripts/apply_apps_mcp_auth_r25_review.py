from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


forward = read("crates/proxy/src/forward.rs")
account = read("src-tauri/src/codex_real_account.rs")
runner = read("src-tauri/src/proxy_runner.rs")
server = read("crates/proxy/src/server.rs")

# CAS-APPS-MCP-AUTH-R25-REVIEW
# Deep fail-closed review gates. These are intentionally semantic-ish string/regex
# assertions rather than source rewrites: if upstream drift changes a security boundary,
# packaging must stop and require a human review instead of guessing.

# 1) Scope must remain exact: only canonical /backend-api/ps/mcp and descendants.
if 'p == "/backend-api/ps/mcp" || p.starts_with("/backend-api/ps/mcp/")' not in forward:
    raise SystemExit("r25 review: MCP diagnostic allowlist widened or missing")
if "headers.contains_key(http::header::AUTHORIZATION)" not in forward:
    raise SystemExit("r25 review: inbound Authorization no-overwrite guard missing")
if '"/backend-api/ps/mcpish"' not in forward or '"/backend-api/ps/plugins/installed"' not in forward:
    raise SystemExit("r25 review: negative allowlist regressions missing")
if '"/backend-api/ps/mcp/../plugins/installed"' not in forward or '%2e%2e/plugins/installed' not in forward:
    raise SystemExit("r25 review: canonical-path escape regressions missing")
if 'reqwest::Url::parse(&format!("https://chatgpt.com{path}"))' not in forward:
    raise SystemExit("r25 review: MCP auth allowlist is not checked on canonical outbound URL")
if 'url.host_str() != Some("chatgpt.com")' not in forward or 'url.scheme() != "https"' not in forward:
    raise SystemExit("r25 review: canonical URL host/scheme pin missing")

# 2) Synthetic mode must be a hard stop in both the relay and the auth source.
if "fake_account_mode_enabled()" not in forward or "reason=synthetic_account" not in forward:
    raise SystemExit("r25 review: synthetic relay hard-stop missing")
if 'value.get("cas_synthetic").and_then(Value::as_bool) == Some(true)' not in account:
    raise SystemExit("r25 review: active auth snapshot does not reject synthetic account")

# 3) Auth source must be the active auth.json only. Do not silently fall back to
# imported/pinned mirrors when the user intentionally runs API-key/synthetic mode.
snapshot_match = re.search(
    r"pub fn active_chatgpt_mcp_relay_auth\(\).*?\n}\n",
    account,
    re.S,
)
if not snapshot_match:
    raise SystemExit("r25 review: active_chatgpt_mcp_relay_auth missing")
snapshot_body = snapshot_match.group(0)
for forbidden in ("locate_chatgpt_tokens", "locate_valid_chatgpt_tokens", "imported_mirror_path"):
    if forbidden in snapshot_body:
        raise SystemExit(f"r25 review: dormant credential fallback leaked into MCP auth source: {forbidden}")
if "read_auth(&paths.auth_json)" not in snapshot_body:
    raise SystemExit("r25 review: active auth.json is no longer the credential source")

# 4) Require real ChatGPT auth mode + refresh token + local expiry check through
# parse_chatgpt_auth/access_token_expired. This avoids injecting API-key or stale tokens.
helper_match = re.search(
    r"fn chatgpt_mcp_relay_auth_from_value\(.*?\n}\n",
    account,
    re.S,
)
if not helper_match:
    raise SystemExit("r25 review: snapshot parser missing")
helper = helper_match.group(0)
for required in ("parse_chatgpt_auth(value)?", "access_token_expired(access_token, now_unix)"):
    if required not in helper:
        raise SystemExit(f"r25 review: credential validity gate missing: {required}")

# 5) The callback must be lazy per request, not a token captured at proxy startup.
if "Arc::new(||" not in runner or "active_chatgpt_mcp_relay_auth()" not in runner:
    raise SystemExit("r25 review: MCP auth provider is not lazy")
if "ChatgptMcpRelayAuth {" not in runner:
    raise SystemExit("r25 review: proxy runner auth snapshot wiring missing")

# 6) Inject only Authorization + optional ChatGPT-Account-ID. No Cookie, refresh_token,
# provider key, or other ambient credentials may be synthesized.
rehydrate_match = re.search(
    r"// CAS-APPS-MCP-AUTH-R25-REHYDRATE.*?\n\s*if !body\.is_empty\(\)",
    forward,
    re.S,
)
if not rehydrate_match:
    raise SystemExit("r25 review: rehydrate block missing")
rehydrate = rehydrate_match.group(0)
for forbidden in ("cookie", "refresh_token", "x-api-key", "api-key"):
    if forbidden in rehydrate.lower():
        raise SystemExit(f"r25 review: forbidden credential/header in rehydrate block: {forbidden}")
for required in ("reqwest::header::AUTHORIZATION", '"chatgpt-account-id"'):
    if required not in rehydrate:
        raise SystemExit(f"r25 review: required minimal identity header missing: {required}")

# 7) 401 revocation correlation must use the actual outbound headers. Otherwise an
# injected bearer would be recorded as fingerprint=0 and stale-token self-heal breaks.
if "authorization_token_fingerprint(&outbound_headers_snapshot)" not in forward:
    raise SystemExit("r25 review: 401 revocation fingerprint still uses authless inbound headers")

# 8) No credential values in structured logs. Logs may state presence/action only.
for line in forward.splitlines():
    if "[apps-mcp-auth]" in line and any(secret in line for secret in ("access_token", "authorization=", "account_id={")):
        raise SystemExit(f"r25 review: credential-like value in Apps MCP log line: {line.strip()}")

# 9) Preserve existing router API and add a separate constructor; this avoids forcing
# tests/proxy-only consumers to gain desktop-auth dependencies.
if "pub fn build_router_with_relogin(" not in server:
    raise SystemExit("r25 review: legacy build_router_with_relogin was removed")
if "pub fn build_router_with_relogin_and_mcp_auth(" not in server:
    raise SystemExit("r25 review: r25 router constructor missing")

print("r25 deep self-review gates: PASS")
