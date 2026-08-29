from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


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


# FAST local-dev path: the checked-in dev-r46 branch already contains the r45/r46
# baseline. Do NOT replay r24..r45 here. Only layer the current r46 hotfixes that
# are intentionally kept as replayable overlays, then stamp r46.
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
        '"thread/resume"',
        "stage=thread_loaded",
        '"thread/rollback"',
    ),
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R46-MODEL-SWITCH-FORENSICS-V2",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI",
        "CAS-R46-RECOVERY-EXPLAINABILITY-UI",
        "同 ID 回退 1 轮（推荐）",
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
print("- skipped historical r24-r45 replay")
print("- current r46 recovery hotfix stack is materialized")
print("- thread/resume-before-rollback is present")
