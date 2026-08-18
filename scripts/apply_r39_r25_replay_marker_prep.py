from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy_runner.rs"
MARKER = "CAS-APPS-MCP-AUTH-R25-WIRE"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r39 r25 replay marker prep: already present")
    raise SystemExit(0)

# r38/r39 intentionally replace the proxy_runner prefix wholesale. They preserve the
# r25 MCP-auth behavior itself, but that replacement used to drop the r25 idempotency
# marker. A later revision-stamp replay then mistook the already-materialized wiring for
# an old tree and tried to replace the historical import anchor, producing:
#   proxy runner: imports: expected exactly one anchor, found 0
# Restore only the marker after proving the semantic wiring is already present.
required = (
    "build_router_with_relogin_and_mcp_auth",
    "ChatgptMcpRelayAuth",
    "active_chatgpt_mcp_relay_auth",
)
for token in required:
    if token not in body:
        raise SystemExit(
            f"r39 r25 replay marker prep: cannot restore marker; semantic token missing: {token}"
        )

anchor = "use codex_app_transfer_proxy::{\n"
if body.count(anchor) != 1:
    raise SystemExit(
        f"r39 r25 replay marker prep: expected one proxy import block, found {body.count(anchor)}"
    )
body = body.replace(
    anchor,
    "// CAS-APPS-MCP-AUTH-R25-WIRE: semantic wiring preserved by r38/r39 prefix replacement.\n"
    + anchor,
    1,
)
PATH.write_text(body, encoding="utf-8")

check = PATH.read_text(encoding="utf-8")
if MARKER not in check:
    raise SystemExit("r39 r25 replay marker prep: marker insertion failed")
print("r39 r25 replay marker prep: PASS")
