from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r55-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r56-fast-real-use.ps1"

if not SOURCE.is_file():
    prep55 = ROOT / "scripts/prepare-r55-fast-builder.py"
    if not prep55.is_file():
        raise SystemExit("r56 fast builder: r55 builder and preparation script are both missing")
    print("r56 fast builder: generating reusable r55 builder once")
    runpy.run_path(str(prep55), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r56 fast builder: generated r55 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r55 - FAST REAL-USE BUILD", "Codex App Transfer r56 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r55", "[1/9] Materialize r56"),
    ("Warm r55 materialization detected; SKIP.", "Warm r56 materialization detected; SKIP."),
    (".\\scripts\\apply_r55_unified.py", ".\\scripts\\apply_r56_unified.py"),
    ("compat_revision=55", "compat_revision=56"),
    ("app_version=2\\.4\\.5\\+55", "app_version=2\\.4\\.5\\+56"),
    ("app_version=2.4.5+55", "app_version=2.4.5+56"),
    ("2.4.5+55", "2.4.5+56"),
    ("2.4.5-r55", "2.4.5-r56"),
    ("r55-real-use", "r56-real-use"),
    ("R55 FAST REAL-USE BUILD PASS", "R56 FAST REAL-USE BUILD PASS"),
    ("r55 FAST REAL-USE", "r56 FAST REAL-USE"),
    ("r55 FAST real-use", "r56 FAST real-use"),
    ("compatRevision = 55", "compatRevision = 56"),
]
for old, new in replacements:
    text = text.replace(old, new)

r55_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\mcp_servers.rs') -Raw -Encoding UTF8) -match 'CAS-R55-DETACHED-MCP-HELPER')"
r56_guard_tail = r55_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK')"
if r55_guard_tail not in text:
    raise SystemExit("r56 fast builder: r55 materialized guard tail missing")
text = text.replace(r55_guard_tail, r56_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r56_unified.py",
    "compat_revision=56",
    "app_version=2\\.4\\.5\\+56",
    "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "crates\\adapters\\src\\responses\\compact.rs",
    "r56-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r56 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R56 FAST BUILDER PREP PASS")
print("- reused the proven r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r56 materializer/version/output/materialization guards only")
print("- warm materialization now also requires the compact SSE summary fallback marker")
print("- full validation suites remain intentionally skipped for this local real-use build")
