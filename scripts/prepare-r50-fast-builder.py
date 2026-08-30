from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r49-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r50-fast-real-use.ps1"

if not SOURCE.is_file():
    prep49 = ROOT / "scripts/prepare-r49-fast-builder.py"
    if not prep49.is_file():
        raise SystemExit("r50 fast builder: r49 builder and preparation script are both missing")
    print("r50 fast builder: generating reusable r49 builder once")
    runpy.run_path(str(prep49), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r50 fast builder: generated r49 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r49 - FAST REAL-USE BUILD", "Codex App Transfer r50 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r49", "[1/9] Materialize r50"),
    ("Warm r49 materialization detected; SKIP.", "Warm r50 materialization detected; SKIP."),
    (".\\scripts\\apply_r49_unified.py", ".\\scripts\\apply_r50_unified.py"),
    ("compat_revision=49", "compat_revision=50"),
    ("app_version=2\\.4\\.5\\+49", "app_version=2\\.4\\.5\\+50"),
    ("app_version=2.4.5+49", "app_version=2.4.5+50"),
    ("2.4.5+49", "2.4.5+50"),
    ("2.4.5-r49", "2.4.5-r50"),
    ("r49-real-use", "r50-real-use"),
    ("R49 FAST REAL-USE BUILD PASS", "R50 FAST REAL-USE BUILD PASS"),
    ("r49 FAST REAL-USE", "r50 FAST REAL-USE"),
    ("r49 FAST real-use", "r50 FAST real-use"),
    ("compatRevision = 49", "compatRevision = 50"),
]
for old, new in replacements:
    text = text.replace(old, new)

old_guard = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'frontend\\src\\pages\\ProvidersPage.vue') -Raw -Encoding UTF8) -match 'CAS-R48-PROVIDER-TEMP-CONTROL') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\no_micro.rs') -Raw -Encoding UTF8) -match 'CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH')"
new_guard = old_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY')"
if old_guard not in text:
    raise SystemExit("r50 fast builder: r49 materialized guard anchor missing")
text = text.replace(old_guard, new_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r50_unified.py",
    "compat_revision=50",
    "app_version=2\\.4\\.5\\+50",
    "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "r50-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r50 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R50 FAST BUILDER PREP PASS")
print("- reused the proven r49/r48/r47/r46 DevCache and native/frontend toolchain")
print("- changed only r50 materializer/version/output/materialization guards")
print("- full validation suites remain intentionally skipped for this local real-use build")
