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
run("scripts/apply_r38_proxy_port_switch.py")
run("scripts/review_r38_proxy_lifecycle_hardening.py")

# Slice B: native Windows owner attribution and safe recovery classification.
run("scripts/apply_r38_windows_port_owner.py")
run("scripts/apply_r38_recovery_port_classification.py")
run("scripts/apply_r38_recovery_async_stop.py")

# Slice C: Codex Desktop Usage injector compatibility + user-visible diagnostics.
run("scripts/apply_r38_codex_usage_injector_core.py")
run("scripts/apply_r38_codex_usage_status_ui.py")
run("scripts/review_r38_codex_usage_injector_compat.py")

# Slice D: lifecycle regression/stress tests materialized into proxy_runner.rs.
run("scripts/apply_r38_proxy_stress_tests.py")

required = {
    "src-tauri/src/proxy_runner.rs": [
        "CAS-R38-PROXY-LIFECYCLE-HARDENING",
        "with_graceful_shutdown",
        "port_release_verified",
        "duplicate_start_rejected",
        "bootstrap_cancelled_by_stop",
        "CAS-R38-PROXY-PORT-SWITCH",
        "port_switch_requested",
        "CAS-R38-WINDOWS-TCP-OWNER",
        "CAS-R38-PROXY-STRESS-TESTS",
    ],
    "src-tauri/src/windows_tcp_owner.rs": [
        "CAS-R38-WINDOWS-TCP-OWNER",
        "GetExtendedTcpTable",
        "TCP_TABLE_OWNER_PID_LISTENER",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R38-RECOVERY-PORT-CLASSIFICATION",
        "CAS-R38-RECOVERY-ASYNC-STOP",
        "transfer_port_occupied_live",
        "transfer_port_stale_owner",
        "stop_transfer_verified",
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
    "frontend/src/pages/ProxyPage.vue": ["chainHealth.recovering"],
    "frontend/src/i18n/zh.ts": [
        "Sub2API Grok Compat r38 · v2.4.5+38",
        "settings.codexQuotaStatusHealthy",
        "chainHealth.recovering",
    ],
    "frontend/src/i18n/en.ts": [
        "Sub2API Grok Compat r38 · v2.4.5+38",
        "settings.codexQuotaStatusHealthy",
        "chainHealth.recovering",
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

print("r38 unified composition: COMPLETE (r37 preserved + lifecycle/port switch + native owner/recovery + Usage compatibility + stress tests)")
