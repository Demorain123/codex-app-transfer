from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r42 required overlay/composer missing: {rel}")
    print(f"r42 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r42 inherited successful no-op: {rel}")


run("scripts/apply_r41_unified.py")
run("scripts/apply_r42_grok_tool_collision_guard.py")
REVISION.write_text("42\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/review_r42_grok_tool_collision_guard.py")

source = (ROOT / "crates/adapters/src/mapper/grok_build.rs").read_text(encoding="utf-8")
for marker in (
    "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD",
    "grok_effective_tool_name",
    "grok_tool_collision_r42_discovered_function_cannot_duplicate_native_web_search",
):
    if marker not in source:
        raise SystemExit(f"r42 materialization missing Grok collision marker: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=42" not in version or "app_version=2.4.5+42" not in version:
    raise SystemExit("r42 visible/package version stamp missing after composition")

print("r42 unified composition: COMPLETE (r41 preserved + final effective-name Grok tool collision guard)")
