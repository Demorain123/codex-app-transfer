from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r60 fast-current-tree required component missing: {rel}")
    print(f"r60 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r59_generated_baseline() -> bool:
    paths = (SUB2API, RESPONSES, BACKEND, PROCESS, COMPACT, MCP_SERVERS, NO_MICRO, CARGO)
    if not all(path.is_file() for path in paths):
        return False
    sub2api = SUB2API.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")
    process = PROCESS.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    mcp = MCP_SERVERS.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    cargo = CARGO.read_text(encoding="utf-8")
    return (
        "CAS-SUB2API-GROK-COMPAT-HOOK" in RESPONSES.read_text(encoding="utf-8")
        and "apply_sub2api_grok_free_cache_compat" in sub2api
        and "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY" in backend
        and "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD" in process
        and "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK" in compact
        and "CAS-R55-DETACHED-MCP-HELPER" in mcp
        and "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION" in mcp
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and 'rusqlite = { version = "0.40", features = ["bundled"] }' in cargo
        and 'rusqlite = { version = "0.31", features = ["bundled"] }' not in cargo
    )


if has_complete_r59_generated_baseline():
    print("R60 FAST BASELINE: complete generated r59 tree detected; R59 COMPOSITION SKIP")
else:
    print("R60 FAST BASELINE: r59 generated markers incomplete; repairing r59 baseline once")
    run("scripts/apply_r59_fast_current_tree.py")
    if not has_complete_r59_generated_baseline():
        raise SystemExit("r60 fast baseline repair completed but required r59 markers are still missing")

run("scripts/apply_r60_sub2api_post_compaction_replay.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=60" not in version_before or "app_version=2.4.5+60" not in version_before:
    REVISION.write_text("60\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R60 version already stamped; revision materializer SKIP")

checks = {
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
        "apply_sub2api_post_compaction_replay_compat",
        "[sub2api-r60] action=post_compaction_replay_rewrite",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    ),
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r60 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=60" not in version or "app_version=2.4.5+60" not in version:
    raise SystemExit("r60 fast-current-tree version stamp missing")

print("R60 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r59 tree is reused without replay when warm")
print("- only Sub2API post-compaction Responses replay lowering is added")
print("- r59/r58/r57/r56 behavior remains otherwise unchanged")
