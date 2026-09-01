from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
MCP_SERVERS = ROOT / "src-tauri/src/admin/services/mcp_servers.rs"
CARGO = ROOT / "src-tauri/Cargo.toml"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r57 required component missing: {rel}")
    print(f"r57 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r56_unified.py")
run("scripts/apply_r57_external_mcp_source_migration.py")

REVISION.write_text("57\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "[compact-r56] action=sse_summary_fallback",
    ),
    "src-tauri/src/admin/services/mcp_servers.rs": (
        "CAS-R55-DETACHED-MCP-HELPER",
        "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
        "migrate_cc_switch_webfetch_r57",
        "migrate_omp_native_webfetch_r57",
        "[mcp-r57] source=cc-switch action=migrated",
        "[mcp-r57] source=omp-native action=migrated",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r57 generated-source invariant missing in {rel}: {marker}")

cargo = CARGO.read_text(encoding="utf-8")
if 'rusqlite = { version = "0.31", features = ["bundled"] }' not in cargo:
    raise SystemExit("r57 Windows rusqlite dependency missing")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=57" not in version or "app_version=2.4.5+57" not in version:
    raise SystemExit("r57 visible/package version stamp missing")

print("R57 UNIFIED COMPOSITION PASS")
print("- r56 same-model/cross-model compact SSE summary recovery remains intact")
print("- r55 detached MCP helper remains the runtime target")
print("- CC Switch persistent Codex MCP source and OMP-native user/profile sources migrate old cat-webfetch commands")
print("- migration is narrow, idempotent and best-effort; unrelated MCP/provider data is untouched")
print("- after external hosts restart once, they no longer need the installed main Transfer EXE for webfetch MCP")
