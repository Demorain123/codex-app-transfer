<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import SettingsRow from '@/components/ui/SettingsRow.vue'
import AppSwitch from '@/components/ui/AppSwitch.vue'

const props = defineProps<{
  enabled: boolean
  cacheEnabled: boolean
}>()

const emit = defineEmits<{
  'update:enabled': [value: boolean]
  'update:cacheEnabled': [value: boolean]
}>()

function setEnabled(value: boolean) {
  emit('update:enabled', value)
  if (!value && props.cacheEnabled) emit('update:cacheEnabled', false)
}

// CAS-R87-SUB2API-COMPAT-GUARD-READONLY
// Deliberately passive: this card must not issue /health, /models, /responses,
// retries, or configuration mutations. It reports only what this form already
// knows plus Transfer-owned fallback capabilities that are packaged locally.
type GuardTone = 'ok' | 'neutral' | 'warn'
type GuardRow = { key: string; label: string; value: string; tone: GuardTone }

const guardSummary = computed(() =>
  props.enabled ? 'Guarded · unverified' : 'Native passthrough',
)

const guardRows = computed<GuardRow[]>(() => [
  {
    key: 'responses',
    label: 'Responses protocol',
    value: 'Configured',
    tone: 'ok',
  },
  {
    key: 'grok',
    label: 'Grok compatibility',
    value: props.enabled ? 'Armed for grok-* only' : 'Off · native passthrough',
    tone: props.enabled ? 'ok' : 'neutral',
  },
  {
    key: 'cache',
    label: 'Free cache compatibility',
    value: props.enabled && props.cacheEnabled ? 'Armed' : 'Off',
    tone: props.enabled && props.cacheEnabled ? 'warn' : 'neutral',
  },
  {
    key: 'compact',
    label: 'Compact / history fallback',
    value: 'Transfer-owned · armed',
    tone: 'ok',
  },
  {
    key: 'models',
    label: 'Model catalog',
    value: 'Not actively probed',
    tone: 'neutral',
  },
  {
    key: 'transport',
    label: 'HTTP / WS transport fallback',
    value: 'Sub2API-owned · not probed',
    tone: 'neutral',
  },
  {
    key: 'version',
    label: 'Sub2API version',
    value: 'Unknown · no passive signal',
    tone: 'neutral',
  },
])
</script>

<template>
  <div class="compat-card">
    <div class="compat-head">
      <span>{{ t('providerForm.grokCompatSection') }}</span>
      <span class="compat-badge">COMPAT</span>
    </div>
    <SettingsRow
      :title="t('providerForm.grokCompat')"
      :description="t('providerForm.grokCompatHint')"
    >
      <AppSwitch :model-value="enabled" @update:model-value="setEnabled" />
    </SettingsRow>
    <SettingsRow
      :title="t('providerForm.grokFreeCacheCompat')"
      :description="t('providerForm.grokFreeCacheCompatHint')"
    >
      <AppSwitch
        :model-value="cacheEnabled"
        :disabled="!enabled"
        @update:model-value="emit('update:cacheEnabled', $event)"
      />
    </SettingsRow>
    <div v-if="cacheEnabled" class="compat-warning">
      {{ t('providerForm.grokFreeCacheCompatWarning') }}
    </div>

    <section
      class="compat-guard"
      data-cas-r87-compat-guard="readonly"
      aria-label="Sub2API compatibility guard"
    >
      <div class="compat-guard__head">
        <div>
          <div class="compat-guard__title">Sub2API Compatibility Guard</div>
          <div class="compat-guard__subtitle">只读兼容护栏 · zero active probes</div>
        </div>
        <span class="compat-guard__state" :class="{ active: enabled }">{{ guardSummary }}</span>
      </div>

      <div class="compat-guard__rows">
        <div v-for="row in guardRows" :key="row.key" class="compat-guard__row">
          <span class="compat-guard__label">{{ row.label }}</span>
          <span class="compat-guard__value" :class="`tone-${row.tone}`">{{ row.value }}</span>
        </div>
      </div>

      <div class="compat-guard__note">
        r87 不会为了检测兼容性主动调用 /health、/models 或 /responses，也不会自动重放
        502/503/timeout。Transport fallback 继续由 Sub2API 负责；Transfer 只保留协议层的安全保底。
      </div>
    </section>
  </div>
</template>

<style scoped>
.compat-card {
  flex-shrink: 0;
  margin: var(--space-3) 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--accent) 5%, var(--surface));
  overflow: hidden;
}
.compat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4) var(--space-1);
  font-size: var(--fs-sm);
  font-weight: 650;
  color: var(--accent);
}
.compat-badge {
  padding: 2px 7px;
  border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
  border-radius: var(--radius-full);
  font-size: 10px;
  letter-spacing: 0.06em;
}
.compat-warning {
  margin: 0 var(--space-4) var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  line-height: 1.45;
}
.compat-guard {
  margin: var(--space-2) var(--space-4) var(--space-4);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--border-strong) 72%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
}
.compat-guard__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.compat-guard__title {
  font-size: var(--fs-sm);
  font-weight: 650;
  color: var(--text);
}
.compat-guard__subtitle {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.compat-guard__state {
  flex: 0 0 auto;
  padding: 2px 7px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  white-space: nowrap;
}
.compat-guard__state.active {
  border-color: color-mix(in srgb, var(--warning) 48%, var(--border));
  color: var(--warning);
}
.compat-guard__rows {
  display: grid;
  gap: 5px;
}
.compat-guard__row {
  display: grid;
  grid-template-columns: minmax(120px, 0.9fr) minmax(0, 1.1fr);
  gap: var(--space-3);
  align-items: baseline;
  font-size: var(--fs-xs);
}
.compat-guard__label {
  color: var(--text-secondary);
}
.compat-guard__value {
  min-width: 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}
.compat-guard__value.tone-ok {
  color: var(--success);
}
.compat-guard__value.tone-warn {
  color: var(--warning);
}
.compat-guard__note {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.5;
}
@media (max-width: 620px) {
  .compat-guard__head {
    flex-direction: column;
  }
  .compat-guard__row {
    grid-template-columns: 1fr;
    gap: 1px;
  }
}
</style>
