from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def body(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r34 review missing file: {rel}")
    return path.read_text(encoding="utf-8")


telemetry = body("crates/proxy/src/telemetry.rs")
forward = body("crates/proxy/src/forward.rs")
health = body("src-tauri/src/admin/handlers/chain_health.rs")
page = body("frontend/src/pages/ProxyPage.vue")
api = body("frontend/src/api/chainHealth.ts")
version = body("SUB2API_GROK_COMPAT_VERSION.txt")

required = {
    "telemetry": [
        "RequestLifecycleSnapshot",
        "RequestLifecycleTracker",
        "max_size: 256",
        'terminal = Some("cancelled"',
    ],
    "forward": [
        "request_lifecycle_correlation_r34",
        "RequestLifecycleStreamR34",
        'mark_failed(lifecycle_id, "upstream_send")',
        "mark_first_event(this.id)",
        "mark_completed(this.id, this.status, this.bytes)",
    ],
    "health": [
        "observe_restart_delta_r34",
        "container.restart_delta > 0",
        "session_turn_stalled",
        "session_retry_recovered",
        "mcp_process_explosion",
        "windows_process_topology_r34",
        "guard_recent_failures_r34",
        "correlation=fingerprinted-no-prompt",
    ],
    "page": [
        "chainHealth.layer.session",
        "chainHealth.layer.mcp",
        "container.restartDelta",
    ],
    "api": ["session: ChainHealthLayer", "mcp: ChainHealthLayer", "restartDelta"],
    "version": ["compat_revision=34", "app_version=2.4.5+34"],
}
for name, markers in required.items():
    source = {
        "telemetry": telemetry,
        "forward": forward,
        "health": health,
        "page": page,
        "api": api,
        "version": version,
    }[name]
    for marker in markers:
        if marker not in source:
            raise SystemExit(f"r34 review missing {name} marker: {marker}")

# Regression lock: cumulative historical restart counts must not independently
# degrade a currently healthy container.
for forbidden in [
    "|| container.restart_count > 0",
    "Docker 容器栈正在启动或存在历史重启",
]:
    if forbidden in health:
        raise SystemExit(f"r34 restart false-positive regression: {forbidden}")

# Privacy boundary: lifecycle and MCP health must not ingest content or arbitrary
# process/container metadata. These exact high-risk access patterns are forbidden
# in the r34 files (comments intentionally avoid spelling them as code paths).
for forbidden in [
    "request_body: String",
    "response_body: String",
    "prompt: String",
    "tool_arguments",
    "Win32_Process.CommandLine",
    ".Config.Env",
    ".Mounts",
    "docker logs",
]:
    if forbidden in telemetry or forbidden in health:
        raise SystemExit(f"r34 privacy boundary violated: {forbidden}")

if "sub2api_retry_runtime_diag_header_fingerprint(headers, name)" not in forward:
    raise SystemExit("r34 correlation must use the existing non-reversible fingerprint helper")
if "Raw identity" not in forward or "Prompt/response bodies" not in telemetry:
    raise SystemExit("r34 privacy intent comments missing")
if "mcp_helper_candidate_r34(&row.name)" not in health:
    raise SystemExit("r34 MCP probe must stay scoped to Codex descendants and candidate names")

print("r34 runtime behavior health review: PASS")
