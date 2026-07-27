from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r28 required composer/overlay missing: {rel}")
    print(f"r28 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# CAS-HYBRID-DIRECT-R28-COMPOSER
# Materialize the already-validated unified r27 stack first. r27 intentionally stamps
# itself as 27, so r28 restamps *after* it finishes rather than fighting the parent
# composer or duplicating the r24/r25/r26/r27 sequence here.
run("scripts/apply_r27_unified.py")

REVISION.write_text("28\n", encoding="utf-8")
print("r28 revision selected: 28")

# Re-run the common revision/identity stage against revision=28. The r24/r25 parts of
# this script are semantically idempotent and are also our materialization gates; r26/r27
# remain present from the parent composer. This fixes the historical 'r27 commit but r25
# artifact' class of version drift when packaging.
run("scripts/apply_sub2api_grok_compat_revision.py")

# Install the new gateway-only boundary last. Scoped preflights resolve known upstream
# layout variants (production defaults vs test fixtures, zh/en dictionary tails) without
# weakening fail-closed checks in the main overlay.
run("scripts/apply_hybrid_direct_r28_preflight.py")
run("scripts/apply_hybrid_direct_r28_i18n_preflight.py")
run("scripts/apply_hybrid_direct_r28.py")

# Backend API guard layer: even an old UI/deep link/manual API request must not be able
# to replay Transfer snapshots or residual-repair a CC Switch-owned Grok route once
# Hybrid Direct is active.
run("scripts/apply_hybrid_direct_r28_manual_guard.py")
run("scripts/review_hybrid_direct_r28.py")
run("scripts/review_hybrid_direct_r28_manual_guard.py")

required = {
    "src-tauri/src/admin/services/desktop/hybrid_direct.rs": "CAS-HYBRID-DIRECT-R28",
    "src-tauri/src/admin/handlers/proxy.rs": "CAS-HYBRID-DIRECT-R28-PROVIDER-REFRESH",
    "src-tauri/src/admin/services/desktop/snapshot.rs": "CAS-HYBRID-DIRECT-R28-GATEWAY-SYNC",
    "src-tauri/src/admin/handlers/desktop.rs": "CAS-HYBRID-DIRECT-R28-MANUAL-RESTORE-GUARD",
    "frontend/src/pages/SettingsPage.vue": "settings.hybridDirect",
    "SUB2API_GROK_COMPAT_VERSION.txt": "compat_revision=28",
}
for rel, marker in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"r28 final composition gate failed: {rel} missing {marker}")

print("r28 Hybrid Direct unified composition: COMPLETE")
