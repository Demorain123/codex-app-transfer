from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r63-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r64-fast-real-use.ps1"

if not SOURCE.is_file():
    prep63 = ROOT / "scripts/prepare-r63-fast-builder.py"
    if not prep63.is_file():
        raise SystemExit("r64 fast builder: r63 builder and preparation script are both missing")
    print("r64 fast builder: generating reusable r63 builder once")
    runpy.run_path(str(prep63), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r64 fast builder: generated r63 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r63 - FAST REAL-USE BUILD", "Codex App Transfer r64 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r63", "[1/9] Materialize r64"),
    ("Warm r63 materialization detected; SKIP.", "Warm r64 materialization detected; SKIP."),
    (".\\scripts\\apply_r63_unified.py", ".\\scripts\\apply_r64_unified.py"),
    ("compat_revision=63", "compat_revision=64"),
    ("app_version=2\\.4\\.5\\+63", "app_version=2\\.4\\.5\\+64"),
    ("app_version=2.4.5+63", "app_version=2.4.5+64"),
    ("2.4.5+63", "2.4.5+64"),
    ("2.4.5-r63", "2.4.5-r64"),
    ("r63-real-use", "r64-real-use"),
    ("R63 FAST REAL-USE BUILD PASS", "R64 FAST REAL-USE BUILD PASS"),
    ("r63 FAST REAL-USE", "r64 FAST REAL-USE"),
    ("r63 FAST real-use", "r64 FAST real-use"),
    ("compatRevision = 63", "compatRevision = 64"),
]
for old, new in replacements:
    text = text.replace(old, new)

r61_guard = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R61-LEGACY-COMPACTION-V1')"
r62_guard = r61_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R62-COMPACT-SUMMARY-SELF-REPAIR')"
r63_guard = r62_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE')"
r64_guard = r63_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R64-POST-COMPACT-CONTINUATION-GUARD')"
if r63_guard not in text:
    raise SystemExit("r64 fast builder: r63 materialized guard tail missing")
text = text.replace(r63_guard, r64_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r64_unified.py",
    "compat_revision=64",
    "app_version=2\\.4\\.5\\+64",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "crates\\proxy\\src\\forward.rs",
    "src-tauri\\src\\admin\\services\\desktop\\process.rs",
    "r64-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r64 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R64 FAST BUILDER PREP PASS")
print("- reused the proven r63/r62/r61/r60/r59/r58/r57/r56 DevCache and toolchain")
print("- changed r64 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
