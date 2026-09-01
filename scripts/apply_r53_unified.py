from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r53 required component missing: {rel}")
    print(f"r53 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r52_unified.py")
run("scripts/apply_r53_sub2api_compact_max_output_hotfix.py")

REVISION.write_text("53\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT",
        "sanitize_sub2api_non_grok_compact_body_r53",
        "[model-switch-r53] action=strip_max_output_tokens",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
        "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT",
        "sanitize_sub2api_non_grok_compact_body_r53(summ)",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R51-COMPACT-HANDOFF-QUALITY",
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r53 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=53" not in version or "app_version=2.4.5+53" not in version:
    raise SystemExit("r53 visible/package version stamp missing")

print("R53 UNIFIED COMPOSITION PASS")
print("- r52 still owns private compact translation and cross-model compact-history portability")
print("- non-Grok Sub2API local compact now strips max_output_tokens for OAuth auto-passthrough compatibility")
print("- Grok compact, ordinary turns, exact session/thread identity, and r49 TEMP behavior remain unchanged")
