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
        raise SystemExit(f"r48 required component missing: {rel}")
    print(f"r48 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


def has_r47_runtime() -> bool:
    if not PROCESS.is_file() or not CHAIN.is_file() or not PROXY_PAGE.is_file():
        return False
    return (
        "CAS-R47-CODEX-CUSTOM-TEMP" in PROCESS.read_text(encoding="utf-8")
        and "CAS-R47-AGENT-LOOP-RECOVERY" in CHAIN.read_text(encoding="utf-8")
        and "CAS-R47-AGENT-LOOP-RECOVERY" in PROXY_PAGE.read_text(encoding="utf-8")
    )


provider_text = PROVIDERS_PAGE.read_text(encoding="utf-8") if PROVIDERS_PAGE.is_file() else ""
if not has_r47_runtime():
    if "CAS-R48-PROVIDER-TEMP-CONTROL" in provider_text:
        raise SystemExit("r48 UI is present but r47 runtime baseline is incomplete")
    run("scripts/apply_r47_unified.py")
else:
    print("R48 UNIFIED BASELINE: r47 runtime already materialized; r47 unified replay SKIP")

run("scripts/apply_r48_provider_temp_control.py")

REVISION.write_text("48\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/services/desktop/process.rs": (
        "CAS-R47-CODEX-CUSTOM-TEMP",
        "codex_custom_temp_launch_env",
        '"TEMP"',
        '"TMP"',
        '"TMPDIR"',
    ),
    "frontend/src/pages/ProvidersPage.vue": (
        "CAS-R48-PROVIDER-TEMP-CONTROL",
        "codexTempEnabled",
        "codexTempDir",
        "settingsStore.save",
        "providers__temp-control",
        "重启时应用",
    ),
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R47-AGENT-LOOP-RECOVERY",
        'recent_log_age_r37("agent_loop_died"',
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r48 generated-source invariant missing in {rel}: {marker}")

settings = (ROOT / "frontend/src/pages/SettingsPage.vue").read_text(encoding="utf-8")
if "<!-- CAS-R47-CODEX-CUSTOM-TEMP -->" in settings or "onApplyCodexCustomTemp" in settings:
    raise SystemExit("r48 generated-source invariant failed: SettingsPage still owns custom TEMP controls")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=48" not in version or "app_version=2.4.5+48" not in version:
    raise SystemExit("r48 visible/package version stamp missing")

print("R48 UNIFIED COMPOSITION PASS")
print("- r47 custom-temp process injection is preserved")
print("- custom TEMP UI is removed from general Settings")
print("- Providers toolbar exposes Codex TEMP enable/path beside Restart Codex App")
print("- Restart Codex App is the single apply point for the TEMP draft")
print("- no user/system environment mutation and no old temp cache deletion")
