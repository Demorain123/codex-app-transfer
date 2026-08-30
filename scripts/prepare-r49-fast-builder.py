from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r48-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r49-fast-real-use.ps1"

if not SOURCE.is_file():
    prep48 = ROOT / "scripts/prepare-r48-fast-builder.py"
    if not prep48.is_file():
        raise SystemExit("r49 fast builder: r48 builder and preparation script are both missing")
    print("r49 fast builder: generating reusable r48 builder once")
    runpy.run_path(str(prep48), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r49 fast builder: generated r48 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r48 - FAST REAL-USE BUILD", "Codex App Transfer r49 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r48", "[1/9] Materialize r49"),
    ("Warm r48 materialization detected; SKIP.", "Warm r49 materialization detected; SKIP."),
    (".\\scripts\\apply_r48_unified.py", ".\\scripts\\apply_r49_unified.py"),
    ("compat_revision=48", "compat_revision=49"),
    ("app_version=2\\.4\\.5\\+48", "app_version=2\\.4\\.5\\+49"),
    ("app_version=2.4.5+48", "app_version=2.4.5+49"),
    ("2.4.5+48", "2.4.5+49"),
    ("2.4.5-r48", "2.4.5-r49"),
    ("r48-real-use", "r49-real-use"),
    ("R48 FAST REAL-USE BUILD PASS", "R49 FAST REAL-USE BUILD PASS"),
    ("r48 FAST REAL-USE", "r49 FAST REAL-USE"),
    ("r48 FAST real-use", "r49 FAST real-use"),
    ("compatRevision = 48", "compatRevision = 49"),
]
for old, new in replacements:
    text = text.replace(old, new)

old_guard = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'frontend\\src\\pages\\ProvidersPage.vue') -Raw -Encoding UTF8) -match 'CAS-R48-PROVIDER-TEMP-CONTROL')"
new_guard = old_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\no_micro.rs') -Raw -Encoding UTF8) -match 'CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH')"
if old_guard not in text:
    raise SystemExit("r49 fast builder: r48 materialized guard anchor missing")
text = text.replace(old_guard, new_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r49_unified.py",
    "compat_revision=49",
    "app_version=2\\.4\\.5\\+49",
    "CAS-R48-PROVIDER-TEMP-CONTROL",
    "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
    "r49-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r49 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R49 FAST BUILDER PREP PASS")
print("- reused r48/r47/r46 DevCache, frontend direct-entry build path and native toolchain")
print("- changed only r49 materializer/version/output/materialization guards")
