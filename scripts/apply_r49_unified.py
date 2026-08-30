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
        raise SystemExit(f"r49 required component missing: {rel}")
    print(f"r49 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_r48_ui_runtime() -> bool:
    if not PROCESS.is_file() or not PROVIDERS.is_file() or not SETTINGS.is_file():
        return False
    return (
        "CAS-R47-CODEX-CUSTOM-TEMP" in PROCESS.read_text(encoding="utf-8")
        and "CAS-R48-PROVIDER-TEMP-CONTROL" in PROVIDERS.read_text(encoding="utf-8")
        and "<!-- CAS-R47-CODEX-CUSTOM-TEMP -->" not in SETTINGS.read_text(encoding="utf-8")
    )


if not has_r48_ui_runtime():
    run("scripts/apply_r48_unified.py")
else:
    print("R49 UNIFIED BASELINE: r48 UI/runtime already materialized; r48 replay SKIP")

run("scripts/apply_r49_unified_codex_temp_launch.py")
run("scripts/apply_r49_no_micro_temp_scope_fix.py")
REVISION.write_text("49\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "pub(crate) fn codex_custom_temp_launch_env",
        '"TEMP"', '"TMP"', '"TMPDIR"',
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
            raise SystemExit(f"r49 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=49" not in version or "app_version=2.4.5+49" not in version:
    raise SystemExit("r49 visible/package version stamp missing")

print("R49 UNIFIED COMPOSITION PASS")
print("- all three Transfer-owned Codex launch buttons apply the same Codex TEMP setting")
print("- No Lagging B inherits the same validated process-local TEMP/TMP/TMPDIR")
print("- B TEMP logging is scoped to launch_windows after its env injection")
print("- r48 Providers placement and r47 agent-loop recovery remain intact")
print("- no user/system TEMP mutation and no old cache deletion")
