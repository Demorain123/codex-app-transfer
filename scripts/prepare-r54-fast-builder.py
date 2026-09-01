from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r53-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r54-fast-real-use.ps1"

if not SOURCE.is_file():
    prep53 = ROOT / "scripts/prepare-r53-fast-builder.py"
    if not prep53.is_file():
        raise SystemExit("r54 fast builder: r53 builder and preparation script are both missing")
    print("r54 fast builder: generating reusable r53 builder once")
    runpy.run_path(str(prep53), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r54 fast builder: generated r53 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r53 - FAST REAL-USE BUILD", "Codex App Transfer r54 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r53", "[1/9] Materialize r54"),
    ("Warm r53 materialization detected; SKIP.", "Warm r54 materialization detected; SKIP."),
    (".\\scripts\\apply_r53_unified.py", ".\\scripts\\apply_r54_unified.py"),
    ("compat_revision=53", "compat_revision=54"),
    ("app_version=2\\.4\\.5\\+53", "app_version=2\\.4\\.5\\+54"),
    ("app_version=2.4.5+53", "app_version=2.4.5+54"),
    ("2.4.5+53", "2.4.5+54"),
    ("2.4.5-r53", "2.4.5-r54"),
    ("r53-real-use", "r54-real-use"),
    ("R53 FAST REAL-USE BUILD PASS", "R54 FAST REAL-USE BUILD PASS"),
    ("r53 FAST REAL-USE", "r54 FAST REAL-USE"),
    ("r53 FAST real-use", "r54 FAST real-use"),
    ("compatRevision = 53", "compatRevision = 54"),
]
for old, new in replacements:
    text = text.replace(old, new)

old_guard = "((Get-Content -LiteralPath $recoveryBackend -Raw -Encoding UTF8) -match 'CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\process.rs') -Raw -Encoding UTF8) -match 'CAS-R47-CODEX-CUSTOM-TEMP') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'frontend\\src\\pages\\ProvidersPage.vue') -Raw -Encoding UTF8) -match 'CAS-R48-PROVIDER-TEMP-CONTROL') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\services\\desktop\\no_micro.rs') -Raw -Encoding UTF8) -match 'CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\proxy\\src\\forward.rs') -Raw -Encoding UTF8) -match 'CAS-R51-COMPACTION-ROLE-TRUTH') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R51-COMPACT-HANDOFF-QUALITY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\sub2api_grok_compat.rs') -Raw -Encoding UTF8) -match 'CAS-R52-SUB2API-CROSS-MODEL-COMPACTION') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\responses.rs') -Raw -Encoding UTF8) -match 'CAS-R52-SUB2API-CROSS-MODEL-COMPACTION') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\responses.rs') -Raw -Encoding UTF8) -match 'CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R52-SUB2API-CROSS-MODEL-COMPACTION') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\sub2api_grok_compat.rs') -Raw -Encoding UTF8) -match 'CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\responses.rs') -Raw -Encoding UTF8) -match 'CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT')"
new_guard = old_guard + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\responses\\compact.rs') -Raw -Encoding UTF8) -match 'CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY')"
if old_guard not in text:
    raise SystemExit("r54 fast builder: r53 materialized guard anchor missing")
text = text.replace(old_guard, new_guard, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r54_unified.py",
    "compat_revision=54",
    "app_version=2\\.4\\.5\\+54",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R51-COMPACTION-ROLE-TRUTH",
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
    "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
    "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT",
    "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
    "r54-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r54 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R54 FAST BUILDER PREP PASS")
print("- reused the proven r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed only r54 materializer/version/output/materialization guards")
print("- warm materialization now requires the Responses SSE reassembly marker")
print("- full validation suites remain intentionally skipped for this local real-use build")
