from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r35 required overlay/composer missing: {rel}")
    print(f"r35 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
        print(f"r35 inherited successful no-op: {rel}")


run("scripts/apply_r34_unified.py")
run("scripts/review_r34_runtime_behavior_health.py")

REVISION.write_text("35\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")
run("scripts/apply_r35_log_privacy_prep.py")
run("scripts/apply_r35_real_upstream_health.py")
run("scripts/review_r35_real_upstream_health.py")

required = {
    "crates/proxy/src/telemetry.rs": [
        "CAS-R35-REAL-UPSTREAM-HEALTH",
        "raw_upstream_status",
        "client_status",
        "request_bytes",
    ],
    "crates/proxy/src/forward.rs": [
        "CAS-R35-REAL-UPSTREAM-HEALTH",
        "client response status",
        "request body: <redacted>",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "CAS-R35-REAL-UPSTREAM-HEALTH",
        "structured-request-lifecycle",
        "failure_streak",
        "retry_upload_bytes",
        "upstream_service_unavailable",
    ],
    "frontend/src/i18n/zh.ts": ["CAS-R35-REAL-UPSTREAM-HEALTH", "账号池 / 上游（被动）"],
    "frontend/src/i18n/en.ts": ["CAS-R35-REAL-UPSTREAM-HEALTH", "Account pool / Upstream (passive)"],
}
for rel, markers in required.items():
    body = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in body:
            raise SystemExit(f"r35 materialization missing marker in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=35" not in version or "app_version=2.4.5+35" not in version:
    raise SystemExit("r35 visible/package version stamp missing after composition")

print("r35 unified composition: COMPLETE (r34 preserved + real upstream health)")
