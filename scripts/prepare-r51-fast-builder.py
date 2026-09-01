from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r50-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r51-fast-real-use.ps1"

if not SOURCE.is_file():
    prep50 = ROOT / "scripts/prepare-r50-fast-builder.py"
    if not prep50.is_file():
        raise SystemExit("r51 fast builder: r50 builder and preparation script are both missing")
    print("r51 fast builder: generating reusable r50 builder once")
    runpy.run_path(str(prep50), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r51 fast builder: generated r50 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r50 - FAST REAL-USE BUILD", "Codex App Transfer r51 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r50", "[1/9] Materialize r51"),
    ("Warm r50 materialization detected; SKIP.", "Warm r51 materialization detected; SKIP."),
    (".\\scripts\\apply_r50_unified.py", ".\\scripts\\apply_r51_unified.py"),
    ("compat_revision=50", "compat_revision=51"),
    ("app_version=2\\.4\\.5\\+50", "app_version=2\\.4\\.5\\+51"),
    ("app_version=2.4.5+50", "app_version=2.4.5+51"),
    ("2.4.5+50", "2.4.5+51"),
    ("2.4.5-r50", "2.4.5-r51"),
    ("r50-real-use", "r51-real-use"),
    ("R50 FAST REAL-USE BUILD PASS", "R51 FAST REAL-USE BUILD PASS"),
    ("r50 FAST REAL-USE", "r51 FAST REAL-USE"),
    ("r50 FAST real-use", "r51 FAST real-use"),
    ("compatRevision = 50", "compatRevision = 51"),
]
for old, new in replacements:
    text = text.replace(old, new)

old_guard = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'frontend\\src\\pages\\ProvidersPage.vue') -Raw -Encoding UTF8) -match 'CAS-R48-PROVIDER-TEMP-CONTROL') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\no_micro.rs') -Raw -Encoding UTF8) -match 'CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY')"
new_guard = old_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R51-COMPACTION-ROLE-TRUTH') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R51-COMPACT-HANDOFF-QUALITY')"
if old_guard not in text:
    raise SystemExit("r51 fast builder: r50 materialized guard anchor missing")
text = text.replace(old_guard, new_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r51_unified.py",
    "compat_revision=51",
    "app_version=2\\.4\\.5\\+51",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R51-COMPACTION-ROLE-TRUTH",
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "r51-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r51 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R51 FAST BUILDER PREP PASS")
print("- reused the proven r50/r49/r48/r47/r46 DevCache and native/frontend toolchain")
print("- changed only r51 materializer/version/output/materialization guards")
print("- full validation suites remain intentionally skipped for this local real-use build")
