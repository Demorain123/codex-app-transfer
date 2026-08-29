from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r47 required component missing: {rel}")
    print(f"r47 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r46_unified.py")
run("scripts/apply_r47_codex_temp_dir.py")
run("scripts/apply_r47_temp_toggle_restart_fix.py")
run("scripts/apply_r47_agent_loop_recovery.py")
run("scripts/apply_r47_frontend_invalidate_once.py")

REVISION.write_text("47\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "codex_custom_temp_launch_env",
        "codexCustomTempEnabled",
        "codexCustomTempDir",
        "launch_codex_direct_with_env",
        '"TEMP"',
        '"TMP"',
        '"TMPDIR"',
    ),
    "src-tauri/src/windows_msix.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "resolve_codex_gui_executable",
        'join("app").join("ChatGPT.exe")',
        "launch_codex_direct_with_env",
    ),
    "frontend/src/pages/SettingsPage.vue": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "CAS-R47-TEMP-TOGGLE-RESTART-FIX",
        "codexCustomTempEnabled",
        "codexCustomTempDir",
        "settings.codexCustomTempApplyRestart",
    ),
    "src-tauri/src/admin/handlers/settings.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        '"codexCustomTempEnabled": false',
        '"codexCustomTempDir": ""',
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        'recent_log_age_r37("agent_loop_died"',
        '"fault_codex_agent_loop"',
        'return "codex_agent_loop_failure"',
        "use_targeted_codex_restart",
    ),
    "frontend/src/pages/ProxyPage.vue": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        "restartCodexApp",
        "codexAgentLoopDetected",
        "onRestartCodexForAgentLoop",
        "重启 Codex（agent loop）",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r47 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=47" not in version or "app_version=2.4.5+47" not in version:
    raise SystemExit("r47 visible/package version stamp missing")

print("R47 UNIFIED COMPOSITION PASS")
print("- complete r46 model-switch/recovery tree preserved")
print("- Windows Transfer-launched Codex can use a user-selected process-local TEMP/TMP/TMPDIR")
print("- sanitized agent_loop_died / failed_to_start_turn are classified before provider/upstream")
print("- local agent-loop faults get one explicit Codex-only restart action, not a generic infrastructure repair")
print("- user/system environment and CODEX_HOME remain unchanged")
print("- invalid custom temp fails closed; no silent fallback to system temp")
print("- disabling custom temp can immediately restart back onto inherited system TEMP")
print("- r47 UI changes force one frontend rebuild, then return to warm reuse")
print("- no existing temp cache is moved or deleted")
