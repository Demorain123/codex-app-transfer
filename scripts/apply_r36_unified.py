from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r36 required overlay/composer missing: {rel}")
    print(f"r36 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r36 inherited successful no-op: {rel}")


run("scripts/apply_r35_unified.py")
run("scripts/review_r35_real_upstream_health.py")

REVISION.write_text("36\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r36_safe_recovery.py")
run("scripts/review_r36_safe_recovery.py")

required = {
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R36-SAFE-RECOVERY",
        "chain_health_recover",
        "RECOVERY_COOLDOWN",
        "restart_healthy_sub2api",
    ],
    "src-tauri/src/admin/mod.rs": ["/api/chain-health/recover"],
    "frontend/src/api/chainHealth.ts": ["recoverChainHealth"],
    "frontend/src/pages/ProxyPage.vue": ["onRecoverChain", "chainHealth.recover"],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r36 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=36" not in version or "app_version=2.4.5+36" not in version:
    raise SystemExit("r36 visible/package version stamp missing after composition")

print("r36 unified composition: COMPLETE (r35 preserved + safe recovery)")
