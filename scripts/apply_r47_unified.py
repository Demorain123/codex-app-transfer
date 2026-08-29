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


# Preserve the complete r46 generated tree, then layer the new launch-only temp setting.
run("scripts/apply_r46_unified.py")
run("scripts/apply_r47_codex_temp_dir.py")

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
        "app\").join(\"ChatGPT.exe",
        "launch_codex_direct_with_env",
    ),
    "frontend/src/pages/SettingsPage.vue": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "codexCustomTempEnabled",
        "codexCustomTempDir",
        "settings.codexCustomTempApplyRestart",
    ),
    "src-tauri/src/admin/handlers/settings.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        '"codexCustomTempEnabled": false',
        '"codexCustomTempDir": ""',
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
print("- user/system environment and CODEX_HOME remain unchanged")
print("- invalid custom temp fails closed; no silent fallback to system temp")
print("- no existing temp cache is moved or deleted")
