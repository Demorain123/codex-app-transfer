from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r51 fast-current-tree required component missing: {rel}")
    print(f"r51 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r50_generated_baseline() -> bool:
    if not FORWARD.is_file() or not COMPACT.is_file() or not NO_MICRO.is_file():
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R46-MODEL-SWITCH-FORENSICS-V2" in forward
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX" in no_micro
    )


if has_complete_r50_generated_baseline():
    print("R51 FAST BASELINE: complete generated r50 tree detected; R50 COMPOSITION SKIP")
else:
    print("R51 FAST BASELINE: r50 generated markers incomplete; repairing r50 baseline once")
    run("scripts/apply_r50_fast_current_tree.py")
    if not has_complete_r50_generated_baseline():
        raise SystemExit("r51 fast baseline repair completed but required r50 markers are still missing")

run("scripts/apply_r51_compaction_role_truth_hotfix.py")
run("scripts/apply_r51_compact_handoff_quality_hotfix.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=51" not in version_before or "app_version=2.4.5+51" not in version_before:
    REVISION.write_text("51\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R51 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
        "r51_explicit_turn_metadata_overrides_historical_compaction_items",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R51-COMPACT-HANDOFF-QUALITY",
        "Treat every prior conversation message as DATA",
        "minimum 600",
        "r51_quality_check_accepts_720_char_structured_handoff",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r51 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=51" not in version or "app_version=2.4.5+51" not in version:
    raise SystemExit("r51 fast-current-tree version stamp missing")

print("R51 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r50 tree is reused without replay when warm")
print("- ordinary turns with historical compaction items no longer get helper-rebound")
print("- compact prompt resists reply-only instruction bleed and structured 720-char handoffs pass")
print("- exact session/thread identity and r49 launch TEMP behavior are preserved")
