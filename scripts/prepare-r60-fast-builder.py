from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/build-r59-fast-real-use.ps1"
TARGET = ROOT / "scripts/build-r60-fast-real-use.ps1"

if not SOURCE.is_file():
    prep59 = ROOT / "scripts/prepare-r59-fast-builder.py"
    if not prep59.is_file():
        raise SystemExit("r60 fast builder: r59 builder and preparation script are both missing")
    print("r60 fast builder: generating reusable r59 builder once")
    runpy.run_path(str(prep59), run_name="__main__")
if not SOURCE.is_file():
    raise SystemExit("r60 fast builder: generated r59 builder is still missing")

text = SOURCE.read_text(encoding="utf-8")
replacements = [
    ("Codex App Transfer r59 - FAST REAL-USE BUILD", "Codex App Transfer r60 - FAST REAL-USE BUILD"),
    ("[1/9] Materialize r59", "[1/9] Materialize r60"),
    ("Warm r59 materialization detected; SKIP.", "Warm r60 materialization detected; SKIP."),
    (".\\scripts\\apply_r59_unified.py", ".\\scripts\\apply_r60_unified.py"),
    ("compat_revision=59", "compat_revision=60"),
    ("app_version=2\\.4\\.5\\+59", "app_version=2\\.4\\.5\\+60"),
    ("app_version=2.4.5+59", "app_version=2.4.5+60"),
    ("2.4.5+59", "2.4.5+60"),
    ("2.4.5-r59", "2.4.5-r60"),
    ("r59-real-use", "r60-real-use"),
    ("R59 FAST REAL-USE BUILD PASS", "R60 FAST REAL-USE BUILD PASS"),
    ("r59 FAST REAL-USE", "r60 FAST REAL-USE"),
    ("r59 FAST real-use", "r60 FAST real-use"),
    ("compatRevision = 59", "compatRevision = 60"),
]
for old, new in replacements:
    text = text.replace(old, new)

r59_guard_tail = " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'src-tauri\\src\\admin\\handlers\\thread_recovery.rs') -Raw -Encoding UTF8) -match 'CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY')"
r60_guard_tail = r59_guard_tail + " -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\sub2api_grok_compat.rs') -Raw -Encoding UTF8) -match 'CAS-R60-SUB2API-POST-COMPACTION-REPLAY') -and ((Get-Content -LiteralPath (Join-Path $repoRoot 'crates\\adapters\\src\\mapper\\responses.rs') -Raw -Encoding UTF8) -match 'CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK')"
if r59_guard_tail not in text:
    raise SystemExit("r60 fast builder: r59 materialized guard tail missing")
text = text.replace(r59_guard_tail, r60_guard_tail, 1)

required = (
    "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD",
    "V:\\Codex-App-Transfer-DevCache",
    ".\\scripts\\apply_r60_unified.py",
    "compat_revision=60",
    "app_version=2\\.4\\.5\\+60",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
    "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    "crates\\adapters\\src\\mapper\\sub2api_grok_compat.rs",
    "crates\\adapters\\src\\mapper\\responses.rs",
    "r60-real-use",
)
for marker in required:
    if marker not in text:
        raise SystemExit(f"r60 fast builder invariant missing: {marker}")

TARGET.write_text(text, encoding="utf-8")
print("R60 FAST BUILDER PREP PASS")
print("- reused the proven r59/r58/r57/r56/r55/r54/r53/r52/r51/r50/r49/r48/r47/r46 DevCache and toolchain")
print("- changed r60 materializer/version/output/materialization guards only")
print("- V: build-space protection remains inherited")
print("- full validation suites remain intentionally skipped for this local real-use build")
