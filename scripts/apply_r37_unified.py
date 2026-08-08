from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r37 required overlay/composer missing: {rel}")
    print(f"r37 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r37 inherited successful no-op: {rel}")


run("scripts/apply_r36_unified.py")
run("scripts/review_r36_safe_recovery.py")

REVISION.write_text("37\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r37_snapshot_prep.py")
run("scripts/apply_r37_i18n_prep.py")
run("scripts/apply_r37_fault_attribution_quota_guard.py")
run("scripts/review_r37_fault_attribution_quota_guard.py")

required = {
    "crates/proxy/src/telemetry.rs": [
        "CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD",
        "quota_primary_used_percent",
        "mark_quota",
    ],
    "crates/proxy/src/forward.rs": [
        "CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD",
        "x-codex-primary-used-percent",
        "x-codex-secondary-used-percent",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "account_pool_layer_r37",
        "fault_attribution_layer_r37",
        "fault_session_scoped",
        "fault_compaction_context",
        "account_pool_exhausted",
    ],
    "frontend/src/api/chainHealth.ts": ["account: ChainHealthLayer", "diagnosis: ChainHealthLayer"],
    "frontend/src/pages/ProxyPage.vue": ["chainHealth.layer.account", "chainHealth.diagnosis.summary"],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r37 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=37" not in version or "app_version=2.4.5+37" not in version:
    raise SystemExit("r37 visible/package version stamp missing after composition")

print("r37 unified composition: COMPLETE (r36 recovery preserved + lightweight attribution/quota guard)")
