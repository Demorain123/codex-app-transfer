from __future__ import annotations

import hashlib
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_ROOTS = [
    ROOT / "src-tauri" / "src",
    ROOT / "crates",
    ROOT / "frontend" / "src",
    ROOT / "resources",
]

FORBIDDEN_EXPERIMENT_MARKERS = (
    "CAS-R66-POST-COMPACT-HOOKS-AB",
    "CAS-R67-HOOKS-RESTORED-SELECTIVE-STATE",
    "CAS-R68-SESSIONSTART-ONLY-HOOKS-AB",
    "CAS-R69-SESSIONSTART-POSTCOMPACT-HOOKS-AB",
)

# r70 masked-history repair lives in the adapters Responses module, not proxy/src.
# Hash this exact modern runtime file before/after carry-forward so an old leaf
# cannot silently regress the r70 one-shot portable-history repair.
MASKED_HISTORY_FILE = ROOT / "crates" / "adapters" / "src" / "responses" / "tool_call_repair.rs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r82 required runtime file missing: {rel}")
    return path.read_text(encoding="utf-8")


def has(rel: str, marker: str) -> bool:
    return marker in text(rel)


def require(rel: str, *markers: str) -> None:
    content = text(rel)
    for marker in markers:
        if marker not in content:
            raise SystemExit(f"r82 invariant missing in {rel}: {marker}")


def run_leaf(stage: str, rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r82 stage={stage} required leaf missing: {rel}")
    print(f"r82 stage={stage} leaf={rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise SystemExit(f"r82 stage={stage} leaf={rel} failed with exit={exc.code}") from exc
    except Exception as exc:
        raise SystemExit(f"r82 stage={stage} leaf={rel} failed: {type(exc).__name__}: {exc}") from exc


def scan_forbidden() -> None:
    hits: list[str] = []
    for root in RUNTIME_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {
                ".rs", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".vue", ".json", ".toml", ".ps1", ".cmd", ".py"
            }:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for marker in FORBIDDEN_EXPERIMENT_MARKERS:
                if marker in content:
                    hits.append(f"{marker} -> {path.relative_to(ROOT).as_posix()}")
    if hits:
        raise SystemExit("r82 forbidden r66-r69 experimental runtime materialization detected:\n" + "\n".join(hits))


if not MASKED_HISTORY_FILE.is_file():
    raise SystemExit(f"r82 r70 preservation file missing: {MASKED_HISTORY_FILE.relative_to(ROOT).as_posix()}")
masked_history_before = sha256(MASKED_HISTORY_FILE)
print(f"r82 preserve=r70_masked_history file={MASKED_HISTORY_FILE.relative_to(ROOT).as_posix()} sha256_before={masked_history_before}")

# IMPORTANT: do not call historical recursive apply_rXX_unified.py drivers.
# They recurse into r24-r42 and contain stale source/UI anchors. r82+ applies only
# reviewed leaf transforms. One explicit exception is the proven r38/r39 proxy
# lifecycle leaf set: it is selectively re-materialized below because later r82+
# packaging accidentally dropped the fixed-port owner-thread/10048 hardening.

if not has("src-tauri/src/proxy_runner.rs", "CAS-R39-PROXY-OWNER-THREAD"):
    run_leaf("r39-lifecycle-prereq", "scripts/apply_r39_lifecycle_selective_modern.py")
else:
    print("r82 stage=r39-lifecycle-prereq status=already_materialized")

if not has("crates/adapters/src/mapper/grok_build.rs", "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD"):
    run_leaf("r42-prereq", "scripts/apply_r42_grok_tool_collision_guard.py")
else:
    print("r82 stage=r42-prereq status=already_materialized")

if not has("src-tauri/src/admin/handlers/chain_health.rs", "CAS-R43-REWRITE-HEALTH-MCP"):
    run_leaf("r43", "scripts/apply_r43_rewrite_health.py")
else:
    print("r82 stage=r43 status=already_materialized")

# r44 had no durable standalone materializer on this branch. Its terminal-SSE
# behavior is carried by the r45 model-switch leaf and is verified below via
# CAS-R45-RESPONSES-SEMANTIC-TERMINAL.
for rel in (
    "scripts/apply_r45_model_switch_continuity.py",
    "scripts/apply_r45_compaction_detector_safety.py",
    "scripts/apply_r45_compaction_metadata_truth.py",
):
    run_leaf("r45", rel)

for rel in (
    "scripts/apply_r46_thread_recovery_backend_fixes.py",
    "scripts/apply_r46_thread_recovery_backup_hardening.py",
    "scripts/apply_r46_recovery_backup_vdrive_hotfix.py",
    "scripts/apply_r46_codex_cli_launchability_hotfix.py",
    "scripts/apply_r46_codex_cli_shadow_copy_hotfix.py",
    "scripts/apply_r46_revert_compat_logging_hotfix.py",
    "scripts/apply_r46_resume_before_rollback_hotfix.py",
    "scripts/apply_r46_model_switch_forensics_v2.py",
    "scripts/apply_r46_thread_recovery_ui.py",
    "scripts/apply_r46_recovery_explainability_preflight.py",
    "scripts/apply_r46_recovery_explainability_ui.py",
    "scripts/apply_r46_failure_boundary_fork_hotfix.py",
    "scripts/apply_r46_chain_health_recovery_hint.py",
    "scripts/apply_r46_generic_repair_loop_guard.py",
    "scripts/apply_r94_stale_exit_guard_recovery.py",
):
    run_leaf("r46", rel)

for rel in (
    "scripts/apply_r47_codex_temp_dir.py",
    "scripts/apply_r47_temp_toggle_restart_fix.py",
    "scripts/apply_r47_agent_loop_recovery.py",
    "scripts/apply_r47_frontend_invalidate_once.py",
):
    run_leaf("r47", rel)

run_leaf("r48", "scripts/apply_r48_provider_temp_control.py")

for rel in (
    "scripts/apply_r49_unified_codex_temp_launch.py",
    "scripts/apply_r49_no_micro_temp_scope_fix.py",
):
    run_leaf("r49", rel)

run_leaf("r50", "scripts/apply_r50_same_session_cross_model_replay.py")

for rel in (
    "scripts/apply_r51_compaction_role_truth_hotfix.py",
    "scripts/apply_r51_compact_handoff_quality_hotfix.py",
):
    run_leaf("r51", rel)

for rel in (
    "scripts/apply_r52_sub2api_cross_model_compaction.py",
    "scripts/apply_r52_non_grok_compact_adapter_guard.py",
):
    run_leaf("r52", rel)

run_leaf("r53", "scripts/apply_r53_sub2api_compact_max_output_hotfix.py")
run_leaf("r54", "scripts/apply_r54_compact_responses_sse_reassembly.py")
run_leaf("r55", "scripts/apply_r55_detached_mcp_helper.py")
run_leaf("r56", "scripts/apply_r56_compact_sse_summary_fallback.py")

for rel in (
    "scripts/apply_r57_external_mcp_source_migration.py",
    "scripts/apply_r57_sqlite_dependency_repair.py",
):
    run_leaf("r57", rel)

run_leaf("r58", "scripts/apply_r58_windows_chatgpt_lifecycle_guard.py")
run_leaf("r59", "scripts/apply_r59_interrupted_tail_same_id_recovery.py")
run_leaf("r60", "scripts/apply_r60_sub2api_post_compaction_replay.py")
run_leaf("r61", "scripts/apply_r61_disable_remote_compaction_v2.py")
run_leaf("r62", "scripts/apply_r62_compact_summary_repair.py")

for rel in (
    "scripts/apply_r63_auth_epoch_encrypted_history_fence.py",
    "scripts/apply_r63_compile_hardening.py",
):
    run_leaf("r63", rel)

run_leaf("r64", "scripts/apply_r64_post_compact_continuation_guard.py")
run_leaf("r65", "scripts/apply_r65_startup_generation_gate.py")

require("crates/adapters/src/mapper/grok_build.rs", "CAS-R42-GROK-EFFECTIVE-TOOL-COLLISION-GUARD")
require(
    "src-tauri/src/admin/handlers/chain_health.rs",
    "CAS-R43-REWRITE-HEALTH-MCP",
    "CAS-R46-OLD-THREAD-RECOVERY-HINT",
    "CAS-R46-GENERIC-REPAIR-SAME-FAULT-GUARD",
    "CAS-R94-STALE-EXIT-GUARD-RECOVERY",
    "recover_stale_exit_guard_listener_r94",
    "fixed_port_released",
    "CAS-R47-AGENT-LOOP-RECOVERY",
)
require(
    "crates/proxy/src/forward.rs",
    "CAS-R45-MODEL-SWITCH-CONTINUITY",
    "CAS-R45-COMPACTION-DETECTOR-SAFETY",
    "CAS-R45-COMPACTION-METADATA-TRUTH",
    "CAS-R45-RESPONSES-SEMANTIC-TERMINAL",
    "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
    "CAS-R63-AUTH-EPOCH-ENCRYPTED-HISTORY-FENCE",
)
require(
    "src-tauri/src/admin/handlers/thread_recovery.rs",
    "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY",
    "CAS-R59-INTERRUPTED-TAIL-SAME-ID-RECOVERY",
)
require("src-tauri/src/admin/handlers/mod.rs", "pub mod thread_recovery;")
require(
    "src-tauri/src/admin/mod.rs",
    "/api/thread-recovery/preview",
    "/api/thread-recovery/action",
)
require(
    "frontend/src/pages/ProxyPage.vue",
    "CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI",
    "transfer_port_stale_owner",
    "适用：旧 Transfer 的 Exit Guard 残留占用固定端口",
    "不会换端口",
)
require(
    "frontend/src/api/threadRecovery.ts",
    "/api/thread-recovery/preview",
    "/api/thread-recovery/action",
)
require(
    "src-tauri/src/admin/services/desktop/process.rs",
    "CAS-R47-CODEX-CUSTOM-TEMP",
    "CAS-R58-WINDOWS-CHATGPT-LIFECYCLE-GUARD",
    "CAS-R61-LEGACY-COMPACTION-V1",
    "CAS-R64-POST-COMPACT-CONTINUATION-GUARD",
    "CAS-R65-FIRST-TURN-STARTUP-GENERATION-GATE",
)
require(
    "src-tauri/src/admin/services/mcp_servers.rs",
    "CAS-R55-DETACHED-MCP-HELPER",
    "CAS-R57-EXTERNAL-MCP-SOURCE-MIGRATION",
)
require(
    "crates/adapters/src/responses/compact.rs",
    "CAS-R51-COMPACT-HANDOFF-QUALITY",
    "CAS-R56-COMPACT-SSE-SUMMARY-FALLBACK",
    "CAS-R62-COMPACT-SUMMARY-SELF-REPAIR",
)
require("crates/adapters/src/mapper/sub2api_grok_compat.rs", "CAS-R60-SUB2API-POST-COMPACTION-REPLAY")
require("crates/adapters/src/mapper/responses.rs", "CAS-R60-SUB2API-POST-COMPACTION-REPLAY-HOOK")
require(
    "src-tauri/src/proxy_runner.rs",
    "CAS-R39-PROXY-OWNER-THREAD",
    "CAS-R39-OWNER-THREAD-STATE-GUARD",
    "CAS-R39-PROXY-OWNER-THREAD-TESTS",
    "port_release_verified",
    "listener_residue_detected",
)
require(
    "src-tauri/src/admin/handlers/proxy.rs",
    "CAS-R39-BIND-BUSY-NONRETRYABLE",
    "bind_busy_nonretryable",
)
require(
    "src-tauri/src/admin/handlers/chain_health.rs",
    "CAS-R38-RECOVERY-PORT-CLASSIFICATION",
    "CAS-R38-RECOVERY-ASYNC-STOP",
    "CAS-R39-BINDER-TERMINOLOGY",
    "transfer_port_occupied_live",
    "transfer_port_stale_owner",
)
require(
    "src-tauri/src/windows_tcp_owner.rs",
    "CAS-R38-WINDOWS-TCP-OWNER",
    "GetExtendedTcpTable",
    "TCP_TABLE_OWNER_PID_LISTENER",
)
_proxy_handler = text("src-tauri/src/admin/handlers/proxy.rs")
if "const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];" in _proxy_handler:
    raise SystemExit("r82 modern carry-forward regressed to r28 blind 10048 retry schedule")
if "[proxy-lifecycle-r28] bind busy requested_port=" in _proxy_handler:
    raise SystemExit("r82 modern carry-forward retained r28 bind-busy retry logging")
print("R82_R39_LIFECYCLE_SELECTIVE_CARRY_FORWARD_PASS")

scan_forbidden()
print("R82_R66_R69_EXPERIMENTS_ABSENT_PASS")

masked_history_after = sha256(MASKED_HISTORY_FILE)
if masked_history_after != masked_history_before:
    raise SystemExit(
        "r82 r70 masked-history regression: crates/adapters/src/responses/tool_call_repair.rs changed during r43-r65 carry-forward"
    )
print(f"r82 preserve=r70_masked_history file={MASKED_HISTORY_FILE.relative_to(ROOT).as_posix()} sha256_after={masked_history_after}")
print("R82_R70_MASKED_HISTORY_PRESERVED_PASS")
print("R82_R43_R65_SELECTIVE_MATERIALIZATION_PASS")
print("- no historical recursive apply_rXX_unified.py driver was executed")
print("- r38/r39 fixed-port lifecycle was restored only through reviewed leaf transforms; unrelated r24-r41 behavior was not replayed")
print("- r94 Try repair can recover the proven dead-binder -> exact r32 Exit Guard leak while preserving the configured fixed port")
print("- r42 leaf was used only as a required prerequisite when absent")
print("- r44 terminal semantics is represented by the verified r45 semantic-terminal invariant")
print("- r66-r69 Hook A/B experiment markers are absent from runtime sources")
