from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r56-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r57-fast-real-use.ps1"

if not SOURCE.is_file():
    prep56 = ROOT / "scripts/prepare-r56-fast-builder.py"
    if not prep56.is_file():
        raise SystemExit("r57 fast builder: r56 builder and preparation script are both missing")
    print("r57 fast builder: generating reusable r56 builder once")
    runpy.run_path(str(prep56), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r57 fast builder: generated r56 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r56 - FAST REAL-USE BUILD", "Codex App Transfer r57 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r56", "[1/9] Materialize r57"),
    ("Warm r56 materialization detected; SKIP.", "Warm r57 materialization detected; SKIP."),
    (".\\scripts\\apply_r56_unified.py", ".\\scripts\\apply_r57_unified.py"),
    ("compat_revision=56", "compat_revision=57"),
    ("app_version=2\\.4\\.5\\+56", "app_version=2\\.4\\.5\\+57"),
    ("app_version=2.4.5+56", "app_version=2.4.5+57"),
    ("2.4.5+56", "2.4.5+57"),
    ("2.4.5-r56", "2.4.5-r57"),
    ("r56-real-use", "r57-real-use"),
    ("R56 FAST REAL-USE BUILD PASS", "R57 FAST REAL-USE BUILD PASS"),
    ("r56 FAST REAL-USE", "r57 FAST REAL-USE"),
    ("r56 FAST real-use", "r57 FAST real-use"),
    ("compatRevision = 56", "compatRevision = 57"),
]
for old, new in replacements:
    text = text.replace(old, new)

r56_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK')"
r57_guard_tail = r56_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\mcp_servers.rs') -Raw -Encoding UTF8) -match 'CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION')"
if r56_guard_tail not in text:
    raise SystemExit("r57 fast builder: r56 materialized guard tail missing")
text = text.replace(r56_guard_tail, r57_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r57_unified.py",
    "compat_revision=57",
    "app_version=2\\.4\\.5\\+57",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    "src-tauri\\src\\admin\\services\\mcp_servers.rs",
    "r57-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r57 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R57 FAST BUILDER PREP PASS")
print("- reused the proven r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r57 materializer/version/output/materialization guards only")
print("- first r57 native build will compile bundled rusqlite once; later builds reuse Cargo cache")
print("- full validation suites remain intentionally skipped for this local real-use build")
