from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r33 required overlay/composer missing: {rel}")
    print(f"r33 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        # Some inherited idempotent overlays use SystemExit(0) to mean
        # "already materialized". That is a successful no-op, not a reason to
        # abort the outer r33 composition. Non-zero exits remain fatal.
        if exc.code not in (None, 0):
            raise
        print(f"r33 inherited successful no-op: {rel}")


# Preserve the validated r32 stack. r33 adds a privacy-bounded, non-destructive
# chain health center to the existing Route page.
run("scripts/apply_r32_unified.py")
# The current r32 composer may return early after its already-applied Usage sort
# overlay. Explicitly rerun both inherited semantic reviews before adding r33.
run("scripts/review_no_lagging_r32.py")
run("scripts/review_r32_usage_sort.py")

REVISION.write_text("33\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r33_chain_health.py")
run("scripts/apply_r33_chain_health_hardening.py")
run("scripts/apply_r33_chain_health_inspect_privacy.py")
run("scripts/apply_r33_chain_health_state_privacy.py")
run("scripts/apply_r33_chain_health_label_privacy.py")
run("scripts/review_r33_chain_health.py")

required = {
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R33-CHAIN-HEALTH",
        "CAS-R33-CHAIN-HEALTH-PRIVACY",
        "CAS-R33-CHAIN-HEALTH-INSPECT-PRIVACY",
        "CAS-R33-CHAIN-HEALTH-STATE-PROJECTION",
        "CAS-R33-CHAIN-HEALTH-LABEL-PROJECTION",
        "docker_daemon_timeout",
        "gateway_tcp_timeout",
        "upstream_headers_stalled",
        "kill_on_drop(true)",
    ],
    "src-tauri/src/admin/handlers/mod.rs": ["CAS-R33-CHAIN-HEALTH"],
    "src-tauri/src/admin/mod.rs": ["/api/chain-health", "CAS-R33-CHAIN-HEALTH"],
    "frontend/src/api/chainHealth.ts": ["CAS-R33-CHAIN-HEALTH", "getChainHealth"],
    "frontend/src/pages/ProxyPage.vue": [
        "CAS-R33-CHAIN-HEALTH",
        "chain-health__grid",
        "loadChainHealth",
    ],
    "frontend/src/i18n/zh.ts": ["chainHealth.title"],
    "frontend/src/i18n/en.ts": ["chainHealth.title"],
    "src-tauri/src/admin/services/desktop/no_micro.rs": ["CAS-NO-LAGGING-R32-MCP-EXIT-GUARD"],
    "frontend/src/pages/UsagePage.vue": ["CAS-R32-USAGE-CLICK-SORT"],
}
for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r33 materialization missing file: {rel}")
    body = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r33 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=33" not in version or "app_version=2.4.5+33" not in version:
    raise SystemExit("r33 visible/package version stamp missing after composition")

print("r33 unified composition: COMPLETE (r32 preserved + privacy-bounded chain health center)")
