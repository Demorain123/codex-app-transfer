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
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r54 fast-current-tree required component missing: {rel}")
    print(f"r54 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r53_generated_baseline() -> bool:
    if not all(path.is_file() for path in (FORWARD, SUB2API, RESPONSES, COMPACT, NO_MICRO)):
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    sub2api = SUB2API.read_text(encoding="utf-8")
    responses = RESPONSES.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R51-COMPACTION-ROLE-TRUTH" in forward
        and "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION" in sub2api
        and "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT" in sub2api
        and "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD" in responses
        and "CAS-R53-SUB2API-OAUTH-COMPACT-MAX-OUTPUT" in responses
        and "CAS-R51-COMPACT-HANDOFF-QUALITY" in compact
        and "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION" in compact
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX" in no_micro
    )


if has_complete_r53_generated_baseline():
    print("R54 FAST BASELINE: complete generated r53 tree detected; R53 COMPOSITION SKIP")
else:
    print("R54 FAST BASELINE: r53 generated markers incomplete; repairing r53 baseline once")
    run("scripts/apply_r53_fast_current_tree.py")
    if not has_complete_r53_generated_baseline():
        raise SystemExit("r54 fast baseline repair completed but required r53 markers are still missing")

run("scripts/apply_r54_compact_responses_sse_reassembly.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=54" not in version_before or "app_version=2.4.5+54" not in version_before:
    REVISION.write_text("54\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R54 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
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
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r54 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=54" not in version or "app_version=2.4.5+54" not in version:
    raise SystemExit("r54 fast-current-tree version stamp missing")

print("R54 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r53 tree is reused without replay when warm")
print("- Sub2API Responses SSE compact replies are reassembled before JSON summary extraction")
print("- ordinary JSON replies, ordinary turns, session identity, and r49 launch TEMP remain unchanged")
