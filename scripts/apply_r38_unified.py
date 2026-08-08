from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 composer missing: {rel}")
    print(f"r38 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# r38 remains a thin outer-shell overlay on the fully-reviewed r37 stack.
run("scripts/apply_r37_unified.py")
run("scripts/review_r37_fault_attribution_quota_guard.py")

REVISION.write_text("38\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r38_proxy_observability.py")
run("scripts/apply_r38_health_model_routes.py")
run("scripts/apply_r38_frontend_model_routes.py")
run("scripts/review_r38_model_route_observability.py")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=38" not in version or "app_version=2.4.5+38" not in version:
    raise SystemExit("r38 composer: version stamp mismatch")
print("r38 unified composition: COMPLETE")
