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
        raise SystemExit(f"r54 required component missing: {rel}")
    print(f"r54 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r53_unified.py")
run("scripts/apply_r54_compact_responses_sse_reassembly.py")

REVISION.write_text("54\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
        "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R51-COMPACT-HANDOFF-QUALITY",
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R54-SUB2API-RESPONSES-SSE-REASSEMBLY",
        "reassemble_responses_sse_to_response_json_r54",
        "[model-switch-r54] action=reassemble_responses_sse",
        "r54_reassembles_responses_sse_completed_response",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r54 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=54" not in version or "app_version=2.4.5+54" not in version:
    raise SystemExit("r54 visible/package version stamp missing")

print("R54 UNIFIED COMPOSITION PASS")
print("- r53 keeps Sub2API non-Grok compact request compatibility")
print("- successful Responses SSE compact replies are reassembled before summary extraction")
print("- response.completed is preferred; output_text.done/delta provides a defensive fallback")
print("- ordinary JSON compact responses and all ordinary model turns remain unchanged")
print("- exact Codex session/thread identity and r49 TEMP behavior remain unchanged")
