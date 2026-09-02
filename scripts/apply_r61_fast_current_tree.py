from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r61 fast-current-tree required component missing: {rel}")
    print(f"r61 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Reuse r60's warm-tree repair/composition logic, then add only the r61 proxy handoff.
run("scripts/apply_r60_fast_current_tree.py")
run("scripts/apply_r61_model_switch_compact_resume_once.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=61" not in version_before or "app_version=2.4.5+61" not in version_before:
    REVISION.write_text("61\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R61 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R61-MODEL-SWITCH-COMPACT-RESUME-ONCE",
        "arm_current_model_fallback",
        "allow_current_model_compaction",
        "resume_main_turn",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r61 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=61" not in version or "app_version=2.4.5+61" not in version:
    raise SystemExit("r61 fast-current-tree version stamp missing")

print("R61 FAST CURRENT-TREE COMPOSITION PASS")
print("- r60 generated tree/cache is reused")
print("- only the r61 CompHashChanged current-model handoff is added")
print("- r60/r59/r58/r57/r56 behavior remains otherwise unchanged")
