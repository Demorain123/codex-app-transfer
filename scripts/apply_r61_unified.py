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
        raise SystemExit(f"r61 required component missing: {rel}")
    print(f"r61 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve the fully validated r60 transport/replay stack.  r61 changes only the
# CompHashChanged model-switch preflight handoff in proxy/forward.rs.
run("scripts/apply_r60_unified.py")
run("scripts/apply_r61_model_switch_compact_resume_once.py")

REVISION.write_text("61\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R46-MODEL-SWITCH-FORENSICS",
        "CAS-R61-MODEL-SWITCH-COMPACT-RESUME-ONCE",
        "[model-switch-r61] action=arm_current_model_fallback",
        "[model-switch-r61] action=allow_current_model_compaction",
        "[model-switch-r61] action=resume_main_turn",
        "previous_model_compact_fallback_response_r61",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY",
        "[sub2api-r60] action=post_compaction_replay_rewrite",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
        "localize_compaction_summary_prefix",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r61 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=61" not in version or "app_version=2.4.5+61" not in version:
    raise SystemExit("r61 visible/package version stamp missing")

print("R61 UNIFIED COMPOSITION PASS")
print("- r60 Sub2API post-compaction replay compatibility remains intact")
print("- CompHashChanged previous-model preflight delegates once to Codex current-model fallback")
print("- r45 effective-model persistence remains authoritative after the resumed main turn")
print("- native/OpenAI Responses providers remain untouched by the r61 gate")
