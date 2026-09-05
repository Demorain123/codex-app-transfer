from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r61-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r62-fast-real-use.ps1"

if not SOURCE.is_file():
    prep61 = ROOT / "scripts/prepare-r61-fast-builder.py"
    if not prep61.is_file():
        raise SystemExit("r62 fast builder: r61 builder and preparation script are both missing")
    print("r62 fast builder: generating reusable r61 builder once")
    runpy.run_path(str(prep61), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r62 fast builder: generated r61 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r61 - FAST REAL-USE BUILD", "Codex App Transfer r62 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r61", "[1/9] Materialize r62"),
    ("Warm r61 materialization detected; SKIP.", "Warm r62 materialization detected; SKIP."),
    (".\\scripts\\apply_r61_unified.py", ".\\scripts\\apply_r62_unified.py"),
    ("compat_revision=61", "compat_revision=62"),
    ("app_version=2\\.4\\.5\\+61", "app_version=2\\.4\\.5\\+62"),
    ("app_version=2.4.5+61", "app_version=2.4.5+62"),
    ("2.4.5+61", "2.4.5+62"),
    ("2.4.5-r61", "2.4.5-r62"),
    ("r61-real-use", "r62-real-use"),
    ("R61 FAST REAL-USE BUILD PASS", "R62 FAST REAL-USE BUILD PASS"),
    ("r61 FAST REAL-USE", "r62 FAST REAL-USE"),
    ("r61 FAST real-use", "r62 FAST real-use"),
    ("compatRevision = 61", "compatRevision = 62"),
]
for old, new in replacements:
    text = text.replace(old, new)

r61_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R61-LEGACY-COMPACTION-V1')"
r62_guard = r61_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R62-COMPACT-SUMMARY-SELF-REPAIR')"
if r61_guard not in text:
    raise SystemExit("r62 fast builder: r61 materialized guard tail missing")
text = text.replace(r61_guard, r62_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r62_unified.py",
    "compat_revision=62",
    "app_version=2\\.4\\.5\\+62",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
    "crates\\adapters\\src\\responses\\compact.rs",
    "r62-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r62 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R62 FAST BUILDER PREP PASS")
print("- reused the proven r61/r60/r59/r58/r57/r56 DevCache and toolchain")
print("- changed r62 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
