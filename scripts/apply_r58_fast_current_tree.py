from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r58 fast-current-tree required component missing: {rel}")
    print(f"r58 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r57_generated_baseline() -> bool:
    if not all(path.is_file() for path in (COMPACT, MCP_SERVERS, PROCESS, CARGO, NO_MICRO)):
        return False
    compact = COMPACT.read_text(encoding="utf-8")
    mcp = MCP_SERVERS.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    cargo = CARGO.read_text(encoding="utf-8")
    return (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK" in compact
        and "CAS-R55-DETACHED-MCP-HELPER" in mcp
        and "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION" in mcp
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and 'rusqlite = { version = "0.40", features = ["bundled"] }' in cargo
        and 'rusqlite = { version = "0.31", features = ["bundled"] }' not in cargo
    )


if has_complete_r57_generated_baseline():
    print("R58 FAST BASELINE: complete generated r57 tree detected; R57 COMPOSITION SKIP")
else:
    print("R58 FAST BASELINE: r57 generated markers incomplete; repairing r57 baseline once")
    run("scripts/apply_r57_fast_current_tree.py")
    if not has_complete_r57_generated_baseline():
        raise SystemExit("r58 fast baseline repair completed but required r57 markers are still missing")

run("scripts/apply_r58_windows_chatgpt_lifecycle_guard.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=58" not in version_before or "app_version=2.4.5+58" not in version_before:
    REVISION.write_text("58\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R58 version already stamped; revision materializer SKIP")

checks = {
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    ),
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
        "ensure_no_install_dir_webfetch_helper_r58",
        "OpenAI.Codex",
        "ChatGPT.exe",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r58 fast-current-tree invariant missing in {rel}: {marker}")

process = PROCESS.read_text(encoding="utf-8")
if "Name='Codex.exe' OR Name='codex.exe'" in process:
    raise SystemExit("r58 fast-current-tree stale app-server-targeting Windows quit query remains")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=58" not in version or "app_version=2.4.5+58" not in version:
    raise SystemExit("r58 fast-current-tree version stamp missing")

print("R58 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r57 tree is reused without replay when warm")
print("- only Windows ChatGPT lifecycle ownership + stale MCP host restart gate are added in r58")
print("- r56 compact parser, r57 external migration, r55 detached helper and r49 TEMP remain unchanged")
