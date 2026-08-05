from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/chainHealth.ts"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"

for path in [HANDLER, PAGE, API, ADMIN, CARGO]:
    if not path.is_file():
        raise SystemExit(f"r33 review missing file: {path.relative_to(ROOT)}")

handler = HANDLER.read_text(encoding="utf-8")
page = PAGE.read_text(encoding="utf-8")
api = API.read_text(encoding="utf-8")
admin = ADMIN.read_text(encoding="utf-8")
cargo = CARGO.read_text(encoding="utf-8")

required_handler = [
    "CAS-R33-CHAIN-HEALTH",
    "CAS-R33-CHAIN-HEALTH-PRIVACY",
    "CACHE_TTL",
    "DNS_TIMEOUT",
    "TCP_TIMEOUT",
    "HTTP_TIMEOUT",
    "COMMAND_TIMEOUT",
    "kill_on_drop(true)",
    "docker_daemon_timeout",
    "docker_stack_failed",
    "native_runtime_reachable",
    "gateway_http_timeout",
    "upstream_headers_stalled",
    "mode=passive-no-inference",
    "set_username(\"\")",
    "set_password(None)",
    "set_query(None)",
    "set_fragment(None)",
]
for marker in required_handler:
    if marker not in handler:
        raise SystemExit(f"r33 handler missing safety/behavior marker: {marker}")

for forbidden in [
    "/var/run/docker.sock",
    "//./pipe/docker_engine",
    "docker restart",
    "docker stop",
    "docker kill",
    "docker rm",
    "Config/Env",
    "Authorization",
    "/v1/responses",
    "/chat/completions",
]:
    if forbidden in handler:
        raise SystemExit(f"r33 automatic health handler contains forbidden behavior: {forbidden}")

if 'features = ["sync", "net", "process", "rt-multi-thread", "time"]' not in cargo:
    raise SystemExit("r33 tokio process feature missing")

for marker in [
    "CAS-R33-CHAIN-HEALTH",
    "chain-health__grid",
    "chainHealth.runtime.containers",
    "loadChainHealth(true)",
    "window.setInterval(() => loadChainHealth(), 10000)",
]:
    if marker not in page:
        raise SystemExit(f"r33 Route page missing marker: {marker}")

if "getChainHealth" not in api or "/api/chain-health" not in api:
    raise SystemExit("r33 frontend chain-health API missing")
if '.route("/api/chain-health"' not in admin:
    raise SystemExit("r33 backend chain-health route missing")

# No automatic recovery buttons in r33: health diagnosis must stay read-only.
for forbidden in ["restartDocker", "restartContainer", "killContainer", "autoRecover"]:
    if forbidden in page or forbidden in api:
        raise SystemExit(f"r33 UI unexpectedly exposes destructive recovery: {forbidden}")

print("r33 chain health semantic review: PASS")
