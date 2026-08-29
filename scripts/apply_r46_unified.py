from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r46 required component missing: {rel}")
    print(f"r46 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# Preserve r45's FINAL model continuity / metadata-truth / Responses terminal tree,
# then add r46's structural forensics and explicit old-thread recovery center.
run("scripts/apply_r45_unified.py")
run("scripts/apply_r46_thread_recovery_backend_fixes.py")
run("scripts/apply_r46_thread_recovery_backup_hardening.py")
run("scripts/apply_r46_recovery_backup_vdrive_hotfix.py")
run("scripts/apply_r46_codex_cli_launchability_hotfix.py")
run("scripts/apply_r46_model_switch_forensics_v2.py")
run("scripts/apply_r46_thread_recovery_ui.py")
run("scripts/apply_r46_recovery_explainability_preflight.py")
run("scripts/apply_r46_recovery_explainability_ui.py")
run("scripts/apply_r46_chain_health_recovery_hint.py")
run("scripts/apply_r46_generic_repair_loop_guard.py")

REVISION.write_text("46\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R45-COMPACTION-METADATA-TRUTH",
        "CAS-R45-RESPONSES-SEMANTIC-TERMINAL",
        "CAS-R46-MODEL-SWITCH-FORENSICS-V2",
        "event=raw_client_status_mismatch",
        "cross_model_compaction_mismatch",
        "r46_metadata_truth_keeps_feature_flag_out_of_request_role",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY",
        "CAS-R46-RECOVERY-STATE-DB-BACKUP",
        "CAS-R46-RECOVERY-BACKUP-VDRIVE",
        "CAS-R46-CODEX-CLI-LAUNCHABILITY-HOTFIX",
        "CODEX_APP_TRANSFER_RECOVERY_BACKUP_DIR",
        "Codex-App-Transfer-Recovery-Backups",
        "find_launchable_codex_cli",
        "thread/revert",
        "thread/rollback",
        "thread/fork",
        "RECOVERY-BACKUP.json",
        "state-db-backup",
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R46-OLD-THREAD-RECOVERY-HINT",
        "same_thread_recovery_available",
        "CAS-R46-GENERIC-REPAIR-SAME-FAULT-GUARD",
        "recovery_same_fault_already_attempted",
        "r46_same_fault_signature_unlocks_after_meaningful_health_change",
    ),
    "src-tauri/src/admin/handlers/mod.rs": (
        "pub mod thread_recovery;",
    ),
    "src-tauri/src/admin/mod.rs": (
        "/api/thread-recovery/preview",
        "/api/thread-recovery/action",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI",
        "CAS-R46-RECOVERY-EXPLAINABILITY-PREFLIGHT",
        "CAS-R46-RECOVERY-EXPLAINABILITY-UI",
        "同 ID 回退 1 轮（推荐）",
        "创建恢复副本（原会话不动）",
        "旧会话恢复（先预览）",
        "已尝试，先查看结果",
        "相同故障指纹已经尝试过一次",
    ),
    "frontend/src/api/threadRecovery.ts": (
        "/api/thread-recovery/preview",
        "/api/thread-recovery/action",
        "stateDbCopies",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r46 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=46" not in version or "app_version=2.4.5+46" not in version:
    raise SystemExit("r46 visible/package version stamp missing")

print("R46 UNIFIED COMPOSITION PASS")
print("- r45 model-switch continuity + metadata truth + semantic terminal base preserved")
print("- privacy-bounded structural model-switch forensics v2 added")
print("- read-only old-thread recovery preview added")
print("- recovery buttons explain applicability / side effects before execution")
print("- unchanged fault signature is locked in both UI and backend after one generic repair attempt")
print("- same-thread one-turn rewind prefers thread/revert, method-not-found falls back to rollback(1)")
print("- fork recovery remains non-destructive fallback")
print("- rollout + cold Codex state DB backup happens before every recovery mutation")
print("- large recovery backups prefer V:\\Codex-App-Transfer-Recovery-Backups instead of the system drive")
print("- recovery uses a launch-preflighted Codex CLI and avoids protected MSIX process paths")
print("- chain-health session/context faults point to the recovery center instead of restart loops")
print("- workspace files are never reverted by r46 recovery")
