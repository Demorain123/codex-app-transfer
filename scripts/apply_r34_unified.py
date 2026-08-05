from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r34 required overlay/composer missing: {rel}")
    print(f"r34 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r34 inherited successful no-op: {rel}")


# Preserve the complete validated r33 stack first.
run("scripts/apply_r33_unified.py")
run("scripts/review_r33_chain_health.py")

REVISION.write_text("34\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
# Normalize the r34 source overlay itself before executing it. This prep is
# idempotent and removes a layout-sensitive container insertion anchor.
run("scripts/apply_r34_restart_delta_overlay_prep.py")
run("scripts/apply_r34_runtime_behavior_health.py")
run("scripts/review_r34_runtime_behavior_health.py")

required = {
    "crates/proxy/src/telemetry.rs": [
        "CAS-R34-RUNTIME-BEHAVIOR-HEALTH",
        "RequestLifecycleTracker",
        "mark_first_event",
    ],
    "crates/proxy/src/forward.rs": [
        "CAS-R34-RUNTIME-BEHAVIOR-HEALTH",
        "RequestLifecycleStreamR34",
        "request_lifecycle_correlation_r34",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R34-RUNTIME-BEHAVIOR-HEALTH",
        "session_layer()",
        "mcp_layer()",
        "restart_delta",
        "session_retry_recovered",
        "mcp_process_explosion",
    ],
    "frontend/src/api/chainHealth.ts": [
        "CAS-R34-RUNTIME-BEHAVIOR-HEALTH",
        "session: ChainHealthLayer",
        "mcp: ChainHealthLayer",
        "restartDelta",
    ],
    "frontend/src/pages/ProxyPage.vue": [
        "CAS-R34-RUNTIME-BEHAVIOR-HEALTH",
        "chainHealth.layer.session",
        "chainHealth.layer.mcp",
        "container.restartDelta",
    ],
    "frontend/src/i18n/zh.ts": ["CAS-R34-RUNTIME-BEHAVIOR-HEALTH", "MCP 健康"],
    "frontend/src/i18n/en.ts": ["CAS-R34-RUNTIME-BEHAVIOR-HEALTH", "MCP Health"],
}
for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r34 materialization missing file: {rel}")
    body = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r34 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=34" not in version or "app_version=2.4.5+34" not in version:
    raise SystemExit("r34 visible/package version stamp missing after composition")

print("r34 unified composition: COMPLETE (r33 preserved + runtime behavior health)")
