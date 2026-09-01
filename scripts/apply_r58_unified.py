from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r58 required component missing: {rel}")
    print(f"r58 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r57_unified.py")
run("scripts/apply_r58_windows_chatgpt_lifecycle_guard.py")

REVISION.write_text("58\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "[compact-r56] action=sse_summary_fallback",
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
        "CloseMainWindow",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r58 generated-source invariant missing in {rel}: {marker}")

process = PROCESS.read_text(encoding="utf-8")
if "Name='Codex.exe' OR Name='codex.exe'" in process:
    raise SystemExit("r58 stale app-server-targeting Windows quit query remains")

cargo = CARGO.read_text(encoding="utf-8")
if 'rusqlite = { version = "0.40", features = ["bundled"] }' not in cargo:
    raise SystemExit("r58 inherited r57 rusqlite 0.40 dependency missing")
if 'rusqlite = { version = "0.31", features = ["bundled"] }' in cargo:
    raise SystemExit("r58 stale rusqlite 0.31 dependency remains")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=58" not in version or "app_version=2.4.5+58" not in version:
    raise SystemExit("r58 visible/package version stamp missing")

print("R58 UNIFIED COMPOSITION PASS")
print("- r56 compact SSE summary recovery remains intact")
print("- r57 external MCP source migration remains intact")
print("- Windows restart now owns the exact OpenAI.Codex package main executable, not the internal codex.exe app-server")
print("- current ChatGPT.exe and legacy Codex.exe package mains are supported without name-only consumer-app targeting")
print("- stale install-directory webfetch helper blocks restart until external MCP hosts reload detached configuration")
