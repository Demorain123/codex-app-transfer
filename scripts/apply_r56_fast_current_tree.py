from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r56 fast-current-tree required component missing: {rel}")
    print(f"r56 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r55_generated_baseline() -> bool:
    if not all(path.is_file() for path in (FORWARD, COMPACT, MCP_SERVERS, NO_MICRO)):
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    mcp = MCP_SERVERS.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R51-COMPACTION-ROLE-TRUTH" in forward
        and "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY" in compact
        and "CAS-R55-DETACHED-MCP-HELPER" in mcp
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
    )


if has_complete_r55_generated_baseline():
    print("R56 FAST BASELINE: complete generated r55 tree detected; R55 COMPOSITION SKIP")
else:
    print("R56 FAST BASELINE: r55 generated markers incomplete; repairing r55 baseline once")
    run("scripts/apply_r55_fast_current_tree.py")
    if not has_complete_r55_generated_baseline():
        raise SystemExit("r56 fast baseline repair completed but required r55 markers are still missing")

run("scripts/apply_r56_compact_sse_summary_fallback.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=56" not in version_before or "app_version=2.4.5+56" not in version_before:
    REVISION.write_text("56\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R56 version already stamped; revision materializer SKIP")

checks = {
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "[compact-r56] action=sse_summary_fallback",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r56 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=56" not in version or "app_version=2.4.5+56" not in version:
    raise SystemExit("r56 fast-current-tree version stamp missing")

print("R56 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r55 tree is reused without replay when warm")
print("- only compact Responses SSE summary recovery is added in r56")
print("- detached MCP helper, session identity, model routing, and r49 TEMP remain unchanged")
