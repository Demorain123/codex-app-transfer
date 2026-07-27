from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r27 required overlay missing: {rel}")
    print(f"r27 applying {rel}")
    runpy.run_path(str(path), run_name="__main__")


# r27 is deliberately a composition layer, not a new fork of the feature code:
# r24 Auto Review COW -> r25 Apps MCP auth -> r26 runtime diagnostics -> r27 proxy
# lifecycle fix. Stamp the target revision before the existing r24/r25 composer so
# all native/UI/package identities are generated as v2.4.5+27 in one pass.
REVISION.write_text("27\n", encoding="utf-8")

# r25 discovered one r24 generator replay defect after rustfmt. Install the source-level
# fix before invoking the existing r24+r25 composer so complete replay is idempotent.
run("scripts/apply_apps_mcp_auth_r25_r24_replay_fix.py")
run("scripts/apply_sub2api_grok_compat_revision.py")

# Layer r26 diagnostics on the already-materialized r24+r25 tree. These are diagnostic
# only and intentionally do not replace the r25 auth path.
run("scripts/apply_runtime_diag_r26.py")
run("scripts/apply_runtime_diag_r26_review.py")

# Fix the independently reproduced Windows proxy stop->same-port-rebind race.
run("scripts/apply_proxy_lifecycle_r27.py")

checks = {
    "crates/codex_integration/src/auto_review_overlay.rs": ["CAS-AUTO-REVIEW-R24"],
    "crates/codex_integration/src/lib.rs": ["pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"],
    "crates/proxy/src/forward.rs": [
        "CAS-APPS-MCP-AUTH-R25-REHYDRATE",
        "CAS-APPS-MCP-AUTH-R25-ERROR-URL-PRIVACY",
        "CAS-SUBAGENT-FAILURE-CHAIN-R26-HOOK",
        "CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT",
    ],
    "src-tauri/src/runtime_diag.rs": [
        "CAS-RUNTIME-DIAG-R26",
        "stream_disconnected",
        "chatgpt.exe",
    ],
    "src-tauri/src/admin/handlers/proxy.rs": [
        "CAS-PROXY-LIFECYCLE-R27",
        "PROXY_LIFECYCLE_R27.lock().await",
        "current_port == Some(port)",
        "CAS-PROXY-LIFECYCLE-R27-START-HANDLER",
    ],
}
for rel, markers in checks.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r27 materialization missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r27 materialization missing marker in {rel}: {marker}")

lib_text = (ROOT / "crates/codex_integration/src/lib.rs").read_text(encoding="utf-8")
module_line = "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24"
if lib_text.count(module_line) != 1:
    raise SystemExit(
        f"r27 requires exactly one r24 module registration, found {lib_text.count(module_line)}"
    )

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=27" not in version or "app_version=" not in version:
    raise SystemExit("r27 version stamp missing after composition")

print("r27 unified materialization gate: PASS (r24 + r25 + r26 + proxy lifecycle)")
