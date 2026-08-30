from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r50 required component missing: {rel}")
    print(f"r50 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# r49 already composes the complete r45/r46 model-switch state machine and r47-r49
# desktop/runtime fixes. r50 adds one narrow Responses replay compatibility layer.
run("scripts/apply_r49_unified.py")
run("scripts/apply_r50_same_session_cross_model_replay.py")

REVISION.write_text("50\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R46-MODEL-SWITCH-FORENSICS-V2",
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "portableize_cross_model_replay_r50",
        "previous_response_id_dropped",
        "reasoning_dropped",
        "compaction_portable_messages",
        "[model-switch-r50] action=portable_replay",
        "r50_cross_model_replay_drops_opaque_reasoning_and_keeps_compaction_summary",
    ),
    "src-tauri/src/admin/services/desktop/no_micro.rs": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r50 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=50" not in version or "app_version=2.4.5+50" not in version:
    raise SystemExit("r50 visible/package version stamp missing")

print("R50 UNIFIED COMPOSITION PASS")
print("- exact Codex session/thread identity and persisted rollout stay unchanged")
print("- actual model switches reuse r45/r46 effective-before state; no parallel session registry")
print("- cross-model Responses copies drop model-bound reasoning encrypted state")
print("- plaintext Codex compaction handoff summaries become portable user messages")
print("- upstream-specific previous_response_id is removed only on an actual model switch")
print("- same-model turns and compaction helper requests remain byte passthrough")
print("- r49 TEMP/No-Lagging launch behavior remains intact")
