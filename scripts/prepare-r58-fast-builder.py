from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r57-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r58-fast-real-use.ps1"

if not SOURCE.is_file():
    prep57 = ROOT / "scripts/prepare-r57-fast-builder.py"
    if not prep57.is_file():
        raise SystemExit("r58 fast builder: r57 builder and preparation script are both missing")
    print("r58 fast builder: generating reusable r57 builder once")
    runpy.run_path(str(prep57), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r58 fast builder: generated r57 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r57 - FAST REAL-USE BUILD", "Codex App Transfer r58 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r57", "[1/9] Materialize r58"),
    ("Warm r57 materialization detected; SKIP.", "Warm r58 materialization detected; SKIP."),
    (".\\scripts\\apply_r57_unified.py", ".\\scripts\\apply_r58_unified.py"),
    ("compat_revision=57", "compat_revision=58"),
    ("app_version=2\\.4\\.5\\+57", "app_version=2\\.4\\.5\\+58"),
    ("app_version=2.4.5+57", "app_version=2.4.5+58"),
    ("2.4.5+57", "2.4.5+58"),
    ("2.4.5-r57", "2.4.5-r58"),
    ("r57-real-use", "r58-real-use"),
    ("R57 FAST REAL-USE BUILD PASS", "R58 FAST REAL-USE BUILD PASS"),
    ("r57 FAST REAL-USE", "r58 FAST REAL-USE"),
    ("r57 FAST real-use", "r58 FAST real-use"),
    ("compatRevision = 57", "compatRevision = 58"),
]
for old, new in replacements:
    text = text.replace(old, new)

r57_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\mcp_servers.rs') -Raw -Encoding UTF8) -match 'CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION')"
r58_guard_tail = r57_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD')"
if r57_guard_tail not in text:
    raise SystemExit("r58 fast builder: r57 materialized guard tail missing")
text = text.replace(r57_guard_tail, r58_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r58_unified.py",
    "compat_revision=58",
    "app_version=2\\.4\\.5\\+58",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "src-tauri\\src\\admin\\services\\desktop\\process.rs",
    "r58-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r58 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R58 FAST BUILDER PREP PASS")
print("- reused the proven r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r58 materializer/version/output/materialization guards only")
print("- r57 external MCP migration and build-space protections remain inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
