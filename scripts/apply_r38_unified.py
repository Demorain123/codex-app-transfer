from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 required overlay/composer missing: {rel}")
    print(f"r38 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r38 inherited successful no-op: {rel}")


# Preserve the complete r37 feature set first, then add independent r38 outer-layer slices.
run("scripts/apply_r37_unified.py")

REVISION.write_text("38\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r38_i18n_prep.py")

# Slice A: deterministic local proxy lifecycle / Windows 10048 hardening.
run("scripts/apply_r38_proxy_lifecycle_hardening.py")
run("scripts/review_r38_proxy_lifecycle_hardening.py")

# Slice B: Codex Desktop Usage injector compatibility + user-visible diagnostics.
run("scripts/apply_r38_codex_usage_injector_core.py")
run("scripts/apply_r38_codex_usage_status_ui.py")
run("scripts/review_r38_codex_usage_injector_compat.py")

required = {
    "src-tauri/src/proxy_runner.rs": [
        "CAS-R38-PROXY-LIFECYCLE-HARDENING",
        "with_graceful_shutdown",
        "port_release_verified",
        "duplicate_start_rejected",
        "bootstrap_cancelled_by_stop",
    ],
    "src-tauri/src/codex_quota_injector.rs": [
        "CAS-R38-CODEX-USAGE-INJECTOR-COMPAT",
        "semantic-section",
        "semantic-popup",
        "QuotaInjectorStatus",
        "__catQuotaDiagnostic",
    ],
    "src-tauri/src/admin/mod.rs": ["/api/diagnostic/codex-quota"],
    "frontend/src/pages/SettingsPage.vue": [
        "CAS-R38-CODEX-USAGE-STATUS-UI",
        "codexQuotaStatusDescription",
    ],
    "frontend/src/i18n/zh.ts": [
        "Sub2API Grok Compat r38 · v2.4.5+38",
        "settings.codexQuotaStatusHealthy",
    ],
    "frontend/src/i18n/en.ts": [
        "Sub2API Grok Compat r38 · v2.4.5+38",
        "settings.codexQuotaStatusHealthy",
    ],
}
for rel, markers in required.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r38 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=38" not in version or "app_version=2.4.5+38" not in version:
    raise SystemExit("r38 visible/package version stamp missing after composition")

print("r38 unified composition: COMPLETE (r37 preserved + proxy lifecycle + Codex Usage injector hardening)")
