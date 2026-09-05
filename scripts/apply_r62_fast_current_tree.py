from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r62 fast-current-tree required component missing: {rel}")
    print(f"r62 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r61_generated_baseline() -> bool:
    if not all(path.is_file() for path in (COMPACT, PROCESS, SUB2API, RESPONSES)):
        return False
    return (
        "CAS-R61-LEGACY-COMPACTION-V1" in PROCESS.read_text(encoding="utf-8")
        and "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" in SUB2API.read_text(encoding="utf-8")
        and "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" in RESPONSES.read_text(encoding="utf-8")
        and "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK" in COMPACT.read_text(encoding="utf-8")
        and "CAS-R51-COMPACT-HANDOFF-QUALITY" in COMPACT.read_text(encoding="utf-8")
    )


if has_complete_r61_generated_baseline():
    print("R62 FAST BASELINE: complete generated r61 tree detected; R61 COMPOSITION SKIP")
else:
    print("R62 FAST BASELINE: r61 generated markers incomplete; repairing r61 baseline once")
    run("scripts/apply_r61_fast_current_tree.py")
    if not has_complete_r61_generated_baseline():
        raise SystemExit("r62 fast baseline repair completed but required r61 markers are still missing")

run("scripts/apply_r62_compact_summary_repair.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=62" not in version_before or "app_version=2.4.5+62" not in version_before:
    REVISION.write_text("62\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R62 version already stamped; revision materializer SKIP")

compact = COMPACT.read_text(encoding="utf-8")
for marker in (
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR-RUNTIME",
    "[compact-r62] action=summary_self_repair_exhausted",
    "## Current State",
    "## Important Files / Tools / Evidence",
    "1500-5000",
    "minimum 600",
):
    if marker not in compact:
        raise SystemExit(f"r62 fast-current-tree invariant missing in compact.rs: {marker}")

process = PROCESS.read_text(encoding="utf-8")
if "CAS-R61-LEGACY-COMPACTION-V1" not in process:
    raise SystemExit("r62 fast-current-tree lost r61 legacy compaction selection")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=62" not in version or "app_version=2.4.5+62" not in version:
    raise SystemExit("r62 fast-current-tree version stamp missing")

print("R62 FAST CURRENT-TREE COMPOSITION PASS")
print("- warm generated r61 tree is reused without historical replay")
print("- only compact summary self-repair/quality diagnostics are added")
print("- inherited r61/r60/r59/r58/r56 model/session/launch behavior remains intact")
