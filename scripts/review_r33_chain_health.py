from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
HANDLERS_MOD = ROOT / "src-tauri/src/admin/handlers/mod.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/chainHealth.ts"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"

for path in [HANDLER, HANDLERS_MOD, PAGE, API, ADMIN, CARGO]:
    if not path.is_file():
        raise SystemExit(f"r33 review missing file: {path.relative_to(ROOT)}")

handler = HANDLER.read_text(encoding="utf-8")
handlers_mod = HANDLERS_MOD.read_text(encoding="utf-8")
page = PAGE.read_text(encoding="utf-8")
api = API.read_text(encoding="utf-8")
admin = ADMIN.read_text(encoding="utf-8")
cargo = CARGO.read_text(encoding="utf-8")

required_handler = [
    "CAS-R33-CHAIN-HEALTH",
    "CAS-R33-CHAIN-HEALTH-PRIVACY",
    "CAS-R33-CHAIN-HEALTH-INSPECT-PRIVACY",
    "CAS-R33-CHAIN-HEALTH-STATE-PROJECTION",
    "CAS-R33-CHAIN-HEALTH-LABEL-PROJECTION",
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
    '"--format".to_owned()',
    '"HealthStatus":{{if .State.Health}}',
    'index .Config.Labels "com.docker.compose.project"',
    'index .Config.Labels "com.docker.compose.service"',
    'index .Config.Labels "com.docker.compose.oneoff"',
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
    '"State":{{json .State}}',
    "Health.Log",
    '"Labels":{{json .Config.Labels}}',
    '\\"com.docker.compose.project\\"',
]:
    if forbidden in handler:
        raise SystemExit(f"r33 automatic health handler contains forbidden behavior: {forbidden}")

# The only inspect call must include the safe scalar projection before container IDs.
inspect_function = handler.split("async fn inspect_containers", 1)[1].split("async fn container_stats", 1)[0]
if '"inspect".to_owned(),\n        "--format".to_owned()' not in inspect_function:
    raise SystemExit("r33 Docker inspect is not field-projected")
if "serde_json::from_str::<Vec<Value>>" in inspect_function:
    raise SystemExit("r33 Docker inspect still expects an unprojected full array")
if '"State":{{json .State}}' in inspect_function or "Health.Log" in inspect_function:
    raise SystemExit("r33 Docker inspect still ingests full state or healthcheck output")
if '"Labels":{{json .Config.Labels}}' in inspect_function:
    raise SystemExit("r33 Docker inspect still ingests the full custom label map")
for scalar in [
    ".State.Running",
    ".State.Status",
    ".State.Health.Status",
    ".State.Restarting",
    ".State.OOMKilled",
    ".State.ExitCode",
]:
    if scalar not in inspect_function:
        raise SystemExit(f"r33 Docker inspect scalar state projection missing: {scalar}")
for compose_key in [
    "com.docker.compose.project",
    "com.docker.compose.service",
    "com.docker.compose.oneoff",
]:
    if compose_key not in inspect_function:
        raise SystemExit(f"r33 Docker inspect Compose identity key missing: {compose_key}")

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

route_marker = '.route("/api/chain-health", get(handlers::chain_health::chain_health))'
module_marker = "pub mod chain_health;"
if admin.count(route_marker) != 1:
    raise SystemExit(
        f"r33 backend chain-health route count must be 1, got {admin.count(route_marker)}"
    )
if handlers_mod.count(module_marker) != 1:
    raise SystemExit(
        f"r33 chain-health handler module count must be 1, got {handlers_mod.count(module_marker)}"
    )

# No automatic recovery buttons in r33: health diagnosis must stay read-only.
for forbidden in ["restartDocker", "restartContainer", "killContainer", "autoRecover"]:
    if forbidden in page or forbidden in api:
        raise SystemExit(f"r33 UI unexpectedly exposes destructive recovery: {forbidden}")

print("r33 chain health semantic review: PASS")
