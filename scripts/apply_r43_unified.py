from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r43 rewrite required component missing: {rel}")
    print(f"r43 rewrite applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


# r42 is the last real-environment-verified base. Its composition remains unchanged.
run("scripts/apply_r42_unified.py")

# CAS-R43-REPLAY-PREFLIGHT-LATEST-LINEAGE: r42 replay output can differ in harmless
# formatting around the failure-selection block. Normalize only that superseded block
# before applying r43's latest-lineage rewrite; the preflight refuses newer semantics.
run("scripts/apply_r43_rewrite_health_replay_preflight.py")

# r43 has one behavioral post-r42 source transform only: health attribution/MCP policy.
# Runtime transition classifiers come from the r26 template source, and MCP post-stop
# verification comes from the r32 exit-guard source, so there is no runtime repair pass.
run("scripts/apply_r43_rewrite_health.py")

REVISION.write_text("43\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "src-tauri/src/admin/handlers/chain_health.rs": (
        "CAS-R43-REPLAY-PREFLIGHT-LATEST-LINEAGE",
        "CAS-R43-REWRITE-HEALTH-MCP",
        "CAS-R43-REWRITE-LATEST-LINEAGE-WINS",
        "CAS-R43-REWRITE-SHARED-FAILURE-QUORUM",
        "fault_compaction_transition",
        "verified_generation_helpers",
    ),
    "src-tauri/src/runtime_diag.rs": (
        "context_auto_compacting",
        "model_switch_selected",
        "compact_v2_upstream_failed",
        "stream_disconnected",
    ),
    "src-tauri/resources/codex_no_lagging_janitor.ps1": (
        "CAS-R43-REWRITE-POST-CLEANUP-VERIFICATION",
        "cleanup_verified",
        "survivors=$remaining.Count",
        "Stop-Process -Id $r.Pid",
    ),
    "crates/adapters/src/mapper/grok_build.rs": (
        "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD",
        "grok_effective_tool_name",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r43 rewrite generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=43" not in version or "app_version=2.4.5+43" not in version:
    raise SystemExit("r43 rewrite visible/package version stamp missing")

print("R43 REWRITE COMPOSITION PASS")
print("- r42 verified base preserved")
print("- replay-only semantic-boundary preflight canonicalizes the superseded lineage block")
print("- one behavioral health/MCP post-r42 transform")
print("- model-switch/compact classifiers originate in runtime template source")
print("- Exit Guard post-cleanup verification originates in janitor source")
