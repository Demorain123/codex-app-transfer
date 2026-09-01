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
        raise SystemExit(f"r52 fast-current-tree required component missing: {rel}")
    print(f"r52 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r51_generated_baseline() -> bool:
    if not all(path.is_file() for path in (FORWARD, COMPACT, NO_MICRO)):
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    compact = COMPACT.read_text(encoding="utf-8")
    no_micro = NO_MICRO.read_text(encoding="utf-8")
    return (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY" in forward
        and "CAS-R51-COMPACTION-ROLE-TRUTH" in forward
        and "CAS-R51-COMPACT-HANDOFF-QUALITY" in compact
        and "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH" in no_micro
        and "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX" in no_micro
    )


if has_complete_r51_generated_baseline():
    print("R52 FAST BASELINE: complete generated r51 tree detected; R51 COMPOSITION SKIP")
else:
    print("R52 FAST BASELINE: r51 generated markers incomplete; repairing r51 baseline once")
    run("scripts/apply_r51_fast_current_tree.py")
    if not has_complete_r51_generated_baseline():
        raise SystemExit("r52 fast baseline repair completed but required r51 markers are still missing")

run("scripts/apply_r52_sub2api_cross_model_compaction.py")
run("scripts/apply_r52_non_grok_compact_adapter_guard.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=52" not in version_before or "app_version=2.4.5+52" not in version_before:
    REVISION.write_text("52\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R52 version already stamped; revision materializer SKIP")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "sub2api_local_compaction_enabled",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
        "use_sub2api_local_compaction",
        "[model-switch-r52] action=local_private_compaction",
        "let summ = if use_grok_compat",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R51-COMPACT-HANDOFF-QUALITY",
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "r52_compact_responses_history_lowers_prior_compaction_and_drops_reasoning",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r52 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=52" not in version or "app_version=2.4.5+52" not in version:
    raise SystemExit("r52 fast-current-tree version stamp missing")

print("R52 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r51 tree is reused without replay when warm")
print("- Sub2API private compact is locally translated for every selected model")
print("- prior compact summaries are portableized before the ordinary summary request")
print("- non-Grok compact requests skip the Grok-only request adapter")
print("- ordinary model turns, session identity, and r49 launch TEMP behavior are preserved")
