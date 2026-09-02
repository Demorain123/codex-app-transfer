from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r61 required component missing: {rel}")
    print(f"r61 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve the complete r60 stack, then change only Codex's launch-time compaction
# feature selection. The HTTP/SSE compaction and post-compaction replay paths stay r60.
run("scripts/apply_r60_unified.py")
run("scripts/apply_r61_disable_remote_compaction_v2.py")

REVISION.write_text("61\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

process = PROCESS.read_text(encoding="utf-8")
for marker in (
    "CAS-R61-LEGACY-COMPACTION-V1",
    "sync_codex_legacy_compaction_v1_r61",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "[model-switch-r61] action=disable_remote_compaction_v2",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
):
    if marker not in process:
        raise SystemExit(f"r61 generated-source invariant missing in process.rs: {marker}")

# r60 behavior must remain composed beneath r61.
checks = {
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
        "apply_sub2api_post_compaction_replay_compat",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r61 inherited invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=61" not in version or "app_version=2.4.5+61" not in version:
    raise SystemExit("r61 visible/package version stamp missing")

print("R61 UNIFIED COMPOSITION PASS")
print("- complete r60 Sub2API compact transport and replay stack is preserved")
print("- Windows Transfer launch disables remote_compaction_v2 so Codex selects legacy V1")
print("- V1 /responses/compact remains locally implemented by the inherited r52 compatibility path")
print("- normal and No-Micro launch pipelines both receive the same feature override")
