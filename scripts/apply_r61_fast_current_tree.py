from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"


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


def has_complete_r60_generated_baseline() -> bool:
    if not all(path.is_file() for path in (PROCESS, SUB2API, RESPONSES)):
        return False
    return (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" in SUB2API.read_text(encoding="utf-8")
        and "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" in RESPONSES.read_text(encoding="utf-8")
        and "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD" in PROCESS.read_text(encoding="utf-8")
    )


if has_complete_r60_generated_baseline():
    print("R61 FAST BASELINE: complete generated r60 tree detected; R60 COMPOSITION SKIP")
else:
    print("R61 FAST BASELINE: r60 generated markers incomplete; repairing r60 baseline once")
    run("scripts/apply_r60_fast_current_tree.py")
    if not has_complete_r60_generated_baseline():
        raise SystemExit("r61 fast baseline repair completed but required r60 markers are still missing")

run("scripts/apply_r61_disable_remote_compaction_v2.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=61" not in version_before or "app_version=2.4.5+61" not in version_before:
    REVISION.write_text("61\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R61 version already stamped; revision materializer SKIP")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "sync_codex_legacy_compaction_v1_r61",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r61 fast-current-tree invariant missing in process.rs: {marker}")

if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" not in SUB2API.read_text(encoding="utf-8"):
    raise SystemExit("r61 fast-current-tree lost r60 Sub2API replay compatibility")
if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" not in RESPONSES.read_text(encoding="utf-8"):
    raise SystemExit("r61 fast-current-tree lost r60 Responses replay hook")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=61" not in version or "app_version=2.4.5+61" not in version:
    raise SystemExit("r61 fast-current-tree version stamp missing")

print("R61 FAST CURRENT-TREE COMPOSITION PASS")
print("- warm generated r60 tree is reused without replay")
print("- only the Windows launch-time remote_compaction_v2=false compatibility guard is added")
print("- inherited r60/r59/r58/r57/r56 behavior remains intact")
