from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r58-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r59-fast-real-use.ps1"

if not SOURCE.is_file():
    prep58 = ROOT / "scripts/prepare-r58-fast-builder.py"
    if not prep58.is_file():
        raise SystemExit("r59 fast builder: r58 builder and preparation script are both missing")
    print("r59 fast builder: generating reusable r58 builder once")
    runpy.run_path(str(prep58), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r59 fast builder: generated r58 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r58 - FAST REAL-USE BUILD", "Codex App Transfer r59 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r58", "[1/9] Materialize r59"),
    ("Warm r58 materialization detected; SKIP.", "Warm r59 materialization detected; SKIP."),
    (".\\scripts\\apply_r58_unified.py", ".\\scripts\\apply_r59_unified.py"),
    ("compat_revision=58", "compat_revision=59"),
    ("app_version=2\\.4\\.5\\+58", "app_version=2\\.4\\.5\\+59"),
    ("app_version=2.4.5+58", "app_version=2.4.5+59"),
    ("2.4.5+58", "2.4.5+59"),
    ("2.4.5-r58", "2.4.5-r59"),
    ("r58-real-use", "r59-real-use"),
    ("R58 FAST REAL-USE BUILD PASS", "R59 FAST REAL-USE BUILD PASS"),
    ("r58 FAST REAL-USE", "r59 FAST REAL-USE"),
    ("r58 FAST real-use", "r59 FAST real-use"),
    ("compatRevision = 58", "compatRevision = 59"),
]
for old, new in replacements:
    text = text.replace(old, new)

r58_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD')"
r59_guard_tail = r58_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\handlers\\thread_recovery.rs') -Raw -Encoding UTF8) -match 'CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY')"
if r58_guard_tail not in text:
    raise SystemExit("r59 fast builder: r58 materialized guard tail missing")
text = text.replace(r58_guard_tail, r59_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r59_unified.py",
    "compat_revision=59",
    "app_version=2\\.4\\.5\\+59",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "src-tauri\\src\\admin\\handlers\\thread_recovery.rs",
    "r59-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r59 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R59 FAST BUILDER PREP PASS")
print("- reused the proven r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r59 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
