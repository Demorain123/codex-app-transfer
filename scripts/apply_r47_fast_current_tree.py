from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


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


# Reuse the proven r46 warm/cold baseline policy, then layer only r47.
# Warm workspace: r24-r45 historical replay remains skipped.
run("scripts/apply_r46_fast_current_tree.py")
run("scripts/apply_r47_codex_temp_dir.py")

REVISION.write_text("47\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

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
        "codexCustomTempEnabled",
        "codexCustomTempDir",
        "settings.codexCustomTempApplyRestart",
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
print("- r46 generated baseline/cache path reused")
print("- only r47 Codex custom-temp overlay added")
print("- no user/system environment mutation")
