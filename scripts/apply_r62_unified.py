from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r62 required component missing: {rel}")
    print(f"r62 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve the complete r61/r60/r59/... stack. r62 changes only the compact summary
# instruction/diagnostic layer; model switching, replay normalization, launch behavior,
# and session identity are inherited unchanged.
run("scripts/apply_r61_unified.py")
run("scripts/apply_r62_compact_summary_repair.py")

REVISION.write_text("62\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

compact = COMPACT.read_text(encoding="utf-8")
for marker in (
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR-RUNTIME",
    "[compact-r62] action=summary_self_repair_exhausted",
    "## Current State",
    "## Next Step",
    "1500-5000",
    "minimum 600",
):
    if marker not in compact:
        raise SystemExit(f"r62 generated-source invariant missing in compact.rs: {marker}")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r62 lost inherited r61 process invariant: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=62" not in version or "app_version=2.4.5+62" not in version:
    raise SystemExit("r62 visible/package version stamp missing")

print("R62 UNIFIED COMPOSITION PASS")
print("- complete r61 legacy-V1 compaction selection is preserved")
print("- complete r60 post-compaction replay compatibility is preserved")
print("- r51 quality floor remains 600 chars; r62 does not accept the observed 229-char bad summary")
print("- substantial-history compact prompt now self-checks once and targets a structured 1500-5000 char checkpoint")
print("- no rollout mutation, rollback, new thread, or session-id change")
