from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "frontend/src/components/provider/ProviderFormModal.vue"
COMPONENT = ROOT / "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue"

parent = PARENT.read_text(encoding="utf-8")
component = COMPONENT.read_text(encoding="utf-8") if COMPONENT.is_file() else ""

# r28 is UI-only: retain the exact r24 payload field/storage path so no backend/catalog
# semantics are forked just to improve the editor.
for marker in (
    "autoReviewModelOverrides: '', // CAS-AUTO-REVIEW-R24",
    "form.autoReviewModelOverrides = stringifyIfAny(p.autoReviewModelOverrides)",
    "autoReviewModelOverrides: (autoReviewModelOverrides || {}) as Record<string, string>",
):
    if marker not in parent:
        raise SystemExit(f"r28 review: r24 backward-compatible storage path changed/missing: {marker}")

# The raw JSON textarea must be gone from the normal UI, replaced by the list editor fed
# from the exact same availableModels collection as the provider's model mapping controls.
for marker in (
    "CAS-AUTO-REVIEW-UI-R28-EDITOR",
    '<AutoReviewModelOverridesEditor',
    ':models="availableModels"',
    'v-model="form.autoReviewModelOverrides"',
    '@refresh="fetchModels()"',
):
    if marker not in parent:
        raise SystemExit(f"r28 review: visual editor wiring missing: {marker}")
if 'placeholder=\'{"grok-4.5":"gpt-5.6-luna"}\'' in parent:
    raise SystemExit("r28 review: raw JSON Auto Review textarea resurfaced")

# Existing-provider refresh must happen only after the stored secret is loaded, and must be
# silent/fallback-safe so a provider without /models does not turn opening Edit into an error.
secret_pos = parent.find("form.apiKey = secret.apiKey || ''")
auto_fetch_pos = parent.find("void fetchModels(true)")
if secret_pos < 0 or auto_fetch_pos <= secret_pos:
    raise SystemExit("r28 review: automatic model refresh runs before provider secret is available")
for marker in (
    "async function fetchModels(silent = false)",
    "if (!silent) toast(tFmt('providerForm.modelsFetched'",
    "} else if (!silent) {",
):
    if marker not in parent:
        raise SystemExit(f"r28 review: silent model refresh invariant missing: {marker}")

# Editor must not fetch credentials/network itself. It only consumes the parent's provider model
# list and emits the original JSON string contract. This keeps credential handling in the existing
# ProviderForm code path and avoids a second model-list implementation.
for forbidden in ("providersApi", "fetch(", "invoke(", "apiKey", "baseUrl"):
    if forbidden in component:
        raise SystemExit(f"r28 review: editor gained a forbidden network/credential dependency: {forbidden}")
for required in (
    "props.models",
    "mergedOptions",
    "emit('update:modelValue'",
    "emit('refresh')",
    "JSON.stringify(out)",
):
    if required not in component:
        raise SystemExit(f"r28 review: editor data-flow invariant missing: {required}")

# Preserve stale/existing slugs if /models is temporarily unavailable; otherwise simply opening
# and saving a provider could erase a still-valid external-catalog override.
if "for (const row of rows.value)" not in component or "for (const value of [row.main, row.reviewer])" not in component:
    raise SystemExit("r28 review: existing override slugs are not merged back into dropdown options")

# Main-model keys are an object-map key, so duplicate rows would silently overwrite each other.
# Require the UI to remove already-used main models from every other row's choices.
for required in (
    "usedByOthers",
    "candidate.id !== row.id",
    "!usedByOthers.has(option.value)",
):
    if required not in component:
        raise SystemExit(f"r28 review: duplicate-main prevention missing: {required}")

# Incomplete rows must never serialize malformed/empty mappings. They can remain visible while the
# user is choosing, but the emitted legacy JSON contains complete main/reviewer pairs only.
for required in (
    "if (main && reviewer) out[main] = reviewer",
    "rows.value.some((row) => !row.main || !row.reviewer)",
):
    if required not in component:
        raise SystemExit(f"r28 review: incomplete-row safety missing: {required}")

# No r28 code may write model_catalog_json. r24 copy-on-write remains the sole catalog mutation
# layer; this UI only edits provider metadata.
for text, label in ((component, "editor"), (parent, "provider form")):
    for forbidden in ("model-catalog-overlays/auto-review", "save_raw_config", "model_catalog_json ="):
        if forbidden in text:
            raise SystemExit(f"r28 review: {label} unexpectedly touches catalog storage: {forbidden}")

print("r28 deep Auto Review UI review: PASS")
