from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"
FORWARD = ROOT / "crates/proxy/src/forward.rs"
SUB2API = ROOT / "crates/adapters/src/mapper/sub2api_grok_compat.rs"
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
COMPACT = ROOT / "crates/adapters/src/responses/compact.rs"


def run(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r52 required component missing: {rel}")
    print(f"r52 applying {rel}")
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise


run("scripts/apply_r51_unified.py")
run("scripts/apply_r52_sub2api_cross_model_compaction.py")
run("scripts/apply_r52_non_grok_compact_adapter_guard.py")

REVISION.write_text("52\n", encoding="utf-8")
run("scripts/apply_sub2api_grok_compat_revision.py")

checks = {
    "crates/proxy/src/forward.rs": (
        "CAS-R50-SAME-SESSION-CROSS-MODEL-REPLAY",
        "CAS-R51-COMPACTION-ROLE-TRUTH",
    ),
    "crates/adapters/src/mapper/sub2api_grok_compat.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "sub2api_local_compaction_enabled",
        "r52_local_compaction_uses_provider_opt_in_not_model_family",
    ),
    "crates/adapters/src/mapper/responses.rs": (
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD",
        "use_sub2api_local_compaction",
        "[model-switch-r52] action=local_private_compaction",
        "let summ = if use_grok_compat",
    ),
    "crates/adapters/src/responses/compact.rs": (
        "CAS-R51-COMPACT-HANDOFF-QUALITY",
        "CAS-R52-SUB2API-CROSS-MODEL-COMPACTION",
        "localize_compaction_summary_prefix(summary)",
        "r52_compact_responses_history_lowers_prior_compaction_and_drops_reasoning",
    ),
    "src-tauri/src/admin/services/desktop/no_micro.rs": (
        "CAS-R49-UNIFIED-CODEX-TEMP-LAUNCH",
        "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX",
    ),
}
for rel, markers in checks.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r52 generated-source invariant missing in {rel}: {marker}")

version = VERSION.read_text(encoding="utf-8")
if "compat_revision=52" not in version or "app_version=2.4.5+52" not in version:
    raise SystemExit("r52 visible/package version stamp missing")

print("R52 UNIFIED COMPOSITION PASS")
print("- r51 keeps ordinary model-switch turns authoritative")
print("- r50 portable replay remains the main-turn cross-model boundary")
print("- explicit Sub2API compat providers now locally implement Codex private compaction for GPT/Luna/Terra as well as Grok")
print("- local compact history lowers prior compaction summaries to portable user messages and drops opaque reasoning")
print("- non-Grok Sub2API compact keeps native Responses semantics; Grok-only adapter is gated")
print("- direct native OpenAI Responses providers without Sub2API opt-in remain untouched")
print("- exact Codex session/thread identity remains unchanged")
