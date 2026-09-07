from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
RECOVERY = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r64 fast-current-tree required component missing: {rel}")
    print(f"r64 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r63_generated_baseline() -> bool:
    if not all(path.is_file() for path in (FORWARD, COMPACT, PROCESS, RECOVERY, SUB2API, RESPONSES)):
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    process = PROCESS.read_text(encoding="utf-8")
    recovery = RECOVERY.read_text(encoding="utf-8")
    sub2api = SUB2API.read_text(encoding="utf-8")
    responses = RESPONSES.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE" in forward
        and "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY" in recovery
        and "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR" in compact
        and "CAS-R61-LEGACY-COMPACTION-V1" in process
        and "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" in sub2api
        and "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" in responses
    )


if has_complete_r63_generated_baseline():
    print("R64 FAST BASELINE: complete generated r63 tree detected; R63 COMPOSITION SKIP")
else:
    print("R64 FAST BASELINE: r63 generated markers incomplete; repairing r63 baseline once")
    run("scripts/apply_r63_fast_current_tree.py")
    if not has_complete_r63_generated_baseline():
        raise SystemExit("r64 fast baseline repair completed but required r63 markers are still missing")

run("scripts/apply_r64_post_compact_continuation_guard.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=64" not in version_before or "app_version=2.4.5+64" not in version_before:
    REVISION.write_text("64\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R64 version already stamped; revision materializer SKIP")

forward = FORWARD.read_text(encoding="utf-8")
for marker in (
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
    "CAS-R63-INVALID-ENCRYPTED-CONTENT-RECOVERY",
):
    if marker not in forward:
        raise SystemExit(f"r64 fast-current-tree lost inherited forward invariant: {marker}")

if "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY" not in RECOVERY.read_text(encoding="utf-8"):
    raise SystemExit("r64 fast-current-tree lost inherited r59 same-id interrupted-tail recovery")

compact = COMPACT.read_text(encoding="utf-8")
for marker in (
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
):
    if marker not in compact:
        raise SystemExit(f"r64 fast-current-tree lost compact invariant: {marker}")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "context_management = false # CAS-R64 managed continuation stability override",
    "[compact-r64] action=disable_context_management",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r64 fast-current-tree process invariant missing: {marker}")

if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" not in SUB2API.read_text(encoding="utf-8"):
    raise SystemExit("r64 fast-current-tree lost r60 Sub2API compaction replay")
if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" not in RESPONSES.read_text(encoding="utf-8"):
    raise SystemExit("r64 fast-current-tree lost r60 Responses compaction hook")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=64" not in version or "app_version=2.4.5+64" not in version:
    raise SystemExit("r64 fast-current-tree version stamp missing")

print("R64 FAST CURRENT-TREE COMPOSITION PASS")
print("- warm generated r63 tree is reused without historical replay")
print("- only the context_management continuation-stability launch guard is added")
print("- r63/r62/r61/r60/r59/r58/r50 behavior remains inherited")
print("- no synthetic continuation request or automatic tool replay is added")
