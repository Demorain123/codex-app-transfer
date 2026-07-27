from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r29 effective {label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


# 1) CAS-AUTO-REVIEW-R29-API-WIRE
# r24 added the field to Provider/ProviderPayload and ProviderForm, but did not add it to
# mapProvider/providerBody. The UI could therefore show/save a value in memory while the HTTP PUT
# silently dropped it. Wire both read and write directions without changing the legacy payload shape.
path = "frontend/src/api/providers.ts"
text = read(path)
text = replace_once(
    text,
    "    reviewModelSlot: provider.reviewModelSlot || '',\n",
    "    reviewModelSlot: provider.reviewModelSlot || '',\n"
    "    autoReviewModelOverrides: provider.autoReviewModelOverrides || {}, // CAS-AUTO-REVIEW-R29-API-WIRE-READ\n",
    "provider map read",
)
text = replace_once(
    text,
    "  if (payload.reviewModelSlot !== undefined && payload.reviewModelSlot !== null)\n"
    "    body.reviewModelSlot = payload.reviewModelSlot\n",
    "  if (payload.reviewModelSlot !== undefined && payload.reviewModelSlot !== null)\n"
    "    body.reviewModelSlot = payload.reviewModelSlot\n"
    "  // CAS-AUTO-REVIEW-R29-API-WIRE-WRITE: preserve an explicit empty object so update can clear\n"
    "  // a previous override instead of confusing ‘clear’ with ‘field omitted’.\n"
    "  if (payload.autoReviewModelOverrides !== undefined)\n"
    "    body.autoReviewModelOverrides = payload.autoReviewModelOverrides\n",
    "provider body write",
)
write(path, text)


# 2) CAS-AUTO-REVIEW-R29-LIVE-APPLY
# update_provider historically only mutated Transfer's registry. For the active provider that meant
# a newly-saved autoReviewModelOverrides map did not rebuild ~/.codex's copy-on-write catalog until
# a later provider apply/restart. Re-sync only when the effective map actually changed and the edited
# provider is active. Registry persistence remains authoritative even if the live sync fails; the
# response exposes that failure so the UI can tell the user rather than silently claiming success.
#
# IMPORTANT: use a semantic marker around the *whole Rust patch*. cargo fmt legitimately rewrites
# the generated Rust, so exact `new in text` replay checks are not stable after formatting. Once the
# marker exists we validate the behavior and skip textual reinsertion entirely.
path = "src-tauri/src/admin/handlers/providers/crud.rs"
text = read(path)
if "CAS-AUTO-REVIEW-R29-LIVE-APPLY" not in text:
    text = replace_once(
        text,
        "use super::super::desktop::switch_provider_and_sync;\n",
        "use super::super::desktop::{sync_desktop_for_active_provider, switch_provider_and_sync};\n",
        "desktop sync import",
    )
    text = replace_once(
        text,
        "pub async fn update_provider(\n    Path(id): Path<String>,\n    Json(input): Json<AddProviderInput>,\n) -> impl IntoResponse {\n",
        "pub async fn update_provider(\n    State(state): State<AdminState>,\n    Path(id): Path<String>,\n    Json(input): Json<AddProviderInput>,\n) -> impl IntoResponse {\n",
        "update provider state extractor",
    )
    text = replace_once(
        text,
        "    let result = with_config_write(|cfg| {\n        let Some(idx) = provider_index(cfg, &id) else {\n",
        "    let result = with_config_write(|cfg| {\n"
        "        // CAS-AUTO-REVIEW-R29-LIVE-APPLY: capture active identity before borrowing providers mutably.\n"
        "        let active_id = cfg\n"
        "            .get(\"activeProvider\")\n"
        "            .and_then(|v| v.as_str())\n"
        "            .map(str::to_owned);\n"
        "        let Some(idx) = provider_index(cfg, &id) else {\n",
        "capture active provider",
    )
    text = replace_once(
        text,
        "        let existing = providers[idx].as_object().unwrap().clone();\n        let mut updated = existing.clone();\n",
        "        let existing = providers[idx].as_object().unwrap().clone();\n"
        "        let previous_auto_review = existing\n"
        "            .get(\"autoReviewModelOverrides\")\n"
        "            .cloned()\n"
        "            .unwrap_or_else(|| json!({}));\n"
        "        let mut updated = existing.clone();\n",
        "capture previous override",
    )
    text = replace_once(
        text,
        "        let updated_value = Value::Object(updated);\n        providers[idx] = updated_value.clone();\n        Ok(ConfigMutation::Modified(updated_value))\n",
        "        let next_auto_review = updated\n"
        "            .get(\"autoReviewModelOverrides\")\n"
        "            .cloned()\n"
        "            .unwrap_or_else(|| json!({}));\n"
        "        let auto_review_changed = input.auto_review_model_overrides.is_some()\n"
        "            && previous_auto_review != next_auto_review;\n"
        "        let edited_active_provider = active_id.as_deref() == Some(id.as_str());\n"
        "        let updated_value = Value::Object(updated);\n"
        "        providers[idx] = updated_value.clone();\n"
        "        Ok(ConfigMutation::Modified((\n"
        "            updated_value,\n"
        "            auto_review_changed,\n"
        "            edited_active_provider,\n"
        "        )))\n",
        "return live apply metadata",
    )
    text = replace_once(
        text,
        "    let updated_value = match result {\n        Ok(v) => v,\n",
        "    let (updated_value, auto_review_changed, edited_active_provider) = match result {\n        Ok(v) => v,\n",
        "destructure update result",
    )
    text = replace_once(
        text,
        "    Json(json!({\"success\": true, \"provider\": public_provider(&updated_value)})).into_response()\n}\n",
        "    let mut response = json!({\n"
        "        \"success\": true,\n"
        "        \"provider\": public_provider(&updated_value),\n"
        "        \"autoReviewChanged\": auto_review_changed,\n"
        "        \"autoReviewActiveProvider\": edited_active_provider,\n"
        "    });\n"
        "    if auto_review_changed && edited_active_provider {\n"
        "        let desktop_sync = sync_desktop_for_active_provider(&state).await;\n"
        "        let applied = desktop_sync\n"
        "            .get(\"success\")\n"
        "            .and_then(|v| v.as_bool())\n"
        "            .unwrap_or(false);\n"
        "        response[\"autoReviewApplied\"] = Value::Bool(applied);\n"
        "        response[\"autoReviewApply\"] = desktop_sync;\n"
        "    }\n"
        "    Json(response).into_response()\n"
        "}\n",
        "sync changed active override",
    )
    write(path, text)
else:
    for required in (
        "sync_desktop_for_active_provider",
        "previous_auto_review",
        "auto_review_changed",
        "edited_active_provider",
        'response["autoReviewApplied"]',
    ):
        if required not in text:
            raise SystemExit(f"r29 effective rustfmt replay marker exists but behavior is incomplete: {required}")
    print("r29 live-apply Rust patch already materialized; semantic replay validation PASS")


# 3) CAS-AUTO-REVIEW-R29-SAVE-FEEDBACK
# Surface the distinction between registry-save, live catalog apply, and Codex process reload. Do not
# automatically restart Codex from a provider form save: that could interrupt active work. The user
# gets a precise success/warning and can restart when convenient.
path = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(path)
text = replace_once(
    text,
    "    if (props.editId) {\n      await providersApi.updateProvider(props.editId, payload)\n    } else {\n",
    "    let updateResult: Awaited<ReturnType<typeof providersApi.updateProvider>> | null = null\n"
    "    if (props.editId) {\n"
    "      updateResult = await providersApi.updateProvider(props.editId, payload)\n"
    "    } else {\n",
    "capture update response",
)
text = replace_once(
    text,
    "    await store.load().catch(() => {})\n    emit('saved')\n    emit('close')\n",
    "    await store.load().catch(() => {})\n"
    "    // CAS-AUTO-REVIEW-R29-SAVE-FEEDBACK: save != live apply != process reload.\n"
    "    if (updateResult?.autoReviewChanged) {\n"
    "      if (updateResult.autoReviewActiveProvider && updateResult.autoReviewApplied === false) {\n"
    "        const detail = updateResult.autoReviewApply?.message || t('providerForm.autoReviewUi.applyFailed')\n"
    "        toast(tFmt('providerForm.autoReviewUi.savedButApplyFailed', { detail }), 'error')\n"
    "      } else if (updateResult.autoReviewActiveProvider && updateResult.autoReviewApplied) {\n"
    "        toast(t('providerForm.autoReviewUi.appliedRestart'))\n"
    "      } else {\n"
    "        toast(t('providerForm.autoReviewUi.savedInactive'))\n"
    "      }\n"
    "    }\n"
    "    emit('saved')\n"
    "    emit('close')\n",
    "save apply feedback",
)
write(path, text)


# 4) API response typing. Keep add/delete etc. untouched.
path = "frontend/src/api/providers.ts"
text = read(path)
text = replace_once(
    text,
    "export const updateProvider = (id: string, payload: ProviderPayload) =>\n  api('PUT', `/api/providers/${id}`, providerBody(payload))\n",
    "export interface ProviderUpdateResp {\n"
    "  success?: boolean\n"
    "  provider?: Record<string, unknown>\n"
    "  autoReviewChanged?: boolean\n"
    "  autoReviewActiveProvider?: boolean\n"
    "  autoReviewApplied?: boolean\n"
    "  autoReviewApply?: { success?: boolean; message?: string; [key: string]: unknown }\n"
    "}\n"
    "export const updateProvider = (id: string, payload: ProviderPayload) =>\n"
    "  api<ProviderUpdateResp>('PUT', `/api/providers/${id}`, providerBody(payload))\n",
    "update response type",
)
write(path, text)


# 5) User-facing semantics: empty mapping means preserve Codex default; explicit mapping is a rescue
# override. Restart wording is intentionally explicit because an already-running auto_review session
# may have cached model metadata even after the shadow catalog is rebuilt.
for rel, anchor, block in [
    (
        "frontend/src/i18n/zh.ts",
        '  "providerForm.autoReviewUi.title":',
        '  "providerForm.autoReviewUi.applyFailed": "live catalog 重建失败",\n'
        '  "providerForm.autoReviewUi.savedButApplyFailed": "Auto Review 映射已保存，但当前 Codex catalog 未能重新应用：{detail}",\n'
        '  "providerForm.autoReviewUi.appliedRestart": "Auto Review 覆盖已写入当前 catalog；重启 Codex 后，新审批线程会使用新 reviewer。",\n'
        '  "providerForm.autoReviewUi.savedInactive": "Auto Review 映射已保存；切换/应用该 provider 后生效。",\n'
    ),
    (
        "frontend/src/i18n/en.ts",
        '  "providerForm.autoReviewUi.title":',
        '  "providerForm.autoReviewUi.applyFailed": "live catalog rebuild failed",\n'
        '  "providerForm.autoReviewUi.savedButApplyFailed": "The Auto Review mapping was saved, but the active Codex catalog could not be reapplied: {detail}",\n'
        '  "providerForm.autoReviewUi.appliedRestart": "The Auto Review override is written to the active catalog. Restart Codex so new approval threads use the new reviewer.",\n'
        '  "providerForm.autoReviewUi.savedInactive": "The Auto Review mapping is saved and will apply when this provider is activated/applied.",\n'
    ),
]:
    text = read(rel)
    if "providerForm.autoReviewUi.appliedRestart" not in text:
        idx = text.find(anchor)
        if idx < 0:
            raise SystemExit(f"r29 effective i18n anchor missing: {rel}")
        text = text[:idx] + block + text[idx:]
        write(rel, text)


# Final fail-closed markers.
checks = {
    "frontend/src/api/providers.ts": [
        "CAS-AUTO-REVIEW-R29-API-WIRE-READ",
        "CAS-AUTO-REVIEW-R29-API-WIRE-WRITE",
        "body.autoReviewModelOverrides = payload.autoReviewModelOverrides",
    ],
    "src-tauri/src/admin/handlers/providers/crud.rs": [
        "CAS-AUTO-REVIEW-R29-LIVE-APPLY",
        "autoReviewChanged",
        "sync_desktop_for_active_provider(&state).await",
    ],
    "frontend/src/components/provider/ProviderFormModal.vue": [
        "CAS-AUTO-REVIEW-R29-SAVE-FEEDBACK",
        "autoReviewApplied",
    ],
}
for rel, markers in checks.items():
    text = read(rel)
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r29 effective materialization missing {rel}: {marker}")

print("r29 effective Auto Review override wiring/live-apply overlay: PASS")
