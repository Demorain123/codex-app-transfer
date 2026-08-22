from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
RUNTIME = ROOT / "src-tauri/src/runtime_diag.rs"
EXIT_GUARD = ROOT / "scripts/no_lagging_r32_mcp_exit_guard.ps1"
GROK = ROOT / "crates/adapters/src/mapper/grok_build.rs"

checks: list[tuple[Path, str]] = [
    (CHAIN, "CAS-R43-HEALTH-MCP-HARDENING"),
    (CHAIN, "CAS-R43-LATEST-LINEAGE-WINS"),
    (CHAIN, "CAS-R43-SHARED-FAILURE-QUORUM"),
    (CHAIN, "fault_compaction_transition"),
    (CHAIN, "new_model_request_seen=unproven"),
    (CHAIN, "verified_generation_helpers"),
    (CHAIN, "orphan_candidates"),
    (CHAIN, "external_candidates"),
    (CHAIN, "r43_lifecycle_failure_predicate_clears_on_success"),
    (CHAIN, "r43_compaction_transition_requires_fresh_5xx_and_signal"),
    (RUNTIME, "CAS-R43-MODEL-SWITCH-COMPACTION-DIAG"),
    (RUNTIME, "CAS-R43-RUNTIME-CLASSIFIER-CANONICAL"),
    (RUNTIME, "context_auto_compacting"),
    (RUNTIME, "model_switch_selected"),
    (RUNTIME, "compact_v2_upstream_failed"),
    (EXIT_GUARD, "CAS-R43-POST-CLEANUP-VERIFICATION"),
    (EXIT_GUARD, "cleanup_verified"),
    (GROK, "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD"),
]

for path, marker in checks:
    if not path.is_file():
        raise SystemExit(f"r43 review missing file: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"r43 review missing marker {marker!r} in {path.relative_to(ROOT)}")

chain = CHAIN.read_text(encoding="utf-8")
if "let failed_correlations: HashSet<&str> = records" in chain:
    raise SystemExit("r43 review: stale r37 whole-window failed_correlations logic survived")
if "window_s={R43_SHARED_FAILURE_WINDOW_SECS}" not in chain:
    raise SystemExit("r43 review: shared-upstream short-window evidence missing")


def powershell_executable_projection(text: str) -> str:
    """Project PowerShell to executable-looking text for forbidden-command review.

    r43 deliberately documents forbidden broad cleanup forms in comments. Reviewing
    the raw file therefore self-triggers on its own safety documentation. PowerShell
    ignores # line comments and <# ... #> block comments at runtime, so remove block
    comments and comment-only lines before looking for dangerous executable forms.

    End-of-line comments are intentionally retained: any executable command before
    the # must still be reviewed. This is a conservative projection, not a parser.
    """

    without_blocks = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines() if not line.lstrip().startswith("#")
    ).lower()


# Regression proof for the review itself: documentation must not trip the gate,
# while an executable broad process-name stop must still be caught.
_comment_probe = "# Stop-Process -Name node\n<# taskkill /IM node.exe #>\nWrite-Host ok\n"
if "stop-process -name" in powershell_executable_projection(_comment_probe):
    raise SystemExit("r43 review self-test: line comments were not excluded")
if "taskkill /im" in powershell_executable_projection(_comment_probe):
    raise SystemExit("r43 review self-test: block comments were not excluded")
if "stop-process -name" not in powershell_executable_projection("Stop-Process -Name node\n"):
    raise SystemExit("r43 review self-test: executable forbidden command was hidden")

exit_guard_raw = EXIT_GUARD.read_text(encoding="utf-8")
exit_guard = exit_guard_raw.lower()
exit_guard_code = powershell_executable_projection(exit_guard_raw)
for forbidden in (
    "stop-process -name",
    "taskkill /im",
    "get-process -name 'node' | stop-process",
    'get-process -name "node" | stop-process',
):
    if forbidden in exit_guard_code:
        raise SystemExit(f"r43 review: broad process-name cleanup is forbidden: {forbidden}")
if "same-identity $r" not in exit_guard:
    raise SystemExit("r43 review: exact PID/start/path identity guard missing")
if "$remaining = @($targets | where-object { same-identity $_ })" not in exit_guard:
    raise SystemExit("r43 review: post-cleanup exact-identity verification missing")

print("R43 HEALTH + MCP HARDENING REVIEW PASS")
print("- latest provider/model/lineage state wins; recovered failures stop voting")
print("- shared-upstream requires >=2 currently-failed lineages in a 120s window")
print("- model-switch/compact 5xx is diagnosed before blaming the selected new model")
print("- runtime classifier is canonically rebuilt after semantic verification")
print("- MCP status counts verified Codex descendants separately from orphan/external candidates")
print("- Exit Guard remains exact-PID/identity-only and verifies post-cleanup survivors")
print("- broad-cleanup review ignores PowerShell comments but still rejects executable name-wide kills")
print("- r42 Grok effective tool collision guard preserved")
