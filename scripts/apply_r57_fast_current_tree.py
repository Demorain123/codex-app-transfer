from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r57 fast-current-tree required component missing: {rel}")
    print(f"r57 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r56_generated_baseline() -> bool:
    if not all(path.is_file() for path in (COMPACT, MCP_SERVERS, CARGO, NO_MICRO)):
        return False
    compact = COMPACT.read_text(encoding="utf-8")
    mcp = MCP_SERVERS.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK" in compact
        and "CAS-R55-DETACHED-MCP-HELPER" in mcp
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
    )


if has_complete_r56_generated_baseline():
    print("R57 FAST BASELINE: complete generated r56 tree detected; R56 COMPOSITION SKIP")
else:
    print("R57 FAST BASELINE: r56 generated markers incomplete; repairing r56 baseline once")
    run("scripts/apply_r56_fast_current_tree.py")
    if not has_complete_r56_generated_baseline():
        raise SystemExit("r57 fast baseline repair completed but required r56 markers are still missing")

run("scripts/apply_r57_external_mcp_source_migration.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=57" not in version_before or "app_version=2.4.5+57" not in version_before:
    REVISION.write_text("57\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R57 version already stamped; revision materializer SKIP")

checks = {
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
        "migrate_cc_switch_webfetch_r57",
        "migrate_omp_native_webfetch_r57",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r57 fast-current-tree invariant missing in {rel}: {marker}")

if 'rusqlite = { version = "0.31", features = ["bundled"] }' not in CARGO.read_text(encoding="utf-8"):
    raise SystemExit("r57 fast-current-tree rusqlite dependency missing")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=57" not in version or "app_version=2.4.5+57" not in version:
    raise SystemExit("r57 fast-current-tree version stamp missing")

print("R57 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r56 tree is reused without replay when warm")
print("- only external MCP source migration + narrow SQLite dependency are added in r57")
print("- r56 compact parser, r55 detached helper, model/session behavior and r49 TEMP remain unchanged")
