from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parent = (ROOT / "frontend/src/components/provider/ProviderFormModal.vue").read_text(encoding="utf-8")
editor = (ROOT / "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue").read_text(encoding="utf-8")
settings_row = (ROOT / "frontend/src/components/ui/SettingsRow.vue").read_text(encoding="utf-8")
overlay = (ROOT / "scripts/apply_auto_review_layout_r31.py").read_text(encoding="utf-8")

# The fix must stay local to the Auto Review row. Do not globally weaken SettingsRow,
# because many compact provider controls rely on the existing non-shrinking slot behavior.
for required in (
    ".settings-row__control {",
    "flex-shrink: 0;",
):
    if required not in settings_row:
        raise SystemExit(f"r31 review: generic SettingsRow invariant changed unexpectedly: {required}")

for required in (
    '<SettingsRow class="pf__auto-review-row" :title="t(\'providerForm.autoReviewModelOverrides\')">',
    "CAS-AUTO-REVIEW-LAYOUT-R31",
    "flex-direction: column;",
    ".pf__auto-review-row :deep(.settings-row__control)",
    "width: 100%;",
    "min-width: 0;",
    "flex: 1 1 auto;",
):
    if required not in parent:
        raise SystemExit(f"r31 review: provider-row overflow fix missing: {required}")

for required in (
    "box-sizing: border-box; /* CAS-AUTO-REVIEW-LAYOUT-R31 */",
    "grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr) auto;",
):
    if required not in editor:
        raise SystemExit(f"r31 review: editor responsive invariant missing: {required}")

if "grid-template-columns: minmax(150px, 1fr) 24px minmax(150px, 1fr) auto;" in editor:
    raise SystemExit("r31 review: old fixed 150px Auto Review grid minimum resurfaced")

# This is deliberately a UI-only hotfix. It must not mutate routing, auth, catalog
# semantics, provider identity, or the r30 Hybrid Direct bridge.
for forbidden in (
    "model_provider",
    "openai_base_url",
    "chatgpt_base_url",
    "auth.json",
    "apply_provider",
    "sync_desktop_for_active_provider",
    "auto_review_model_override\"",
):
    if forbidden in overlay:
        raise SystemExit(f"r31 review: layout overlay leaked into non-UI behavior: {forbidden}")

print("r31 Auto Review layout/overflow deep review: PASS")
