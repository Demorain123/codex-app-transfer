from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
PROVIDERS = ROOT / "frontend/src/pages/ProvidersPage.vue"
SETTINGS = ROOT / "frontend/src/pages/SettingsPage.vue"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r49 fast-current-tree required component missing: {rel}")
    print(f"r49 fast-current-tree applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_complete_r48_generated_baseline() -> bool:
    if not PROCESS.is_file() or not PROVIDERS.is_file() or not SETTINGS.is_file():
        return False
    process = PROCESS.read_text(encoding="utf-8")
    providers = PROVIDERS.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    return (
        "CAS-R47-CODEX-CUSTOM-TEMP" in process
        and "codex_custom_temp_launch_env" in process
        and "CAS-R48-PROVIDER-TEMP-CONTROL" in providers
        and "codexTempEnabled" in providers
        and "codexTempDir" in providers
        and "<!-- CAS-R47-CODEX-CUSTOM-TEMP -->" not in settings
        and "onApplyCodexCustomTemp" not in settings
    )


if has_complete_r48_generated_baseline():
    print("R49 FAST BASELINE: complete generated r48 tree detected; R48 COMPOSITION SKIP")
else:
    print("R49 FAST BASELINE: r48 generated markers incomplete; repairing r48 baseline once")
    run("scripts/apply_r48_fast_current_tree.py")
    if not has_complete_r48_generated_baseline():
        raise SystemExit("r49 fast baseline repair completed but required r48 markers are still missing")

run("scripts/apply_r49_unified_codex_temp_launch.py")
run("scripts/apply_r49_no_micro_temp_scope_fix.py")

version_before = VERSION.read_text(encoding="utf-8") if VERSION.is_file() else ""
if "compat_revision=49" not in version_before or "app_version=2.4.5+49" not in version_before:
    REVISION.write_text("49\n", encoding="utf-8")
    run("scripts/apply_sub2api_grok_compat_revision.py")
else:
    print("R49 version already stamped; revision materializer SKIP")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "pub(crate) fn codex_custom_temp_launch_env",
    ),
    "src-tauri/src/admin/services/desktop/no_micro.rs": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX",
        'codex_custom_temp_launch_env("windows")',
        ".envs(custom_temp_env.iter()",
    ),
    "frontend/src/pages/ProvidersPage.vue": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "persistCodexTempDraft",
        ':before-launch="persistCodexTempDraft"',
        "任一启动均应用",
    ),
    "frontend/src/components/codex/NoMicroPanel.vue": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "beforeLaunch?: () => Promise<boolean>",
        "await props.beforeLaunch()",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r49 fast-current-tree invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=49" not in version or "app_version=2.4.5+49" not in version:
    raise SystemExit("r49 fast-current-tree version stamp missing")

print("R49 FAST CURRENT-TREE COMPOSITION PASS")
print("- complete generated r48 tree is reused without replay")
print("- Restart Codex App / Normal A / No Lagging B share one persisted TEMP draft")
print("- B launcher reuses the same r47 TEMP/TMP/TMPDIR validation helper")
print("- B TEMP logging is scoped only to the actual Node launch command")
print("- frontend assets invalidate once for unified launch behavior")
print("- no user/system environment mutation")
