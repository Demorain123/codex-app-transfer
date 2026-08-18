from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r39 composer missing: {rel}")
    print(f"r39 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# r39 remains a thin outer-shell overlay: preserve all reviewed r38 behavior,
# then replace only proxy lifecycle/recovery semantics and related diagnostics.
run("scripts/apply_r38_unified.py")
run("scripts/review_r38_model_route_observability.py")

REVISION.write_text("39\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r39_proxy_lifecycle_reliability.py")
run("scripts/apply_r39_lifecycle_singleflight_followup.py")
run("scripts/review_r39_proxy_lifecycle_reliability.py")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=39" not in version or "app_version=2.4.5+39" not in version:
    raise SystemExit("r39 composer: version stamp mismatch")
print("r39 unified composition: COMPLETE")
