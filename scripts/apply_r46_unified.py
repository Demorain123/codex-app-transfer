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


# Preserve r45's model continuity + Responses semantic terminal work, then add
# r46's structural forensics and explicit old-thread recovery center.
run("scripts/apply_r45_unified.py")
run("scripts/apply_r46_thread_recovery_backend_fixes.py")
run("scripts/apply_r46_model_switch_forensics.py")
run("scripts/apply_r46_thread_recovery_ui.py")

REVISION.write_text("46\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R45-MODEL-SWITCH-CONTINUITY",
        "CAS-R45-RESPONSES-SEMANTIC-TERMINAL",
        "CAS-R46-MODEL-SWITCH-FORENSICS",
        "event=raw_client_status_mismatch",
        "cross_model_compaction_mismatch",
        "r46_request_kind_header_outranks_beta_feature_noise",
    ),
    "src-tauri/src/admin/handlers/thread_recovery.rs": (
        "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY",
        "thread/revert",
        "thread/rollback",
        "thread/fork",
        "RECOVERY-BACKUP.json",
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
        "同 ID 回退 1 轮（推荐）",
        "创建恢复副本（原会话不动）",
    ),
    "frontend/src/api/threadRecovery.ts": (
        "/api/thread-recovery/preview",
        "/api/thread-recovery/action",
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
print("- r45 model-switch continuity + semantic terminal base preserved")
print("- authoritative x-codex-turn-metadata request_kind classification added")
print("- privacy-bounded structural model-switch forensics added")
print("- read-only old-thread recovery preview added")
print("- same-thread one-turn rewind prefers thread/revert, method-not-found falls back to rollback(1)")
print("- fork recovery remains non-destructive fallback")
print("- rollout backup + SHA256 happens before every recovery mutation")
print("- workspace files are never reverted by r46 recovery")
