from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
PROVIDERS = ROOT / "frontend/src/pages/ProvidersPage.vue"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r50 fast-current-tree required component missing: {rel}")
    print(f"r50 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r49_generated_baseline() -> bool:
    if not FORWARD.is_file() or not NO_MICRO.is_file() or not PROVIDERS.is_file():
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    providers = PROVIDERS.read_text(encoding="utf-8")
    return (
        "CAS-R45-MODEL-SWITCH-CONTINUITY" in forward
        and "CAS-R46-MODEL-SWITCH-FORENSICS-V2" in forward
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX" in no_micro
        and "CAS-R48-PROVIDER-TEMP-CONTROL" in providers
    )


if has_complete_r49_generated_baseline():
    print("R50 FAST BASELINE: complete generated r49 tree detected; R49 COMPOSITION SKIP")
else:
    print("R50 FAST BASELINE: r49 generated markers incomplete; repairing r49 baseline once")
    run("scripts/apply_r49_fast_current_tree.py")
    if not has_complete_r49_generated_baseline():
        raise SystemExit("r50 fast baseline repair completed but required r49 markers are still missing")

run("scripts/apply_r50_same_session_cross_model_replay.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=50" not in version_before or "app_version=2.4.5+50" not in version_before:
    REVISION.write_text("50\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R50 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "portableize_cross_model_replay_r50",
        "previous_response_id_dropped",
        "reasoning_dropped",
        "compaction_portable_messages",
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
            raise SystemExit(f"r50 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=50" not in version or "app_version=2.4.5+50" not in version:
    raise SystemExit("r50 fast-current-tree version stamp missing")

print("R50 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r49 tree is reused without replay when warm")
print("- same-session cross-model replay compatibility is the only r50 runtime delta")
print("- persisted rollout/session ids are untouched; only outbound Responses bytes are portableized")
print("- r49 launch TEMP behavior and existing DevCache remain reusable")
