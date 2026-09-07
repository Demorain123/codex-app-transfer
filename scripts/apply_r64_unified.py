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
        raise SystemExit(f"r64 required component missing: {rel}")
    print(f"r64 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# r64 is intentionally narrow: retain the entire r63/r62/r61/r60 stack and
# only add a launch-time guard against the upstream experimental
# context_management stop-after-compaction regression.
run("scripts/apply_r63_unified.py")
run("scripts/apply_r64_post_compact_continuation_guard.py")

REVISION.write_text("64\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

forward = FORWARD.read_text(encoding="utf-8")
for marker in (
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
    "CAS-R63-AUTH-EPOCH-REQUEST-FENCE-HOOK",
    "CAS-R63-INVALID-ENCRYPTED-CONTENT-RECOVERY",
    "CAS-R63-COMPILE-HARDENING",
):
    if marker not in forward:
        raise SystemExit(f"r64 lost inherited r63/portable-replay invariant in forward.rs: {marker}")

if "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY" not in RECOVERY.read_text(encoding="utf-8"):
    raise SystemExit("r64 lost inherited r59 same-id interrupted-tail recovery")

compact = COMPACT.read_text(encoding="utf-8")
for marker in (
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
):
    if marker not in compact:
        raise SystemExit(f"r64 lost inherited compact invariant: {marker}")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "context_management = false # CAS-R64 managed continuation stability override",
    "[compact-r64] action=disable_context_management",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r64 generated process invariant missing: {marker}")

if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" not in SUB2API.read_text(encoding="utf-8"):
    raise SystemExit("r64 lost inherited r60 Sub2API replay compatibility")
if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" not in RESPONSES.read_text(encoding="utf-8"):
    raise SystemExit("r64 lost inherited r60 Responses replay hook")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=64" not in version or "app_version=2.4.5+64" not in version:
    raise SystemExit("r64 visible/package version stamp missing")

print("R64 UNIFIED COMPOSITION PASS")
print("- r63 auth-epoch/encrypted-history recovery remains unchanged")
print("- r62 compact summary self-repair remains unchanged")
print("- r61 legacy-V1 transport and r60 post-compact replay remain unchanged")
print("- experimental context_management is disabled before Windows Codex launch")
print("- no synthetic continuation request or automatic tool replay is introduced")
