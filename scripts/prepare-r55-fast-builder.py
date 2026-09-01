from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r54-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r55-fast-real-use.ps1"

if not SOURCE.is_file():
    prep54 = ROOT / "scripts/prepare-r54-fast-builder.py"
    if not prep54.is_file():
        raise SystemExit("r55 fast builder: r54 builder and preparation script are both missing")
    print("r55 fast builder: generating reusable r54 builder once")
    runpy.run_path(str(prep54), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r55 fast builder: generated r54 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r54 - FAST REAL-USE BUILD", "Codex App Transfer r55 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r54", "[1/9] Materialize r55"),
    ("Warm r54 materialization detected; SKIP.", "Warm r55 materialization detected; SKIP."),
    (".\\scripts\\apply_r54_unified.py", ".\\scripts\\apply_r55_unified.py"),
    ("compat_revision=54", "compat_revision=55"),
    ("app_version=2\\.4\\.5\\+54", "app_version=2\\.4\\.5\\+55"),
    ("app_version=2.4.5+54", "app_version=2.4.5+55"),
    ("2.4.5+54", "2.4.5+55"),
    ("2.4.5-r54", "2.4.5-r55"),
    ("r54-real-use", "r55-real-use"),
    ("R54 FAST REAL-USE BUILD PASS", "R55 FAST REAL-USE BUILD PASS"),
    ("r54 FAST REAL-USE", "r55 FAST REAL-USE"),
    ("r54 FAST real-use", "r55 FAST real-use"),
    ("compatRevision = 54", "compatRevision = 55"),
]
for old, new in replacements:
    text = text.replace(old, new)

r54_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY')"
r55_guard_tail = r54_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\mcp_servers.rs') -Raw -Encoding UTF8) -match 'CAS-R55-DETACHED-MCP-HELPER')"
if r54_guard_tail not in text:
    raise SystemExit("r55 fast builder: r54 materialized guard tail missing")
text = text.replace(r54_guard_tail, r55_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r55_unified.py",
    "compat_revision=55",
    "app_version=2\\.4\\.5\\+55",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R51-COMPACTION-ROLE-TRUTH",
    "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
    "CAS-R55-DETACHED-MCP-HELPER",
    "src-tauri\\src\\admin\\services\\mcp_servers.rs",
    "r55-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r55 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R55 FAST BUILDER PREP PASS")
print("- reused the proven r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r55 materializer/version/output/materialization guards only")
print("- warm materialization now also requires the detached MCP helper source marker")
print("- full validation suites remain intentionally skipped for this local real-use build")
