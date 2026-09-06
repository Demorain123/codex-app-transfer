from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r62-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r63-fast-real-use.ps1"

if not SOURCE.is_file():
    prep62 = ROOT / "scripts/prepare-r62-fast-builder.py"
    if not prep62.is_file():
        raise SystemExit("r63 fast builder: r62 builder and preparation script are both missing")
    print("r63 fast builder: generating reusable r62 builder once")
    runpy.run_path(str(prep62), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r63 fast builder: generated r62 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r62 - FAST REAL-USE BUILD", "Codex App Transfer r63 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r62", "[1/9] Materialize r63"),
    ("Warm r62 materialization detected; SKIP.", "Warm r63 materialization detected; SKIP."),
    (".\\scripts\\apply_r62_unified.py", ".\\scripts\\apply_r63_unified.py"),
    ("compat_revision=62", "compat_revision=63"),
    ("app_version=2\\.4\\.5\\+62", "app_version=2\\.4\\.5\\+63"),
    ("app_version=2.4.5+62", "app_version=2.4.5+63"),
    ("2.4.5+62", "2.4.5+63"),
    ("2.4.5-r62", "2.4.5-r63"),
    ("r62-real-use", "r63-real-use"),
    ("R62 FAST REAL-USE BUILD PASS", "R63 FAST REAL-USE BUILD PASS"),
    ("r62 FAST REAL-USE", "r63 FAST REAL-USE"),
    ("r62 FAST real-use", "r63 FAST real-use"),
    ("compatRevision = 62", "compatRevision = 63"),
]
for old, new in replacements:
    text = text.replace(old, new)

r61_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R61-LEGACY-COMPACTION-V1')"
r62_guard = r61_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R62-COMPACT-SUMMARY-SELF-REPAIR')"
r63_guard = r62_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE')"
if r62_guard not in text:
    raise SystemExit("r63 fast builder: r62 materialized guard tail missing")
text = text.replace(r62_guard, r63_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r63_unified.py",
    "compat_revision=63",
    "app_version=2\\.4\\.5\\+63",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
    "crates\\proxy\\src\\forward.rs",
    "r63-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r63 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R63 FAST BUILDER PREP PASS")
print("- reused the proven r62/r61/r60/r59/r58/r57/r56 DevCache and toolchain")
print("- changed r63 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
