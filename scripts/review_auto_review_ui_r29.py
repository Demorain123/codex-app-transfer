from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "frontend/src/components/provider/ProviderFormModal.vue"
COMPONENT = ROOT / "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue"
APPLY = ROOT / "scripts/apply_auto_review_ui_r29.py"
EFFECTIVE = ROOT / "scripts/apply_auto_review_effective_r29.py"
PROVIDERS_API = ROOT / "frontend/src/api/providers.ts"
CRUD = ROOT / "src-tauri/src/admin/handlers/providers/crud.rs"

parent = PARENT.read_text(encoding="utf-8")
component = COMPONENT.read_text(encoding="utf-8") if COMPONENT.is_file() else ""
apply_script = APPLY.read_text(encoding="utf-8")
effective_script = EFFECTIVE.read_text(encoding="utf-8")
providers_api = PROVIDERS_API.read_text(encoding="utf-8")
crud = CRUD.read_text(encoding="utf-8")

# 1) Keep the exact r24 payload/storage/catalog contract. r29 improves the editor and closes missing
# transport/apply wiring, but r24 remains the sole copy-on-write catalog implementation.
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

# 3) Scope the ordering check to the actual existing-provider onMounted branch. There are also
# cache/seed calls in applyPreset; using the first global occurrence would make this gate a false
# positive even if the edit flow regressed.
edit_anchor = parent.find("  if (!props.editId) return")
edit_end = parent.find("})\n\nfunction parseJsonObj", edit_anchor)
if edit_anchor < 0 or edit_end <= edit_anchor:
    raise SystemExit("r29 review: could not isolate existing-provider onMounted branch")
edit_flow = parent[edit_anchor:edit_end]
cache_pos = edit_flow.find("loadCachedModels(form.baseUrl)")
seed_pos = edit_flow.find("seedModelsFromDeclared(")
secret_pos = edit_flow.find("form.apiKey = secret.apiKey || ''")
auto_fetch_pos = edit_flow.find("void fetchModels(true)")
if min(cache_pos, seed_pos, secret_pos, auto_fetch_pos) < 0:
    raise SystemExit("r29 review: existing-provider model hydration/refresh sequence is incomplete")
if not (cache_pos < seed_pos < secret_pos < auto_fetch_pos):
    raise SystemExit("r29 review: edit flow must show cache/declared models, load secret, then refresh")
if parent.count("void fetchModels(true)") != 1:
    raise SystemExit("r29 review: existing-provider automatic model refresh must run exactly once")
for marker in (
    "async function fetchModels(silent = false)",
    "if (!silent) toast(tFmt('providerForm.modelsFetched'",
    "} else if (!silent) {",
    "CAS-AUTO-REVIEW-UI-R29-SILENT-NO-SUGGEST",
):
    if marker not in parent:
        raise SystemExit(f"r29 review: silent model refresh invariant missing: {marker}")

# Automatic edit-time refresh is observational: it may update availableModels/cache/filter status,
# but must not populate `suggested` model slots. Suggested-slot mutation is manual fetch only.
suggest_guard = parent.find("if (!silent) { // CAS-AUTO-REVIEW-UI-R29-SILENT-NO-SUGGEST")
suggested = parent.find("const suggested = res.suggested || {}")
if suggest_guard < 0 or suggested <= suggest_guard:
    raise SystemExit("r29 review: suggested model auto-fill is not guarded by !silent")

# 4) The editor itself must stay pure UI: no provider API, network, credential, Tauri invoke or
# model-catalog storage access. All such behavior stays in ProviderForm/r24/effective companion.
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
for required in (
    "usedByOthers",
    "candidate.id !== row.id",
    "!usedByOthers.has(option.value)",
):
    if required not in component:
        raise SystemExit(f"r29 review: duplicate-main prevention missing: {required}")

# 7) Incomplete rows may stay visible but may never serialize.
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

# 9) P0 transport regression: r24's form/type field is useless unless list->mapProvider loads it and
# providerBody sends it. An explicit empty object must be transmitted so removing a mapping restores
# Codex's default reviewer instead of leaving a stale override in the registry.
for required in (
    "CAS-AUTO-REVIEW-R29-API-WIRE-READ",
    "autoReviewModelOverrides: provider.autoReviewModelOverrides || {}",
    "CAS-AUTO-REVIEW-R29-API-WIRE-WRITE",
    "if (payload.autoReviewModelOverrides !== undefined)",
    "body.autoReviewModelOverrides = payload.autoReviewModelOverrides",
):
    if required not in providers_api:
        raise SystemExit(f"r29 review: Auto Review provider API transport missing: {required}")
if providers_api.count("body.autoReviewModelOverrides = payload.autoReviewModelOverrides") != 1:
    raise SystemExit("r29 review: Auto Review write transport must exist exactly once")

# 10) Active-provider apply semantics: registry persistence happens first, then only a real mapping
# change on the currently-active provider may rebuild the live catalog. Non-active providers and
# unrelated provider edits must not mutate ~/.codex just because the form was saved.
for required in (
    "CAS-AUTO-REVIEW-R29-LIVE-APPLY",
    "let previous_auto_review = existing",
    "let auto_review_changed = input.auto_review_model_overrides.is_some()",
    "&& previous_auto_review != next_auto_review",
    "let edited_active_provider = active_id.as_deref() == Some(id.as_str())",
    "if auto_review_changed && edited_active_provider",
    "sync_desktop_for_active_provider(&state).await",
    'response["autoReviewApplied"] = Value::Bool(applied)',
):
    if required not in crud:
        raise SystemExit(f"r29 review: live Auto Review apply invariant missing: {required}")
if crud.count("sync_desktop_for_active_provider(&state).await") != 1:
    raise SystemExit("r29 review: update_provider may re-sync the active provider at most once")

# 11) Saving an override must not silently restart Codex. Existing review sessions may have cached
# model metadata, so surface a restart hint after a successful live catalog rebuild and surface sync
# failure separately. The existing explicit Restart button remains the user's control point.
for required in (
    "CAS-AUTO-REVIEW-R29-SAVE-FEEDBACK",
    "updateResult?.autoReviewChanged",
    "updateResult.autoReviewApplied === false",
    "providerForm.autoReviewUi.savedButApplyFailed",
    "providerForm.autoReviewUi.appliedRestart",
    "providerForm.autoReviewUi.savedInactive",
):
    if required not in parent:
        raise SystemExit(f"r29 review: save/apply feedback missing: {required}")
if "restartCodexApp(" in parent:
    raise SystemExit("r29 review: provider save must not auto-restart Codex")

# 12) Default behavior is intentionally preserved: an empty mapping means there is no explicit
# per-model override. The r24 copy-on-write layer then leaves the source catalog's reviewer behavior
# alone (in the user's current real test this resolves to codex-auto-review). Do not introduce a
# hard-coded codex-auto-review rewrite or an implicit reviewer value in the editor.
for forbidden in (
    'out[main] = "codex-auto-review"',
    "reviewer: 'codex-auto-review'",
    'reviewer: "codex-auto-review"',
):
    if forbidden in component or forbidden in effective_script:
        raise SystemExit(f"r29 review: default reviewer was hard-coded unexpectedly: {forbidden}")

# 13) Explicit scope freeze requested after the provider-identity investigation: r29 must not change
# r27's built-in openai fallback/model-provider behavior. That remains a later independent option.
for text, label in (
    (component, "editor"),
    (apply_script, "UI overlay"),
    (effective_script, "effective overlay"),
):
    for forbidden in ("model_provider", "openai_base_url", "chatgpt_base_url", "model_providers.OpenAi"):
        if forbidden in text:
            raise SystemExit(f"r29 review: {label} unexpectedly touches provider identity/routing: {forbidden}")

# 14) r29 must not become a second model-catalog implementation. r24 remains authoritative; the
# effective companion may only trigger the existing desktop sync after registry persistence.
for text, label in ((component, "editor"), (parent, "provider form"), (effective_script, "effective overlay")):
    for forbidden in ("model-catalog-overlays/auto-review", "save_raw_config", "model_catalog_json ="):
        if forbidden in text:
            raise SystemExit(f"r29 review: {label} unexpectedly touches catalog storage: {forbidden}")

print("r29 deep Auto Review provider-model-list/effective override review: PASS")
