from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "frontend/src/components/provider/ProviderFormModal.vue"
COMPONENT = ROOT / "frontend/src/components/provider/AutoReviewModelOverridesEditor.vue"
ZH = ROOT / "frontend/src/i18n/zh.ts"
EN = ROOT / "frontend/src/i18n/en.ts"
MARKER = "CAS-AUTO-REVIEW-UI-R29"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r29 {label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


COMPONENT_SOURCE = r'''<script setup lang="ts">
// CAS-AUTO-REVIEW-UI-R29
// Visual editor for the existing r24 autoReviewModelOverrides map.
// It consumes the provider model list owned by ProviderFormModal and emits the same
// backward-compatible JSON string contract; no catalog/network/credential code lives here.
import { computed, ref, watch } from 'vue'
import { t, tFmt } from '@/i18n'
import AppButton from '@/components/ui/AppButton.vue'
import AppSelect from '@/components/ui/AppSelect.vue'

type ModelOpt = { value: string; label: string }
type MappingRow = { id: number; main: string; reviewer: string }

const props = withDefaults(
  defineProps<{
    modelValue: string
    models: ModelOpt[]
    loading?: boolean
  }>(),
  { loading: false },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  refresh: []
}>()

const rows = ref<MappingRow[]>([])
const legacyInvalid = ref(false)
let nextRowId = 1

function parseMap(raw: string): Record<string, string> | null {
  const trimmed = raw.trim()
  if (!trimmed) return {}
  try {
    const value: unknown = JSON.parse(trimmed)
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    const out: Record<string, string> = {}
    for (const [main, reviewer] of Object.entries(value as Record<string, unknown>)) {
      if (typeof reviewer !== 'string' || !main.trim() || !reviewer.trim()) return null
      out[main.trim()] = reviewer.trim()
    }
    return out
  } catch {
    return null
  }
}

function serializeRows(): string {
  const out: Record<string, string> = {}
  for (const row of rows.value) {
    const main = row.main.trim()
    const reviewer = row.reviewer.trim()
    // Incomplete rows stay visible while editing but are never persisted.
    if (main && reviewer) out[main] = reviewer
  }
  return Object.keys(out).length ? JSON.stringify(out) : ''
}

function hydrate(raw: string) {
  const parsed = parseMap(raw)
  legacyInvalid.value = parsed === null
  if (parsed === null) {
    rows.value = []
    return
  }
  rows.value = Object.entries(parsed).map(([main, reviewer]) => ({
    id: nextRowId++,
    main,
    reviewer,
  }))
}

watch(
  () => props.modelValue,
  (raw) => {
    const parsed = parseMap(raw)
    if (parsed !== null && JSON.stringify(parsed) === (serializeRows() || '{}')) return
    hydrate(raw)
  },
  { immediate: true },
)

const mergedOptions = computed<ModelOpt[]>(() => {
  const seen = new Map<string, string>()
  for (const option of props.models) {
    const value = option.value.trim()
    if (value && !seen.has(value)) seen.set(value, option.label || value)
  }
  // Existing mappings remain editable even if /models is temporarily unavailable or
  // an upstream model disappeared after the mapping was saved.
  for (const row of rows.value) {
    for (const value of [row.main, row.reviewer]) {
      const trimmed = value.trim()
      if (trimmed && !seen.has(trimmed)) seen.set(trimmed, trimmed)
    }
  }
  return [...seen].map(([value, label]) => ({ value, label }))
})

const reviewerOptions = computed<ModelOpt[]>(() => [
  { value: '', label: t('providerForm.autoReviewUi.selectReviewer') },
  ...mergedOptions.value,
])

function mainOptions(row: MappingRow): ModelOpt[] {
  // The serialized form is an object map. Prevent duplicate main-model keys instead
  // of silently letting the last duplicate row overwrite an earlier one.
  const usedByOthers = new Set(
    rows.value
      .filter((candidate) => candidate.id !== row.id)
      .map((candidate) => candidate.main.trim())
      .filter(Boolean),
  )
  return [
    { value: '', label: t('providerForm.autoReviewUi.selectMain') },
    ...mergedOptions.value.filter((option) => !usedByOthers.has(option.value)),
  ]
}

const canAdd = computed(() => {
  if (!mergedOptions.value.length || props.loading) return false
  if (rows.value.some((row) => !row.main.trim() || !row.reviewer.trim())) return false
  const used = new Set(rows.value.map((row) => row.main.trim()).filter(Boolean))
  return mergedOptions.value.some((option) => !used.has(option.value))
})

function addRow() {
  if (!canAdd.value) return
  rows.value.push({ id: nextRowId++, main: '', reviewer: '' })
}

function removeRow(id: number) {
  rows.value = rows.value.filter((row) => row.id !== id)
  legacyInvalid.value = false
  emit('update:modelValue', serializeRows())
}

function rowChanged() {
  legacyInvalid.value = false
  emit('update:modelValue', serializeRows())
}
</script>

<template>
  <div class="armap">
    <div class="armap__top">
      <div class="armap__meta">
        <strong>{{ t('providerForm.autoReviewUi.title') }}</strong>
        <span>{{ tFmt('providerForm.autoReviewUi.available', { count: mergedOptions.length }) }}</span>
        <small>{{ t('providerForm.autoReviewUi.hint') }}</small>
      </div>
      <AppButton
        size="sm"
        variant="ghost"
        :label="loading ? t('providerForm.fetching') : t('providerForm.autoReviewUi.refresh')"
        :disabled="loading"
        @click="emit('refresh')"
      />
    </div>

    <div v-if="legacyInvalid" class="armap__warning">
      {{ t('providerForm.autoReviewUi.legacyInvalid') }}
    </div>

    <div v-if="rows.length" class="armap__rows">
      <div v-for="row in rows" :key="row.id" class="armap__row">
        <div class="armap__select">
          <span class="armap__caption">{{ t('providerForm.autoReviewUi.source') }}</span>
          <AppSelect v-model="row.main" :options="mainOptions(row)" @update:model-value="rowChanged" />
        </div>
        <span class="armap__arrow" aria-hidden="true">→</span>
        <div class="armap__select">
          <span class="armap__caption">{{ t('providerForm.autoReviewUi.reviewer') }}</span>
          <AppSelect v-model="row.reviewer" :options="reviewerOptions" @update:model-value="rowChanged" />
        </div>
        <AppButton
          class="armap__remove"
          size="sm"
          variant="ghost"
          :label="t('common.delete')"
          @click="removeRow(row.id)"
        />
      </div>
    </div>

    <div v-else class="armap__empty">
      {{ mergedOptions.length ? t('providerForm.autoReviewUi.none') : t('providerForm.autoReviewUi.empty') }}
    </div>

    <div class="armap__bottom">
      <small v-if="rows.some((row) => !row.main.trim() || !row.reviewer.trim())" class="armap__pending">
        {{ t('providerForm.autoReviewUi.pending') }}
      </small>
      <span v-else></span>
      <AppButton
        size="sm"
        variant="secondary"
        :label="t('providerForm.autoReviewUi.add')"
        :disabled="!canAdd"
        @click="addRow"
      />
    </div>
  </div>
</template>

<style scoped>
.armap {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-subtle);
}
.armap__top,
.armap__bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.armap__meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: var(--text-secondary);
  font-size: var(--fs-sm);
}
.armap__meta strong {
  color: var(--text);
  font-size: var(--fs-sm);
}
.armap__meta small {
  color: var(--text-muted);
  line-height: 1.35;
}
.armap__rows {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.armap__row {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) 24px minmax(150px, 1fr) auto;
  align-items: end;
  gap: var(--space-2);
}
.armap__select {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.armap__caption {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}
.armap__arrow {
  align-self: center;
  margin-top: 17px;
  color: var(--text-muted);
  text-align: center;
}
.armap__remove {
  align-self: end;
}
.armap__empty,
.armap__warning,
.armap__pending {
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.armap__warning {
  color: var(--danger);
}
.armap__pending {
  color: var(--warning, var(--text-muted));
}
@media (max-width: 760px) {
  .armap__row {
    grid-template-columns: 1fr;
  }
  .armap__arrow {
    margin-top: 0;
    transform: rotate(90deg);
  }
  .armap__remove {
    justify-self: end;
  }
}
</style>
'''

COMPONENT.parent.mkdir(parents=True, exist_ok=True)
COMPONENT.write_text(COMPONENT_SOURCE, encoding="utf-8")
print("r29 wrote frontend/src/components/provider/AutoReviewModelOverridesEditor.vue")

parent = PARENT.read_text(encoding="utf-8")
if "AutoReviewModelOverridesEditor" not in parent:
    parent = replace_once(
        parent,
        "import Sub2ApiGrokCompatControls from '@/components/provider/Sub2ApiGrokCompatControls.vue'\n",
        "import Sub2ApiGrokCompatControls from '@/components/provider/Sub2ApiGrokCompatControls.vue'\n"
        "import AutoReviewModelOverridesEditor from '@/components/provider/AutoReviewModelOverridesEditor.vue'\n",
        "component import",
    )

if "CAS-AUTO-REVIEW-UI-R29-SILENT-FETCH" not in parent:
    parent = replace_once(
        parent,
        "async function fetchModels() {",
        "async function fetchModels(silent = false) { // CAS-AUTO-REVIEW-UI-R29-SILENT-FETCH",
        "silent fetch signature",
    )
    # CAS-AUTO-REVIEW-UI-R29-UNIQUE-SUCCESS-ANCHOR: the r27 function contains the
    # same toast in both the normal-success and fallback-success branches. Anchor the normal one
    # together with the following catch boundary instead of pretending the toast text is unique.
    parent = replace_once(
        parent,
        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\n"
        "  } catch (e) {",
        "    if (!silent) toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\n"
        "  } catch (e) {",
        "silent fetch success toast",
    )
    parent = replace_once(
        parent,
        "    if (availableModels.value.length > 0) {\n"
        "      toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\n"
        "    } else {\n"
        "      error.value = (e as Error).message || t('providerForm.modelsFetchFailed')\n"
        "    }",
        "    if (availableModels.value.length > 0) {\n"
        "      if (!silent) toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\n"
        "    } else if (!silent) {\n"
        "      error.value = (e as Error).message || t('providerForm.modelsFetchFailed')\n"
        "    }",
        "silent fetch fallback",
    )
    parent = replace_once(
        parent,
        "    const suggested = res.suggested || {}\n"
        "    const valid = new Set(availableModels.value.map((o) => o.value))\n"
        "    for (const slot of Object.keys(form.models)) {\n"
        "      const sv = suggested[slot]\n"
        "      if (sv && !form.models[slot] && valid.has(sv)) form.models[slot] = sv\n"
        "    }",
        "    if (!silent) { // CAS-AUTO-REVIEW-UI-R29-SILENT-NO-SUGGEST\n"
        "      const suggested = res.suggested || {}\n"
        "      const valid = new Set(availableModels.value.map((o) => o.value))\n"
        "      for (const slot of Object.keys(form.models)) {\n"
        "        const sv = suggested[slot]\n"
        "        if (sv && !form.models[slot] && valid.has(sv)) form.models[slot] = sv\n"
        "      }\n"
        "    }",
        "silent refresh must not mutate model slots",
    )
    parent = replace_once(
        parent,
        "  form.apiKey = secret.apiKey || ''\n",
        "  form.apiKey = secret.apiKey || ''\n"
        "  // CAS-AUTO-REVIEW-UI-R29-AUTO-FETCH: cache/declared models are already visible;\n"
        "  // now refresh the exact provider /models list only after its stored secret is available.\n"
        "  // Failure stays silent so opening Edit never destroys an existing mapping.\n"
        "  void fetchModels(true)\n",
        "edit auto fetch",
    )

if "CAS-AUTO-REVIEW-UI-R29-EDITOR" not in parent:
    old_ui = '''      <SettingsRow :title="t('providerForm.autoReviewModelOverrides')">
        <div class="pf__auto-review">
          <textarea
            v-model="form.autoReviewModelOverrides"
            class="pf__json"
            spellcheck="false"
            placeholder='{"grok-4.5":"gpt-5.6-luna"}'
          ></textarea>
          <small>{{ t('providerForm.autoReviewModelOverridesHint') }}</small>
        </div>
      </SettingsRow>'''
    new_ui = '''      <SettingsRow :title="t('providerForm.autoReviewModelOverrides')">
        <!-- CAS-AUTO-REVIEW-UI-R29-EDITOR -->
        <AutoReviewModelOverridesEditor
          v-model="form.autoReviewModelOverrides"
          :models="availableModels"
          :loading="fetching"
          @refresh="fetchModels()"
        />
      </SettingsRow>'''
    parent = replace_once(parent, old_ui, new_ui, "JSON textarea -> visual mapping editor")

PARENT.write_text(parent, encoding="utf-8")
print("r29 patched frontend/src/components/provider/ProviderFormModal.vue")

zh_keys = '''  "providerForm.autoReviewUi.title": "按模型指定 Auto Review",
  "providerForm.autoReviewUi.source": "主模型",
  "providerForm.autoReviewUi.reviewer": "Auto Review 模型",
  "providerForm.autoReviewUi.add": "+ 添加映射",
  "providerForm.autoReviewUi.refresh": "刷新模型列表",
  "providerForm.autoReviewUi.selectMain": "选择主模型",
  "providerForm.autoReviewUi.selectReviewer": "选择审查模型",
  "providerForm.autoReviewUi.available": "当前 provider 可选 {count} 个模型",
  "providerForm.autoReviewUi.hint": "直接从当前 provider 模型列表选择“主模型 → 审查模型”。未列出的主模型继续继承原 catalog 配置；外部 model_catalog_json 仍保持只读。",
  "providerForm.autoReviewUi.empty": "当前没有可用模型。点击“刷新模型列表”拉取当前 provider 的 /models。",
  "providerForm.autoReviewUi.none": "尚未设置按模型覆盖。点击“添加映射”开始设置。",
  "providerForm.autoReviewUi.pending": "先把当前行两边都选好，才能继续添加下一条。",
  "providerForm.autoReviewUi.legacyInvalid": "现有 Auto Review 映射格式无效；请重新建立映射后再保存。",
'''
en_keys = '''  "providerForm.autoReviewUi.title": "Per-model Auto Review",
  "providerForm.autoReviewUi.source": "Main model",
  "providerForm.autoReviewUi.reviewer": "Auto Review model",
  "providerForm.autoReviewUi.add": "+ Add mapping",
  "providerForm.autoReviewUi.refresh": "Refresh models",
  "providerForm.autoReviewUi.selectMain": "Select main model",
  "providerForm.autoReviewUi.selectReviewer": "Select review model",
  "providerForm.autoReviewUi.available": "{count} models available from this provider",
  "providerForm.autoReviewUi.hint": "Choose main model → review model directly from this provider's model list. Unlisted main models keep the existing catalog behavior and external model_catalog_json stays read-only.",
  "providerForm.autoReviewUi.empty": "No models are available yet. Refresh this provider's /models list first.",
  "providerForm.autoReviewUi.none": "No per-model override yet. Add a mapping to begin.",
  "providerForm.autoReviewUi.pending": "Finish both selections in this row before adding another mapping.",
  "providerForm.autoReviewUi.legacyInvalid": "The existing Auto Review mapping is invalid; rebuild it before saving.",
'''

for path, block in ((ZH, zh_keys), (EN, en_keys)):
    text = path.read_text(encoding="utf-8")
    if '"providerForm.autoReviewUi.title"' not in text:
        text = replace_once(
            text,
            '  "pluginUnlock.disconnected":',
            block + '  "pluginUnlock.disconnected":',
            f"i18n insertion {path.name}",
        )
        path.write_text(text, encoding="utf-8")
        print(f"r29 patched {path.relative_to(ROOT)}")

# Fail closed if an upstream replay partially resurrects the raw JSON UI or drops any
# provider-list wiring. The deeper semantic checks live in review_auto_review_ui_r29.py.
parent = PARENT.read_text(encoding="utf-8")
for item in (
    "CAS-AUTO-REVIEW-UI-R29-EDITOR",
    "CAS-AUTO-REVIEW-UI-R29-SILENT-FETCH",
    "CAS-AUTO-REVIEW-UI-R29-AUTO-FETCH",
    "<AutoReviewModelOverridesEditor",
    ':models="availableModels"',
    '@refresh="fetchModels()"',
):
    if item not in parent:
        raise SystemExit(f"r29 parent materialization missing: {item}")
if 'placeholder=\'{"grok-4.5":"gpt-5.6-luna"}\'' in parent:
    raise SystemExit("r29 old raw Auto Review JSON textarea is still present")

component = COMPONENT.read_text(encoding="utf-8")
for item in (
    MARKER,
    "mergedOptions",
    "mainOptions(row)",
    "serializeRows()",
    "emit('update:modelValue'",
    "emit('refresh')",
):
    if item not in component:
        raise SystemExit(f"r29 editor materialization missing: {item}")

print("r29 Auto Review provider-model-list UI overlay: PASS")
