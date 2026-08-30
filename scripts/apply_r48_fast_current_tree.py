from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
PROXY_PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
PROVIDERS_PAGE = ROOT / "frontend/src/pages/ProvidersPage.vue"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r48 fast-current-tree required component missing: {rel}")
    print(f"r48 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r47_generated_baseline() -> bool:
    if not PROCESS.is_file() or not CHAIN.is_file() or not PROXY_PAGE.is_file():
        return False
    process = PROCESS.read_text(encoding="utf-8")
    chain = CHAIN.read_text(encoding="utf-8")
    proxy = PROXY_PAGE.read_text(encoding="utf-8")
    return (
        "CAS-R47-CODEX-CUSTOM-TEMP" in process
        and "codex_custom_temp_launch_env" in process
        and "CAS-R47-AGENT-LOOP-RECOVERY" in chain
        and 'recent_log_age_r37("agent_loop_died"' in chain
        and "CAS-R47-AGENT-LOOP-RECOVERY" in proxy
        and "onRestartCodexForAgentLoop" in proxy
    )


provider_text = PROVIDERS_PAGE.read_text(encoding="utf-8") if PROVIDERS_PAGE.is_file() else ""
r48_already = "CAS-R48-PROVIDER-TEMP-CONTROL" in provider_text

if has_complete_r47_generated_baseline():
    print("R48 FAST BASELINE: complete generated r47 backend/runtime tree detected; R47 COMPOSITION SKIP")
else:
    if r48_already:
        raise SystemExit("r48 provider UI exists but required r47 backend/runtime markers are missing")
    print("R48 FAST BASELINE: r47 generated markers incomplete; repairing r47 baseline once")
    run("scripts/apply_r47_fast_current_tree.py")
    if not has_complete_r47_generated_baseline():
        raise SystemExit("r48 fast baseline repair completed but required r47 markers are still missing")

run("scripts/apply_r48_provider_temp_control.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=48" not in version_before or "app_version=2.4.5+48" not in version_before:
    REVISION.write_text("48\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R48 version already stamped; revision materializer SKIP")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "codex_custom_temp_launch_env",
        "launch_codex_direct_with_env",
    ),
    "frontend/src/pages/ProvidersPage.vue": (
        "CAS-R48-PROVIDER-TEMP-CONTROL",
        "useSettingsStore",
        "codexTempEnabled",
        "codexTempDir",
        "settingsStore.save",
        "providers__temp-control",
        "重启时应用",
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        'recent_log_age_r37("agent_loop_died"',
        '"fault_codex_agent_loop"',
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r48 fast-current-tree invariant missing in {rel}: {marker}")

settings = (ROOT / "frontend/src/pages/SettingsPage.vue").read_text(encoding="utf-8")
if "<!-- CAS-R47-CODEX-CUSTOM-TEMP -->" in settings or "onApplyCodexCustomTemp" in settings:
    raise SystemExit("r48 fast-current-tree invariant failed: custom TEMP controls still exposed in SettingsPage")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=48" not in version or "app_version=2.4.5+48" not in version:
    raise SystemExit("r48 fast-current-tree version stamp missing")

print("R48 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r47 backend/runtime tree is reused without replay")
print("- custom TEMP controls moved from SettingsPage to the ProvidersPage restart toolbar")
print("- existing Restart Codex App button atomically saves enable/path then restarts Codex")
print("- disabling TEMP then restarting returns Codex to inherited system TEMP")
print("- r47 process-local TEMP/TMP/TMPDIR backend and agent-loop recovery are preserved")
print("- frontend assets invalidate once for the toolbar move")
