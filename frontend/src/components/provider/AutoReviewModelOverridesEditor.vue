<script setup lang="ts">
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
