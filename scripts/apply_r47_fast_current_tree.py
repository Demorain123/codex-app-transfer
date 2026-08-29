from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
RECOVERY = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
R46_BUILDER = ROOT / "scripts/build-r46-fast-real-use.ps1"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r47 fast-current-tree required component missing: {rel}")
    print(f"r47 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r46_generated_baseline() -> bool:
    if not FORWARD.is_file() or not RECOVERY.is_file() or not R46_BUILDER.is_file():
        return False
    forward = FORWARD.read_text(encoding="utf-8")
    recovery = RECOVERY.read_text(encoding="utf-8")
    builder = R46_BUILDER.read_text(encoding="utf-8")
    return (
        "CAS-R45-MODEL-SWITCH-CONTINUITY" in forward
        and "CAS-R45-COMPACTION-METADATA-TRUTH" in forward
        and "CAS-R46-MODEL-SWITCH-FORENSICS-V2" in forward
        and "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY" in recovery
        and "CAS-R46-FAILURE-BOUNDARY-FORK-HOTFIX" in recovery
        and "CAS-R46-FRONTEND-DIRECT-ENTRY-GUARD" in builder
    )


if has_complete_r46_generated_baseline():
    print("R47 FAST BASELINE: complete generated r46 tree detected; R46 COMPOSITION SKIP")
else:
    print("R47 FAST BASELINE: r46 generated markers incomplete; repairing r46 baseline once")
    run("scripts/apply_r46_fast_current_tree.py")
    if not has_complete_r46_generated_baseline():
        raise SystemExit("r47 fast baseline repair completed but required r46 markers are still missing")

run("scripts/apply_r47_codex_temp_dir.py")
run("scripts/apply_r47_temp_toggle_restart_fix.py")
run("scripts/apply_r47_agent_loop_recovery.py")
run("scripts/apply_r47_frontend_invalidate_once.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=47" not in version_before or "app_version=2.4.5+47" not in version_before:
    REVISION.write_text("47\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R47 version already stamped; revision materializer SKIP")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "codex_custom_temp_launch_env",
        "launch_codex_direct_with_env",
    ),
    "src-tauri/src/windows_msix.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "resolve_codex_gui_executable",
        "launch_codex_direct_with_env",
    ),
    "frontend/src/pages/SettingsPage.vue": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "CAS-R47-TEMP-TOGGLE-RESTART-FIX",
        "codexCustomTempEnabled",
        "codexCustomTempDir",
        "settings.codexCustomTempApplyRestart",
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        'recent_log_age_r37("agent_loop_died"',
        '"fault_codex_agent_loop"',
        'return "codex_agent_loop_failure"',
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        "codexAgentLoopDetected",
        "onRestartCodexForAgentLoop",
        "重启 Codex（agent loop）",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r47 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=47" not in version or "app_version=2.4.5+47" not in version:
    raise SystemExit("r47 fast-current-tree version stamp missing")

print("R47 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r46 baseline is reused without replay when present")
print("- r47 custom-temp launch overlay is applied")
print("- sanitized agent_loop_died is classified as a local Codex turn-start failure")
print("- agent-loop recovery exposes one targeted Codex-only restart; provider/Docker/gateway/history/workspace stay untouched")
print("- compatibility revision stamping runs only on the first r46→r47 transition")
print("- disabling custom temp still leaves Apply/Restart reachable")
print("- r47 UI changes invalidate stale frontend assets once")
print("- no user/system environment mutation")
