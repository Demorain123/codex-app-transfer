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
        raise SystemExit(f"r46 fast-current-tree required component missing: {rel}")
    print(f"r46 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_r45_generated_baseline() -> bool:
    if not FORWARD.is_file():
        return False
    source = FORWARD.read_text(encoding="utf-8")
    return (
        "CAS-R45-MODEL-SWITCH-CONTINUITY" in source
        and "CAS-R45-COMPACTION-METADATA-TRUTH" in source
    )


# FAST local-dev policy:
# - Normal warm workspace: preserve the already-generated r45/r46 tree and only layer
#   current r46 hotfixes. No r24-r45 historical replay.
# - After an explicit git reset/clean clone, the checked-in branch is an overlay source
#   baseline and does NOT contain generated r45 markers. In that one situation, bootstrap
#   the canonical generated r46 tree once. Subsequent runs are warm again.
if not has_r45_generated_baseline():
    print("R46 FAST BASELINE BOOTSTRAP: generated r45 markers are missing.")
    print("- running canonical r46 materialization ONCE after reset/clean checkout")
    print("- later FAST runs will reuse this generated tree and skip historical replay")
    run("scripts/apply_r46_unified.py")
    if not has_r45_generated_baseline():
        raise SystemExit("r46 fast baseline bootstrap completed but r45 generated markers are still missing")
else:
    print("R46 FAST WARM BASELINE: r45 generated markers present; historical replay SKIP")

    run("scripts/apply_r46_thread_recovery_backend_fixes.py")
    run("scripts/apply_r46_thread_recovery_backup_hardening.py")
    run("scripts/apply_r46_recovery_backup_vdrive_hotfix.py")
    run("scripts/apply_r46_codex_cli_launchability_hotfix.py")
    run("scripts/apply_r46_codex_cli_shadow_copy_hotfix.py")
    run("scripts/apply_r46_revert_compat_logging_hotfix.py")
    run("scripts/apply_r46_resume_before_rollback_hotfix.py")
    run("scripts/apply_r46_model_switch_forensics_v2.py")
    run("scripts/apply_r46_thread_recovery_ui.py")
    run("scripts/apply_r46_recovery_explainability_preflight.py")
    run("scripts/apply_r46_recovery_explainability_ui.py")
    run("scripts/apply_r46_failure_boundary_fork_hotfix.py")
    run("scripts/apply_r46_chain_health_recovery_hint.py")
    run("scripts/apply_r46_generic_repair_loop_guard.py")

    REVISION.write_text("46\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY",
        "CAS-R46-RECOVERY-STATE-DB-BACKUP",
        "CAS-R46-RECOVERY-BACKUP-VDRIVE",
        "CAS-R46-CODEX-CLI-LAUNCHABILITY-HOTFIX",
        "CAS-R46-CODEX-CLI-SHADOW-COPY",
        "CAS-R46-REVERT-COMPAT-LOGGING-HOTFIX",
        "CAS-R46-RESUME-BEFORE-ROLLBACK-HOTFIX",
        "CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX",
        '"thread/resume"',
        "stage=thread_loaded",
        "stage=fork_boundary",
        "latest_failed_compaction_turn_id",
        '"thread/rollback"',
        '"thread/fork"',
    ),
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R45-COMPACTION-METADATA-TRUTH",
        "CAS-R46-MODEL-SWITCH-FORENSICS-V2",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI",
        "CAS-R46-RECOVERY-EXPLAINABILITY-UI",
        "同 ID 回退 1 轮（推荐）",
        "创建故障前恢复副本（推荐）",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r46 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=46" not in version or "app_version=2.4.5+46" not in version:
    raise SystemExit("r46 fast-current-tree version stamp missing")

print("R46 FAST CURRENT-TREE COMPOSITION PASS")
print("- canonical baseline bootstraps only when generated r45 markers are absent")
print("- warm runs skip historical r24-r45 replay")
print("- current r46 recovery hotfix stack is materialized")
print("- thread/resume-before-rollback is present")
print("- recovery-copy forks before the exact failed compaction boundary")
