from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r47-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r48-fast-real-use.ps1"

if not SOURCE.is_file():
    prep47 = ROOT / "scripts/prepare-r47-fast-builder.py"
    if not prep47.is_file():
        raise SystemExit("r48 fast builder: r47 builder and preparation script are both missing")
    print("r48 fast builder: generating reusable r47 builder once")
    runpy.run_path(str(prep47), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r48 fast builder: generated r47 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r47 - FAST REAL-USE BUILD", "Codex App Transfer r48 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r47", "[1/9] Materialize r48"),
    ("Warm r47 materialization detected; SKIP.", "Warm r48 materialization detected; SKIP."),
    (".\\scripts\\apply_r47_unified.py", ".\\scripts\\apply_r48_unified.py"),
    ("compat_revision=47", "compat_revision=48"),
    ("app_version=2\\.4\\.5\\+47", "app_version=2\\.4\\.5\\+48"),
    ("app_version=2.4.5+47", "app_version=2.4.5+48"),
    ("2.4.5+47", "2.4.5+48"),
    ("2.4.5-r47", "2.4.5-r48"),
    ("r47-real-use", "r48-real-use"),
    ("R47 FAST REAL-USE BUILD PASS", "R48 FAST REAL-USE BUILD PASS"),
    ("r47 FAST REAL-USE", "r48 FAST REAL-USE"),
    ("r47 FAST real-use", "r48 FAST real-use"),
    ("compatRevision = 47", "compatRevision = 48"),
]
for old, new in replacements:
    text = text.replace(old, new)

# Extend r47's materialization guard with the provider-toolbar marker. The r47
# process marker remains the proof that the process-local TEMP backend exists.
old_guard = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP')"
new_guard = old_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'frontend\\src\\pages\\ProvidersPage.vue') -Raw -Encoding UTF8) -match 'CAS-R48-PROVIDER-TEMP-CONTROL')"
if old_guard not in text:
    raise SystemExit("r48 fast builder: r47 materialized guard anchor missing")
text = text.replace(old_guard, new_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r48_unified.py",
    "compat_revision=48",
    "app_version=2\\.4\\.5\\+48",
    "CAS-R47-CODEX-CUSTOM-TEMP",
    "CAS-R48-PROVIDER-TEMP-CONTROL",
    "r48-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r48 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R48 FAST BUILDER PREP PASS")
print("- reused r47/r46 DevCache, frontend direct-entry build path and native toolchain")
print("- changed only r48 materializer/version/output/materialization guards")
