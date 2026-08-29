from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r46-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r47-fast-real-use.ps1"

if not SOURCE.is_file():
    raise SystemExit("r47 fast builder: proven r46 builder is missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r46 - FAST REAL-USE BUILD", "Codex App Transfer r47 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r46", "[1/9] Materialize r47"),
    ("Warm r46 materialization detected; SKIP.", "Warm r47 materialization detected; SKIP."),
    (".\\scripts\\apply_r46_unified.py", ".\\scripts\\apply_r47_unified.py"),
    ("compat_revision=46", "compat_revision=47"),
    ("app_version=2\\.4\\.5\\+46", "app_version=2\\.4\\.5\\+47"),
    ("app_version=2.4.5+46", "app_version=2.4.5+47"),
    ("2.4.5+46", "2.4.5+47"),
    ("2.4.5-r46", "2.4.5-r47"),
    ("r46-real-use", "r47-real-use"),
    ("R46 FAST REAL-USE BUILD PASS", "R47 FAST REAL-USE BUILD PASS"),
    ("r46 FAST REAL-USE", "r47 FAST REAL-USE"),
    ("r46 FAST real-use", "r47 FAST real-use"),
    ("compatRevision = 46", "compatRevision = 47"),
]
for old, new in replacements:
    text = text.replace(old, new)

# The generated source tree must contain the r47 launch overlay before packaging.
old_materialized = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY')"
new_materialized = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP')"
if old_materialized not in text:
    raise SystemExit("r47 fast builder: r46 materialized guard anchor missing")
text = text.replace(old_materialized, new_materialized, 1)

# Keep every proven r46 build-tool/cache guard. Only revision/materializer/output changes.
required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r47_unified.py",
    "compat_revision=47",
    "app_version=2\\.4\\.5\\+47",
    "CAS-R47-CODEX-CUSTOM-TEMP",
    "r47-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r47 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R47 FAST BUILDER PREP PASS")
print("- reused r46 DevCache / native toolchain / frontend direct-entry build path")
print("- changed only r47 materialization/version/output guards")
