from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r60-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r61-fast-real-use.ps1"

if not SOURCE.is_file():
    prep60 = ROOT / "scripts/prepare-r60-fast-builder.py"
    if not prep60.is_file():
        raise SystemExit("r61 fast builder: r60 builder and preparation script are both missing")
    print("r61 fast builder: generating reusable r60 builder once")
    runpy.run_path(str(prep60), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r61 fast builder: generated r60 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r60 - FAST REAL-USE BUILD", "Codex App Transfer r61 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r60", "[1/9] Materialize r61"),
    ("Warm r60 materialization detected; SKIP.", "Warm r61 materialization detected; SKIP."),
    (".\\scripts\\apply_r60_unified.py", ".\\scripts\\apply_r61_unified.py"),
    ("compat_revision=60", "compat_revision=61"),
    ("app_version=2\\.4\\.5\\+60", "app_version=2\\.4\\.5\\+61"),
    ("app_version=2.4.5+60", "app_version=2.4.5+61"),
    ("2.4.5+60", "2.4.5+61"),
    ("2.4.5-r60", "2.4.5-r61"),
    ("r60-real-use", "r61-real-use"),
    ("R60 FAST REAL-USE BUILD PASS", "R61 FAST REAL-USE BUILD PASS"),
    ("r60 FAST REAL-USE", "r61 FAST REAL-USE"),
    ("r60 FAST real-use", "r61 FAST real-use"),
    ("compatRevision = 60", "compatRevision = 61"),
]
for old, new in replacements:
    text = text.replace(old, new)

r60_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\responses.rs') -Raw -Encoding UTF8) -match 'CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK')"
r61_guard = r60_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R61-LEGACY-COMPACTION-V1')"
if r60_guard not in text:
    raise SystemExit("r61 fast builder: r60 materialized guard tail missing")
text = text.replace(r60_guard, r61_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r61_unified.py",
    "compat_revision=61",
    "app_version=2\\.4\\.5\\+61",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "src-tauri\\src\\admin\\services\\desktop\\process.rs",
    "r61-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r61 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R61 FAST BUILDER PREP PASS")
print("- reused the proven r60/r59/r58/r57/r56 DevCache and toolchain")
print("- changed r61 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
