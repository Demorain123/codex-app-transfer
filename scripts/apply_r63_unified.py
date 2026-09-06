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
        raise SystemExit(f"r63 required component missing: {rel}")
    print(f"r63 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve the complete r62/r61/r60/... stack. r63 changes only the authentication
# generation + encrypted-history compatibility boundary and explicit 400 recovery.
run("scripts/apply_r62_unified.py")
run("scripts/apply_r63_auth_epoch_encrypted_history_fence.py")
run("scripts/apply_r63_compile_hardening.py")

REVISION.write_text("63\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

forward = FORWARD.read_text(encoding="utf-8")
for marker in (
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
    "CAS-R63-AUTH-EPOCH-REQUEST-FENCE-HOOK",
    "CAS-R63-INVALID-ENCRYPTED-CONTENT-RECOVERY",
    "CAS-R63-COMPILE-HARDENING",
    "fn portableize_input_item_r63(",
    "auth-epoch-r63.json",
    "invalid_encrypted_content_recovery_retry_1",
):
    if marker not in forward:
        raise SystemExit(f"r63 generated-source invariant missing in forward.rs: {marker}")
if "let mut lower = |item:" in forward:
    raise SystemExit("r63 unified composition still contains the borrow-unsafe item-lowering closure")

if "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY" not in RECOVERY.read_text(encoding="utf-8"):
    raise SystemExit("r63 lost inherited r59 same-id interrupted-tail recovery")

compact = COMPACT.read_text(encoding="utf-8")
for marker in (
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
):
    if marker not in compact:
        raise SystemExit(f"r63 lost inherited compact invariant: {marker}")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r63 lost inherited process invariant: {marker}")

if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY" not in SUB2API.read_text(encoding="utf-8"):
    raise SystemExit("r63 lost inherited r60 Sub2API replay compatibility")
if "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK" not in RESPONSES.read_text(encoding="utf-8"):
    raise SystemExit("r63 lost inherited r60 Responses replay hook")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=63" not in version or "app_version=2.4.5+63" not in version:
    raise SystemExit("r63 visible/package version stamp missing")

print("R63 UNIFIED COMPOSITION PASS")
print("- r62 compact summary self-repair remains unchanged")
print("- r60 Sub2API private-compaction lowering remains unchanged")
print("- r50 cross-model portable replay remains unchanged")
print("- auth changes are tracked as privacy-safe persistent epochs per session fingerprint")
print("- an auth-boundary session gets a sticky portable encrypted-history fence")
print("- backend-confirmed invalid_encrypted_content is rebuilt and retried at most once")
print("- generated Rust item lowering is borrow-safe before build/test")
print("- no rollout mutation, rollback, fork, new thread, or raw account/session/token persistence")
