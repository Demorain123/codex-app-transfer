from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "frontend/src/components/provider/ProviderFormModal.vue"
COMPONENT = ROOT / "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue"
APPLY = ROOT / "scripts/apply_auto_review_ui_r29.py"

parent = PARENT.read_text(encoding="utf-8")
component = COMPONENT.read_text(encoding="utf-8") if COMPONENT.is_file() else ""
apply_script = APPLY.read_text(encoding="utf-8")

# 1) r29 is UI-only. Keep the exact r24 payload/storage contract so existing providers and
# copy-on-write catalog semantics do not fork just because the editor changed.
for marker in (
    "autoReviewModelOverrides: '', // CAS-AUTO-REVIEW-R24",
    "form.autoReviewModelOverrides = stringifyIfAny(p.autoReviewModelOverrides)",
    "autoReviewModelOverrides: (autoReviewModelOverrides || {}) as Record<string, string>",
):
    if marker not in parent:
        raise SystemExit(f"r29 review: r24 backward-compatible storage path missing: {marker}")

# 2) The raw JSON textarea must be gone from the normal Auto Review UI and the replacement must
# consume the same provider-owned availableModels list used by the normal model mapping controls.
for marker in (
    "CAS-AUTO-REVIEW-UI-R29-EDITOR",
    "<AutoReviewModelOverridesEditor",
    ':models="availableModels"',
    'v-model="form.autoReviewModelOverrides"',
    '@refresh="fetchModels()"',
):
    if marker not in parent:
        raise SystemExit(f"r29 review: visual editor wiring missing: {marker}")
if 'placeholder=\'{"grok-4.5":"gpt-5.6-luna"}\'' in parent:
    raise SystemExit("r29 review: raw Auto Review JSON textarea resurfaced")

# 3) Editing an existing provider must show cache/declared models first, then refresh only after
# its stored secret is loaded. The silent refresh may never turn opening the modal into an error.
cache_pos = parent.find("loadCachedModels(form.baseUrl)")
seed_pos = parent.find("seedModelsFromDeclared(", cache_pos)
secret_pos = parent.find("form.apiKey = secret.apiKey || ''")
auto_fetch_pos = parent.find("void fetchModels(true)")
if min(cache_pos, seed_pos, secret_pos, auto_fetch_pos) < 0:
    raise SystemExit("r29 review: existing-provider model hydration/refresh sequence is incomplete")
if not (cache_pos < seed_pos < secret_pos < auto_fetch_pos):
    raise SystemExit("r29 review: provider model refresh order regressed; secret must precede network refresh")
if parent.count("void fetchModels(true)") != 1:
    raise SystemExit("r29 review: existing-provider automatic model refresh must run exactly once")
for marker in (
    "async function fetchModels(silent = false)",
    "if (!silent) toast(tFmt('providerForm.modelsFetched'",
    "} else if (!silent) {",
):
    if marker not in parent:
        raise SystemExit(f"r29 review: silent model refresh invariant missing: {marker}")

# 4) The editor itself must stay pure UI: no provider API, network, credential, Tauri invoke or
# model-catalog storage access. All such behavior stays in ProviderForm/r24.
for forbidden in (
    "providersApi",
    "fetch(",
    "invoke(",
    "apiKey",
    "baseUrl",
    "model_catalog_json",
    "save_raw_config",
    "localStorage",
):
    if forbidden in component:
        raise SystemExit(f"r29 review: editor gained forbidden dependency: {forbidden}")
for required in (
    "props.models",
    "mergedOptions",
    "emit('update:modelValue'",
    "emit('refresh')",
    "JSON.stringify(out)",
):
    if required not in component:
        raise SystemExit(f"r29 review: editor data-flow invariant missing: {required}")

# 5) Preserve stale/existing slugs if /models is temporarily empty. Simply opening and saving an
# existing provider must not erase a still-valid external-catalog override.
for required in (
    "for (const row of rows.value)",
    "for (const value of [row.main, row.reviewer])",
    "if (trimmed && !seen.has(trimmed)) seen.set(trimmed, trimmed)",
):
    if required not in component:
        raise SystemExit(f"r29 review: existing override slug preservation missing: {required}")

# 6) Duplicate main-model keys would silently overwrite each other in the legacy object map.
# Require the UI to exclude main models already used by another row.
for required in (
    "usedByOthers",
    "candidate.id !== row.id",
    "!usedByOthers.has(option.value)",
):
    if required not in component:
        raise SystemExit(f"r29 review: duplicate-main prevention missing: {required}")

# 7) Incomplete rows may stay visible but may never serialize. This protects existing mappings while
# the user is halfway through adding a new row.
for required in (
    "if (main && reviewer) out[main] = reviewer",
    "rows.value.some((row) => !row.main.trim() || !row.reviewer.trim())",
):
    if required not in component:
        raise SystemExit(f"r29 review: incomplete-row safety missing: {required}")

# 8) Invalid legacy JSON must be surfaced, not silently normalized to empty and saved away.
for required in (
    "legacyInvalid.value = parsed === null",
    "if (parsed === null)",
    "providerForm.autoReviewUi.legacyInvalid",
):
    if required not in component:
        raise SystemExit(f"r29 review: invalid legacy-map preservation missing: {required}")

# 9) Explicit scope freeze requested after the provider-identity investigation: r29 must not change
# r27's built-in openai fallback/model_provider behavior. That remains a later independent option.
for text, label in ((component, "editor"), (apply_script, "overlay")):
    for forbidden in ("model_provider", "openai_base_url", "chatgpt_base_url", "model_providers.OpenAi"):
        if forbidden in text:
            raise SystemExit(f"r29 review: {label} unexpectedly touches provider identity/routing: {forbidden}")

# 10) r29 must not become a second model-catalog implementation. r24 remains authoritative.
for text, label in ((component, "editor"), (parent, "provider form")):
    for forbidden in ("model-catalog-overlays/auto-review", "save_raw_config", "model_catalog_json ="):
        if forbidden in text:
            raise SystemExit(f"r29 review: {label} unexpectedly touches catalog storage: {forbidden}")

print("r29 deep Auto Review provider-model-list UI review: PASS")
